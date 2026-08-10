"""WorldSteward - the part of the engine that lets the world grow.

A content pack cannot enumerate every place a player will walk into or every
person they will decide to talk to. The old behaviour was to reject anything
the pack had not written down, which taught the player to stop being creative.

The steward inverts that. When an utterance reaches for something the world
does not have yet, it first tries to recognise what the player meant among
things that *do* exist (a hall called 大殿, a herbalist called 药铺老板), and
only when that fails does it invent the missing piece.

The division of labour is the point:

* the model decides *what* should exist and what the player meant;
* this module decides what is *allowed* to exist, and clamps every field;
* the change lands in the same transaction as the rest of the turn, so from
  the next turn onwards it is ordinary world state - remembered, queryable,
  and exactly as real as anything the pack shipped.

Nothing here decides outcomes. Creating a shopkeeper does not decide whether
the shopkeeper talks to you; the rules and the NPC agent still do that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.ids import new_id
from engine.core.logging import get_logger
from engine.core.models import Character, Emotion, Location, Personality
from engine.core.mutations import StateChange
from engine.core.types import ActionType, CharacterType, LLMRole
from engine.world.state_view import WorldStateView

logger = get_logger("steward")

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: How much the world may grow in one turn. Generous enough that a player is
#: never told "that does not exist", tight enough that one strange utterance
#: cannot spawn a second sect.
MAX_NEW_LOCATIONS_PER_TURN = 2
MAX_NEW_CHARACTERS_PER_TURN = 3


# ---------------------------------------------------------------------------
# What the model is allowed to propose
# ---------------------------------------------------------------------------
class LocationDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    name: str = ""
    location_type: str = "building"
    parent_key: str = ""
    description: str = ""
    danger_level: int = 0
    spirit_density: float = 1.0
    travel_minutes_from_parent: int = 10


class CharacterDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    name: str = ""
    title: str | None = None
    age: int = 30
    gender: str = "unspecified"
    location_key: str = ""
    faction_key: str | None = None
    realm: str = ""
    background: str = ""
    speech_style: str = ""
    traits: dict[str, float] = Field(default_factory=dict)
    short_term_goals: list[str] = Field(default_factory=list)


class StewardPlan(BaseModel):
    """The steward's proposal. Every field is advisory until validated."""

    model_config = ConfigDict(extra="ignore")

    interpretation: str = ""
    action_type: ActionType = ActionType.CUSTOM
    target_key: str | None = None
    location_key: str | None = None
    utterance: str | None = None
    new_locations: list[LocationDraft] = Field(default_factory=list)
    new_characters: list[CharacterDraft] = Field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class StewardResult:
    interpretation: str = ""
    action_type: ActionType | None = None
    target_id: str | None = None
    target_key: str | None = None
    location_key: str | None = None
    utterance: str | None = None
    changes: list[StateChange] = field(default_factory=list)
    new_characters: list[Character] = field(default_factory=list)
    new_locations: list[Location] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    consulted: bool = False
    degraded: bool = False

    @property
    def grew_the_world(self) -> bool:
        return bool(self.new_characters or self.new_locations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "interpretation": self.interpretation,
            "action_type": str(self.action_type) if self.action_type else None,
            "target_key": self.target_key,
            "location_key": self.location_key,
            "new_characters": [c.key for c in self.new_characters],
            "new_locations": [loc.key for loc in self.new_locations],
            "notes": self.notes,
            "consulted": self.consulted,
            "degraded": self.degraded,
        }


