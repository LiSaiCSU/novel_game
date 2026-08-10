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

import math
from dataclasses import dataclass, field
from typing import Any

from engine.characters.goals import GoalLifecycleService
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.errors import EngineError
from engine.core.models import Character, Event, Quest
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import CharacterType, QuestStatus, Visibility
from engine.director.lifecycle import DirectorEventLifecycleService
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.simulation.schedules import ScheduleService
from engine.world.clock import WorldClock
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class SimulationReport:
    strategy: str = "temporal_jump"
    requested_minutes: int = 0
    minutes: int = 0
    ticks: dict[str, int] = field(default_factory=dict)
    processed_windows: int = 0
    offline_events: list[str] = field(default_factory=list)
    aggregate_event_count: int = 0
    moved_characters: int = 0
    aged_characters: int = 0
    natural_deaths: list[str] = field(default_factory=list)
    npc_goal_actions: int = 0
    npc_goal_steps_completed: int = 0
    npc_goal_plans_completed: list[str] = field(default_factory=list)
    director_events_resolved: int = 0
    director_events_cancelled: int = 0
    director_tension_delta: float = 0.0
    director_events_rescheduled: int = 0
    reassigned_quests: list[str] = field(default_factory=list)
    rumours_spread: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "requested_minutes": self.requested_minutes,
            "minutes": self.minutes,
            "ticks": self.ticks,
            "processed_windows": self.processed_windows,
            "offline_events": self.offline_events,
            "aggregate_event_count": self.aggregate_event_count,
            "moved_characters": self.moved_characters,
            "aged_characters": self.aged_characters,
            "natural_deaths": self.natural_deaths,
            "npc_goal_actions": self.npc_goal_actions,
            "npc_goal_steps_completed": self.npc_goal_steps_completed,
            "npc_goal_plans_completed": self.npc_goal_plans_completed,
            "director_events_resolved": self.director_events_resolved,
            "director_events_cancelled": self.director_events_cancelled,
            "director_tension_delta": self.director_tension_delta,
            "director_events_rescheduled": self.director_events_rescheduled,
            "reassigned_quests": self.reassigned_quests,
            "rumours_spread": self.rumours_spread,
        }


