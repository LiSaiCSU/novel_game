"""World simulation with level of detail (Prompt section 31).

The world outside the player's line of sight keeps moving, but it does not cost
an LLM call per NPC per minute. Four bands:

* LOD 0 - the player's scene: full agent decisions (handled by the orchestrator)
* LOD 1 - adjacent locations: schedules and rules
* LOD 2 - the rest of the region: resources, factions, quests, rumours
* LOD 3 - the world: wars, disasters, sect-scale events

Time spent is what escalates detail: a five-minute conversation touches LOD 1;
three years of seclusion runs all four.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character, Event, Quest
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import CharacterType, QuestStatus, Visibility
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.simulation.schedules import ScheduleService
from engine.world.clock import WorldClock
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class SimulationReport:
    minutes: int = 0
    ticks: dict[str, int] = field(default_factory=dict)
    offline_events: list[str] = field(default_factory=list)
    moved_characters: int = 0
    reassigned_quests: list[str] = field(default_factory=list)
    rumours_spread: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "minutes": self.minutes,
            "ticks": self.ticks,
            "offline_events": self.offline_events,
            "moved_characters": self.moved_characters,
            "reassigned_quests": self.reassigned_quests,
            "rumours_spread": self.rumours_spread,
        }


class WorldSimulator:
    def __init__(
        self,
        pack: ContentPack,
        schedules: ScheduleService,
        knowledge: KnowledgeService,
        max_offline_minutes: int = 525_600,
    ) -> None:
        self.pack = pack
        self.schedules = schedules
        self.knowledge = knowledge
        self.max_offline_minutes = max_offline_minutes
        self.tick_minutes: dict[str, int] = {
            "lod1": 240,
            "lod2": 1440,
            "lod3": 10080,
            **{k: int(v) for k, v in (pack.rule("simulation.tick_minutes", {}) or {}).items()},
        }
        self.max_ticks = int(pack.rule("simulation.max_ticks_per_advance", 400))
        self.offline_chance = pack.rule("simulation.offline_event_chance_per_week", {}) or {}

    # ------------------------------------------------------------------
    async def advance(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        minutes: int,
        change_set: ChangeSet,
        *,
        rng,
        event_builder: EventBuilder,
    ) -> SimulationReport:
        minutes = max(0, min(int(minutes), self.max_offline_minutes))
        report = SimulationReport(minutes=minutes)
        if minutes <= 0:
            return report

        clock: WorldClock = state.clock
        target_minute = state.world.current_minute + minutes
        days = minutes / clock.minutes_per_day
        weeks = days / 7.0

        characters = await uow.characters.list_for_world(state.world.id)
        alive = [c for c in characters if c.alive and c.character_type is not CharacterType.PLAYER]

        # -- LOD 1: everyone follows their day ------------------------------
        report.ticks["lod1"] = max(1, minutes // self.tick_minutes["lod1"])
        end_time = clock.to_world_time(target_minute)
        moves = self.schedules.move_changes(
            alive, state.graph, end_time, exclude_ids={state.player.id}
        )
        change_set.extend(moves)
        report.moved_characters = len(moves)

        # -- LOD 2: regions drift ------------------------------------------
        if minutes >= self.tick_minutes["lod2"]:
            report.ticks["lod2"] = minutes // self.tick_minutes["lod2"]
            await self._simulate_factions(uow, state, change_set, weeks=weeks, rng=rng)
            report.reassigned_quests = await self._expire_quests(
                uow, state, change_set, target_minute, event_builder, rng
            )

        # -- LOD 3: world-scale beats ---------------------------------------
        if minutes >= self.tick_minutes["lod3"]:
            report.ticks["lod3"] = minutes // self.tick_minutes["lod3"]
            report.offline_events = self._roll_offline_events(
                state, change_set, event_builder, weeks=weeks, rng=rng
            )

        # -- information keeps moving too -----------------------------------
        if days >= 1.0:
            spread = await self.knowledge.propagate(
                uow,
                state.world.id,
                days_elapsed=days,
                at_minute=target_minute,
                rng=rng,
                candidates=alive,
            )
            change_set.extend(spread)
            report.rumours_spread = len(spread)

        # -- passive recovery for everyone off screen ------------------------
        change_set.extend(self._recover(alive, minutes))
        return report

    # ------------------------------------------------------------------
    async def _simulate_factions(
        self, uow: UnitOfWork, state: WorldStateView, change_set: ChangeSet, *, weeks: float, rng
    ) -> None:
        drift = self.pack.rule("simulation.faction_drift_per_week", {}) or {}
        for faction in await uow.factions.list_for_world(state.world.id):
            for field_name, bounds in drift.items():
                low, high = float(bounds["min"]), float(bounds["max"])
                delta = rng.uniform(low, high) * min(weeks, 52.0)
                if field_name == "resources":
                    before = dict(faction.resources)
                    after = {
                        k: round(max(0.0, v * (1.0 + delta)), 4) for k, v in before.items()
                    }
                    if after != before:
                        change_set.add(
                            mut.faction_field(
                                faction.id, "resources", before, after, reason="offline_drift"
                            )
                        )
                elif hasattr(faction, field_name):
                    before_value = float(getattr(faction, field_name))
                    after_value = round(before_value + delta, 3)
                    if abs(after_value - before_value) >= 0.01:
                        change_set.add(
                            mut.faction_field(
                                faction.id,
                                field_name,
                                before_value,
                                after_value,
                                reason="offline_drift",
                            )
                        )

    async def _expire_quests(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        change_set: ChangeSet,
        target_minute: int,
        event_builder: EventBuilder,
        rng,
    ) -> list[str]:
        """Prompt section 42: the world does not wait for the player.

        An offered task the player ignored gets picked up by somebody else, and
        that somebody may fail.
        """
        reassigned: list[str] = []
        for quest in await uow.quests.list_for_world(state.world.id):
            if quest.status is not QuestStatus.OFFERED:
                continue
            if quest.expires_at_minute is None or target_minute < quest.expires_at_minute:
                continue
            consequences = quest.world_consequences.get("if_player_refuses", {}) or {}
            candidates = list(consequences.get("reassign_to", []) or [])
            if not candidates:
                change_set.add(
                    mut.quest_status(quest.id, str(quest.status), str(QuestStatus.EXPIRED), reason="deadline")
                )
                continue
            taker = rng.choice(candidates)
            success_chance = float(consequences.get("success_chance", 0.5))
            succeeded = rng.chance(success_chance)
            change_set.add(
                mut.quest_status(
                    quest.id, str(quest.status), str(QuestStatus.TAKEN_BY_OTHER), reason=f"taken_by:{taker}"
                )
            )
            change_set.add_event(
                event_builder.build(
                    "QUEST_COMPLETED" if succeeded else "QUEST_FAILED",
                    location_id=None,
                    payload={
                        "summary": quest.name,
                        "quest": quest.key,
                        "taken_by": taker,
                        "succeeded": succeeded,
                    },
                    causes=["player_did_not_accept"],
                    world_minute=target_minute,
                    visibility=Visibility.LOCAL,
                )
            )
            reassigned.append(f"{quest.key}->{taker}:{'ok' if succeeded else 'failed'}")
        return reassigned

    def _roll_offline_events(
        self,
        state: WorldStateView,
        change_set: ChangeSet,
        event_builder: EventBuilder,
        *,
        weeks: float,
        rng,
    ) -> list[str]:
        fired: list[str] = []
        templates = [t for t in self.pack.offline_templates if 3 in (t.get("lod") or [])]
        if not templates:
            return fired
        per_week = float(self.offline_chance.get("lod3", 0.08))
        rolls = min(int(weeks), 52)
        weights = [float(t.get("weight", 1)) for t in templates]
        for _ in range(rolls):
            if not rng.chance(per_week):
                continue
            template = rng.weighted_choice(templates, weights)
            change_set.add_event(
                event_builder.build(
                    "OFFLINE_WORLD_EVENT",
                    payload={
                        "summary": template.get("narrative_hint", ""),
                        "template": template.get("key"),
                        "scope": template.get("scope"),
                    },
                    world_minute=state.world.current_minute,
                    visibility=Visibility.PUBLIC,
                )
            )
            fired.append(str(template.get("key")))
        return fired

    def _recover(self, characters: list[Character], minutes: int) -> list:
        hours = minutes / 60.0
        hp_rate = float(self.pack.rule("combat.health_regen_per_hour", 0.03))
        sp_rate = float(self.pack.rule("combat.spiritual_power_regen_per_hour", 0.08))
        changes = []
        for character in characters:
            if character.health < character.max_health:
                healed = min(
                    character.max_health,
                    character.health + int(character.max_health * hp_rate * hours),
                )
                if healed != character.health:
                    changes.append(
                        mut.character_field(
                            character.id, "health", character.health, healed, reason="offline_recovery"
                        )
                    )
            if character.spiritual_power < character.max_spiritual_power:
                restored = min(
                    character.max_spiritual_power,
                    character.spiritual_power
                    + int(character.max_spiritual_power * sp_rate * hours),
                )
                if restored != character.spiritual_power:
                    changes.append(
                        mut.character_field(
                            character.id,
                            "spiritual_power",
                            character.spiritual_power,
                            restored,
                            reason="offline_recovery",
                        )
                    )
        return changes


def summarise_offline(events: list[Event], limit: int = 3) -> list[str]:
    out: list[str] = []
    for event in events[-limit:]:
        summary = event.payload.get("summary")
        if isinstance(summary, str) and summary:
            out.append(summary)
    return out


def quest_is_open(quest: Quest) -> bool:
    return quest.status in (QuestStatus.OFFERED, QuestStatus.ACTIVE)