class WorldSteward:
    def __init__(
        self,
        pack: ContentPack,
        llm: Any = None,
        registry: Any = None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version
        self.aliases: dict[str, str] = {
            str(k): str(v) for k, v in (pack.vocabulary.get("entity_aliases", {}) or {}).items()
        }

    # ==================================================================
    # Step 1 - recognise before inventing
    # ==================================================================
    def recognise_location(self, state: WorldStateView, phrase: str) -> Location | None:
        """Find an existing location the player plausibly meant."""
        phrase = (phrase or "").strip()
        if not phrase:
            return None
        aliased = self.aliases.get(phrase)
        if aliased:
            hit = state.graph.by_key(aliased)
            if hit is not None:
                return hit

        candidates = state.graph.all()
        exact = [loc for loc in candidates if loc.name == phrase or loc.key == phrase]
        if exact:
            return exact[0]
        # "大殿" inside "青云主殿", or the player naming the full thing loosely.
        contained = [loc for loc in candidates if phrase in loc.name or loc.name in phrase]
        if contained:
            # prefer the nearest one, so 主殿 beats a namesake three regions away
            here = state.location_key()
            neighbours = state.graph.neighbours(here)
            contained.sort(key=lambda loc: (loc.key not in neighbours, len(loc.name)))
            return contained[0]
        return None

    def recognise_character(
        self, state: WorldStateView, phrase: str, world_characters: list[Character]
    ) -> Character | None:
        """Find an existing character the player plausibly meant, present or not."""
        phrase = (phrase or "").strip()
        if not phrase:
            return None
        aliased = self.aliases.get(phrase)
        pool = [c for c in world_characters if c.alive]
        if aliased:
            hit = next((c for c in pool if c.key == aliased), None)
            if hit is not None:
                return hit

        def labels(c: Character) -> list[str]:
            return [x for x in (c.name, c.title, c.key, c.display_name) if x]

        exact = [c for c in pool if phrase in labels(c)]
        if exact:
            return exact[0]
        contained = [c for c in pool if any(phrase in lab or lab in phrase for lab in labels(c))]
        if contained:
            present_ids = {c.id for c in state.present_characters}
            contained.sort(key=lambda c: (c.id not in present_ids, len(c.name)))
            return contained[0]
        return None

    # ==================================================================
    # Step 2 - invent what is genuinely missing
    # ==================================================================
    async def resolve(
        self,
        state: WorldStateView,
        *,
        player_text: str,
        unresolved: list[str],
        world_characters: list[Character],
        recent_narrative: str = "",
    ) -> StewardResult:
        result = StewardResult(notes=list(unresolved))
        if not (self.llm and self.registry and self.llm.usable_for(LLMRole.STEWARD)):
            result.degraded = True
            return result

        try:
            prompt = self.registry.render(
                "world_steward",
                self.prompt_version,
                schema=self.llm.schema_hint(StewardPlan),
                action_types=", ".join(str(a) for a in ActionType),
                player_input=player_text,
                unresolved="\n".join(f"- {n}" for n in unresolved) or "-",
                location=state.location.name if state.location else "-",
                location_key=state.location_key(),
                time_label=state.time.label,
                present_characters=self._present_block(state),
                world_locations=self._location_index(state),
                world_characters=self._character_index(state, world_characters),
                location_types=", ".join(
                    str(t.get("key", "")) for t in self.pack.location_types
                )
                or "building",
                realm_keys=", ".join(r.key for r in self.pack.realms.realms),
                faction_keys=", ".join(sorted(state.factions)) or "-",
                recent_narrative=recent_narrative[-600:] or "-",
            )
            plan = await self.llm.generate_structured(
                LLMRole.STEWARD, StewardPlan, prompt, prompt_version=self.prompt_version
            )
        except (LLMError, StructuredOutputError) as exc:
            logger.warning("steward unavailable, world stays as written: %s", exc)
            self.llm.record_degraded(LLMRole.STEWARD, str(exc))
            result.degraded = True
            return result

        result.consulted = True
        result.interpretation = plan.interpretation.strip()
        result.action_type = plan.action_type
        result.utterance = plan.utterance
        self._apply_plan(state, plan, world_characters, result)
        return result

    # ------------------------------------------------------------------
    def _apply_plan(
        self,
        state: WorldStateView,
        plan: StewardPlan,
        world_characters: list[Character],
        result: StewardResult,
    ) -> None:
        """Turn a proposal into world changes, clamping everything on the way."""
        taken_location_keys = {loc.key for loc in state.graph.all()}
        taken_character_keys = {c.key for c in world_characters} | {state.player.key}

        for location_draft in plan.new_locations[:MAX_NEW_LOCATIONS_PER_TURN]:
            location = self._build_location(
                state, location_draft, taken_location_keys, result.notes
            )
            if location is None:
                continue
            taken_location_keys.add(location.key)
            result.new_locations.append(location)
            result.changes.append(
                mut.location_spawn(location, reason=f"steward:{plan.interpretation[:60]}")
            )

        for character_draft in plan.new_characters[:MAX_NEW_CHARACTERS_PER_TURN]:
            character = self._build_character(
                state,
                character_draft,
                taken_character_keys,
                result.new_locations,
                result.notes,
            )
            if character is None:
                continue
            taken_character_keys.add(character.key)
            result.new_characters.append(character)
            result.changes.append(
                mut.character_spawn(character, reason=f"steward:{plan.interpretation[:60]}")
            )

        # Bind the plan's references, now that anything it created exists.
        if plan.location_key:
            existing = state.graph.by_key(plan.location_key)
            spawned_location = next(
                (loc for loc in result.new_locations if loc.key == plan.location_key), None
            )
            if existing is not None or spawned_location is not None:
                result.location_key = plan.location_key
            else:
                result.notes.append(f"steward_location_unknown:{plan.location_key}")

        if plan.target_key:
            spawned_character = next(
                (c for c in result.new_characters if c.key == plan.target_key), None
            )
            if spawned_character is not None:
                result.target_key = spawned_character.key
                result.target_id = spawned_character.id
            else:
                match = next(
                    (c for c in world_characters if c.key == plan.target_key and c.alive), None
                )
                if match is not None:
                    result.target_key = match.key
                    result.target_id = match.id
                    # Naming someone who is elsewhere is a travel plan. Record
                    # where they are so the caller can route there.
                    if not state.is_present(match.id) and not result.location_key:
                        result.location_key = match.location_key
                else:
                    result.notes.append(f"steward_target_unknown:{plan.target_key}")

    # ------------------------------------------------------------------
    def _build_location(
        self,
        state: WorldStateView,
        draft: LocationDraft,
        taken: set[str],
        notes: list[str],
    ) -> Location | None:
        key = _clean_key(draft.key)
        name = draft.name.strip()
        if not key or not name:
            notes.append("steward_location_missing_key_or_name")
            return None
        if key in taken:
            notes.append(f"steward_location_key_taken:{key}")
            return None

        parent = state.graph.by_key(draft.parent_key) or state.location
        if parent is None:
            notes.append(f"steward_location_parent_unknown:{draft.parent_key}")
            return None

        types = {str(t.get("key", "")) for t in self.pack.location_types} or {"building"}
        location_type = draft.location_type if draft.location_type in types else "building"

        # A newly imagined corner of the world may not be more dangerous than
        # its surroundings by more than one step, and may not out-shine them.
        danger = _clamp_int(draft.danger_level, 0, max(0, parent.danger_level) + 1)
        density = _clamp_float(draft.spirit_density, 0.1, max(0.2, parent.spirit_density * 1.2))
        travel = _clamp_int(draft.travel_minutes_from_parent, 1, 240)

        return Location(
            id=new_id(),
            world_id=state.world.id,
            parent_id=parent.id,
            key=key,
            name=name,
            location_type=location_type,
            description=draft.description.strip()[:400],
            danger_level=danger,
            spirit_density=density,
            faction_key=parent.faction_key,
            accessible=True,
            travel_minutes={parent.key: travel},
            metadata={"origin": "steward"},
        )

    def _build_character(
        self,
        state: WorldStateView,
        draft: CharacterDraft,
        taken: set[str],
        spawned_locations: list[Location],
        notes: list[str],
    ) -> Character | None:
        key = _clean_key(draft.key)
        name = draft.name.strip()
        if not key or not name:
            notes.append("steward_character_missing_key_or_name")
            return None
        if key in taken:
            notes.append(f"steward_character_key_taken:{key}")
            return None

        location = state.graph.by_key(draft.location_key)
        location_id = location.id if location else None
        location_key = location.key if location else None
        if location is None:
            spawned = next(
                (loc for loc in spawned_locations if loc.key == draft.location_key), None
            )
            if spawned is not None:
                location_id, location_key = spawned.id, spawned.key
        if location_id is None:
            # Default to standing in front of the player rather than nowhere.
            location_id = state.player.location_id
            location_key = state.player.location_key

        ladder = self.pack.realms
        realm = draft.realm if ladder.has_realm(draft.realm) else state.player.realm
        # An improvised extra never outranks the player by more than one tier.
        if ladder.order(realm) > ladder.order(state.player.realm) + 1:
            realm = state.player.realm
            notes.append(f"steward_character_realm_capped:{key}")
        stage = ladder.first_stage(realm).key
        max_hp = ladder.max_health(realm, stage)
        max_sp = ladder.max_spiritual_power(realm, stage)

        faction_key = draft.faction_key if draft.faction_key in state.factions else None

        return Character(
            id=new_id(),
            world_id=state.world.id,
            key=key,
            name=name,
            title=(draft.title or None),
            # Improvised people are supporting cast. Only the pack and the
            # director may introduce someone who matters to the whole world.
            character_type=CharacterType.MINOR_NPC,
            age=_clamp_int(draft.age, 6, 400),
            gender=draft.gender or "unspecified",
            location_id=location_id,
            location_key=location_key,
            faction_key=faction_key,
            realm=realm,
            realm_stage=stage,
            health=max_hp,
            max_health=max_hp,
            spiritual_power=max_sp,
            max_spiritual_power=max_sp,
            personality=Personality(
                traits={
                    str(k): _clamp_float(v, 0.0, 1.0)
                    for k, v in list(draft.traits.items())[:8]
                },
                speech_style=draft.speech_style.strip()[:120],
            ),
            background=draft.background.strip()[:400],
            short_term_goals=[g.strip()[:80] for g in draft.short_term_goals[:3] if g.strip()],
            current_emotion=Emotion(updated_at_minute=state.world.current_minute),
            metadata={"origin": "steward"},
        )

    # ==================================================================
    # Context blocks
    # ==================================================================
    def _present_block(self, state: WorldStateView) -> str:
        rows = [
            f"- {c.display_name}[{c.key}] {self.pack.realms.display(c.realm, c.realm_stage)}"
            for c in state.present_characters
            if c.alive
        ]
        return "\n".join(rows) or "-"

    def _location_index(self, state: WorldStateView) -> str:
        here = state.location_key()
        neighbours = state.graph.neighbours(here)
        rows = []
        for loc in state.graph.all():
            mark = ""
            if loc.key == here:
                mark = " (HERE)"
            elif loc.key in neighbours:
                mark = f" ({neighbours[loc.key]}min)"
            rows.append(f"- {loc.name}[{loc.key}]{mark}")
        return "\n".join(rows) or "-"

    def _character_index(
        self, state: WorldStateView, world_characters: list[Character]
    ) -> str:
        present_ids = {c.id for c in state.present_characters}
        rows = []
        for c in world_characters:
            if not c.alive or c.id == state.player.id:
                continue
            where = c.location_key or "?"
            mark = " (HERE)" if c.id in present_ids else f" (at {where})"
            rows.append(f"- {c.display_name}[{c.key}]{mark}")
        return "\n".join(rows) or "-"


# ---------------------------------------------------------------------------
def _clean_key(raw: str) -> str:
    key = (raw or "").strip().lower()
    key = re.sub(r"[^a-z0-9_]", "_", key).strip("_")
    key = re.sub(r"_+", "_", key)[:40]
    return key if key and _KEY_RE.match(key) else ""


def _clamp_int(value: Any, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return low


def _clamp_float(value: Any, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low