class WorldSimulator:
    def __init__(
        self,
        pack: ContentPack,
        schedules: ScheduleService,
        knowledge: KnowledgeService,
        max_offline_minutes: int = 0,
    ) -> None:
        self.pack = pack
        self.schedules = schedules
        self.knowledge = knowledge
        self.goals = GoalLifecycleService(pack)
        self.director_events = DirectorEventLifecycleService(pack)
        self.max_offline_minutes = max_offline_minutes
        self.tick_minutes: dict[str, int] = {
            "lod1": 240,
            "lod2": 1440,
            "lod3": 10080,
            **{k: int(v) for k, v in (pack.rule("simulation.tick_minutes", {}) or {}).items()},
        }
        self.max_materialized_events = int(
            pack.rule("simulation.max_materialized_events_per_jump", 12)
        )
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
        minutes = max(0, int(minutes))
        if self.max_offline_minutes > 0 and minutes > self.max_offline_minutes:
            raise EngineError(
                "temporal jump exceeds configured limit",
                requested_minutes=minutes,
                max_offline_minutes=self.max_offline_minutes,
            )
        report = SimulationReport(requested_minutes=minutes, minutes=minutes)
        if minutes <= 0:
            return report

        clock: WorldClock = state.clock
        target_minute = state.world.current_minute + minutes
        days = minutes / clock.minutes_per_day
        weeks = days / 7.0

        characters = await uow.characters.list_for_world(state.world.id)
        living = [c for c in characters if c.alive]
        age_changes, death_changes, death_ids, death_keys = self._age_and_mortality(
            living,
            state,
            target_minute,
            event_builder,
            change_set,
        )
        change_set.extend(age_changes)
        change_set.extend(death_changes)
        report.aged_characters = len(age_changes)
        report.natural_deaths = death_keys
        alive_at_end = [
            c
            for c in living
            if c.id not in death_ids and c.character_type is not CharacterType.PLAYER
        ]
        death_minutes = {
            event.actor_id: event.world_minute
            for event in change_set.events
            if event.event_type == "DEATH" and event.actor_id in death_ids
        }

        due_director = await self.director_events.process_due(
            uow,
            state,
            target_minute,
            change_set,
            event_builder=event_builder,
        )
        report.director_events_resolved = due_director.resolved
        report.director_events_cancelled = due_director.cancelled
        report.director_tension_delta = due_director.tension_delta
        report.director_events_rescheduled = due_director.rescheduled

        # -- important NPCs pursue durable plans off screen -----------------
        for character in (
            c for c in living if c.character_type is not CharacterType.PLAYER
        ):
            # A coarse jump must preserve the life lived before a mid-jump
            # death. Goal actions are allowed strictly before the canonical
            # death minute, never at or after it.
            goal_target_minute = min(
                target_minute,
                death_minutes.get(character.id, target_minute + 1) - 1,
            )
            if goal_target_minute <= state.world.current_minute:
                continue
            goal_result = self.goals.advance(
                character,
                state.world.current_minute,
                goal_target_minute,
                rng=rng,
                event_builder=event_builder,
                graph=state.graph,
            )
            if goal_result.changed and goal_result.lifecycle is not None:
                change_set.add(
                    mut.character_goals(
                        character.id,
                        {
                            "goal_lifecycle": goal_result.lifecycle.model_dump(mode="json")
                        },
                        reason="temporal_jump_npc_goal",
                    )
                )
            for event in goal_result.events:
                change_set.add_event(event)
            report.npc_goal_actions += goal_result.attempts
            report.npc_goal_steps_completed += goal_result.completed_steps
            if (
                goal_result.lifecycle is not None
                and goal_result.lifecycle.status.value == "REVIEW_REQUIRED"
                and goal_result.completed_steps
            ):
                report.npc_goal_plans_completed.append(character.key)

        # -- LOD 1: everyone follows their day ------------------------------
        report.ticks["lod1"] = max(1, minutes // self.tick_minutes["lod1"])
        end_time = clock.to_world_time(target_minute)
        moves = self.schedules.move_changes(
            alive_at_end, state.graph, end_time, exclude_ids={state.player.id}
        )
        change_set.extend(moves)
        report.processed_windows += 1
        report.moved_characters = len(moves)

        # -- LOD 2: regions drift ------------------------------------------
        if minutes >= self.tick_minutes["lod2"]:
            report.ticks["lod2"] = minutes // self.tick_minutes["lod2"]
            await self._simulate_factions(uow, state, change_set, weeks=weeks, rng=rng)
            report.reassigned_quests = await self._expire_quests(
                uow, state, change_set, target_minute, event_builder, rng
            )
            report.processed_windows += 1

        # -- LOD 3: world-scale beats ---------------------------------------
        if minutes >= self.tick_minutes["lod3"]:
            report.ticks["lod3"] = minutes // self.tick_minutes["lod3"]
            report.offline_events, report.aggregate_event_count = self._roll_offline_events(
                state, change_set, event_builder, weeks=weeks, rng=rng
            )
            report.processed_windows += 1

        # -- information keeps moving too -----------------------------------
        if days >= 1.0:
            spread = await self.knowledge.propagate(
                uow,
                state.world.id,
                days_elapsed=days,
                at_minute=target_minute,
                rng=rng,
                candidates=alive_at_end,
            )
            change_set.extend(spread)
            report.rumours_spread = len(spread)

        # -- passive recovery for everyone off screen ------------------------
        change_set.extend(self._recover(alive_at_end, minutes))
        return report

    def _age_and_mortality(
        self,
        characters: list[Character],
        state: WorldStateView,
        target_minute: int,
        event_builder: EventBuilder,
        change_set: ChangeSet,
    ) -> tuple[list, list, set[str], list[str]]:
        start_year = state.clock.to_world_time(state.world.current_minute).year
        end_year = state.clock.to_world_time(target_minute).year
        years = max(0, end_year - start_year)
        if years <= 0:
            return [], [], set(), []

        age_changes = []
        death_changes = []
        death_ids: set[str] = set()
        death_keys: list[str] = []
        for character in characters:
            new_age = character.age + years
            age_changes.append(
                mut.character_field(
                    character.id,
                    "age",
                    character.age,
                    new_age,
                    reason="temporal_jump_aging",
                )
            )
            lifespan = self.pack.realms.realm(character.realm).lifespan_years
            if new_age < lifespan:
                continue
            years_until_death = max(0, lifespan - character.age)
            death_minute = min(
                target_minute,
                state.world.current_minute + years_until_death * state.clock.minutes_per_year,
            )
            event = event_builder.build(
                "DEATH",
                actor_id=character.id,
                location_id=character.location_id,
                payload={
                    "cause": "natural_lifespan",
                    "character_name": character.display_name,
                    "age": lifespan,
                    "lifespan": lifespan,
                },
                causes=["natural_lifespan"],
                world_minute=death_minute,
                visibility=Visibility.PUBLIC,
            )
            change_set.add_event(event)
            death_changes.append(
                mut.character_death(
                    character.id,
                    reason="natural_lifespan",
                    event_id=event.id,
                )
            )
            death_ids.add(character.id)
            death_keys.append(character.key)
        return age_changes, death_changes, death_ids, death_keys

    # ------------------------------------------------------------------
    async def _simulate_factions(
        self, uow: UnitOfWork, state: WorldStateView, change_set: ChangeSet, *, weeks: float, rng
    ) -> None:
        drift = self.pack.rule("simulation.faction_drift_per_week", {}) or {}
        for faction in await uow.factions.list_for_world(state.world.id):
            for field_name, bounds in drift.items():
                low, high = float(bounds["min"]), float(bounds["max"])
                weekly_mean = (low + high) / 2.0
                weekly_stddev = (high - low) / math.sqrt(12.0)
                aggregate_rng = rng.derive(f"faction:{faction.id}:{field_name}")
                delta = aggregate_rng.normal(
                    weekly_mean * weeks,
                    weekly_stddev * math.sqrt(max(0.0, weeks)),
                )
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
                    if field_name == "military_power":
                        after_value = max(0.0, after_value)
                    elif field_name == "reputation":
                        limits = self.pack.rule("reputation.ranges", {}) or {}
                        after_value = max(
                            float(limits.get("min", -100)),
                            min(float(limits.get("max", 100)), after_value),
                        )
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
    ) -> tuple[list[str], int]:
        fired: list[str] = []
        templates = [t for t in self.pack.offline_templates if 3 in (t.get("lod") or [])]
        if not templates:
            return fired, 0
        per_week = float(self.offline_chance.get("lod3", 0.08))
        whole_weeks = max(0, int(weeks))
        fraction = max(0.0, weeks - whole_weeks)
        event_rng = rng.derive("offline-events")
        total = event_rng.binomial(whole_weeks, per_week)
        if fraction > 0:
            partial_chance = 1.0 - (1.0 - per_week) ** fraction
            total += int(event_rng.chance(partial_chance))
        materialized = min(total, max(0, self.max_materialized_events))
        if materialized <= 0:
            return fired, total

        weights = [float(t.get("weight", 1)) for t in templates]
        base_count, remainder = divmod(total, materialized)
        for index in range(materialized):
            template = event_rng.weighted_choice(templates, weights)
            occurrences = base_count + int(index < remainder)
            event_minute = state.world.current_minute + int(
                ((index + 1) / (materialized + 1)) * weeks * 7 * state.clock.minutes_per_day
            )
            change_set.add_event(
                event_builder.build(
                    "OFFLINE_WORLD_EVENT",
                    payload={
                        "summary": template.get("narrative_hint", ""),
                        "template": template.get("key"),
                        "scope": template.get("scope"),
                        "occurrences": occurrences,
                    },
                    world_minute=event_minute,
                    visibility=Visibility.PUBLIC,
                )
            )
            fired.append(f"{template.get('key')}x{occurrences}")
        return fired, total

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
