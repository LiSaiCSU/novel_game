"""In-memory UnitOfWork adapter.

A complete, transactional implementation of the engine's repository ports that
keeps everything in dictionaries. It is the default backend for tests and for
`scripts/play_cli.py`, and it makes the whole turn pipeline runnable with zero
external services.

Transactional semantics: mutations go through :meth:`apply`, which snapshots
state first and restores it on rollback.
"""

from __future__ import annotations

import copy
from typing import Any

from engine.core.errors import EngineError
from engine.core.models import (
    Character,
    CharacterKnowledge,
    CharacterSkill,
    Emotion,
    Event,
    Fact,
    Faction,
    GameSession,
    InventoryItem,
    Item,
    Location,
    Memory,
    NarrativeSegment,
    PlotThread,
    Quest,
    Relationship,
    RelationshipChange,
    Skill,
    World,
)
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import KnowledgeSource, KnowledgeState
from engine.world.seeder import SeedBundle


class MemoryStore:
    """The shared data plane. One instance == one database."""

    def __init__(self) -> None:
        self.worlds: dict[str, World] = {}
        self.locations: dict[str, Location] = {}
        self.factions: dict[str, Faction] = {}
        self.characters: dict[str, Character] = {}
        self.relationships: dict[tuple[str, str], Relationship] = {}
        self.relationship_changes: list[RelationshipChange] = []
        self.facts: dict[str, Fact] = {}
        self.knowledge: dict[tuple[str, str], CharacterKnowledge] = {}
        self.memories: dict[str, Memory] = {}
        self.items: dict[str, Item] = {}
        self.inventory: dict[tuple[str, str], InventoryItem] = {}
        self.skills: dict[str, Skill] = {}
        self.character_skills: dict[tuple[str, str], CharacterSkill] = {}
        self.quests: dict[str, Quest] = {}
        self.events: list[Event] = []
        self.plot_threads: dict[str, PlotThread] = {}
        self.sessions: dict[str, GameSession] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.turn_traces: dict[str, dict[str, Any]] = {}
        self.narrative: list[NarrativeSegment] = []

    # -- seeding ------------------------------------------------------------
    def load(self, bundle: SeedBundle) -> None:
        self.worlds[bundle.world.id] = bundle.world
        for loc in bundle.locations:
            self.locations[loc.id] = loc
        for fac in bundle.factions:
            self.factions[fac.id] = fac
        for ch in bundle.characters:
            self.characters[ch.id] = ch
        for rel in bundle.relationships:
            self.relationships[(rel.character_a_id, rel.character_b_id)] = rel
        for fact in bundle.facts:
            self.facts[fact.id] = fact
        for k in bundle.knowledge:
            self.knowledge[(k.character_id, k.fact_id)] = k
        for item in bundle.items:
            self.items[item.id] = item
        for inv in bundle.inventory:
            self.inventory[(inv.character_id, inv.item_key)] = inv
        for skill in bundle.skills:
            self.skills[skill.id] = skill
        for cs in bundle.character_skills:
            self.character_skills[(cs.character_id, cs.skill_key)] = cs
        for quest in bundle.quests:
            self.quests[quest.id] = quest
        for thread in bundle.plot_threads:
            self.plot_threads[thread.id] = thread
        if bundle.session is not None:
            self.sessions[bundle.session.id] = bundle.session

    def snapshot(self) -> dict[str, Any]:
        return {
            name: copy.deepcopy(getattr(self, name))
            for name in (
                "worlds", "locations", "factions", "characters", "relationships",
                "relationship_changes", "facts", "knowledge", "memories", "items",
                "inventory", "skills", "character_skills", "quests", "events",
                "plot_threads", "sessions", "turns", "turn_traces", "narrative",
            )
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        for name, value in snapshot.items():
            setattr(self, name, value)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------
def _detach(entity):
    """Hand out a copy, the way a real session hands out refreshed rows.

    Without this the engine could mutate stored state by accident and a
    before/after diff of the "same" object would silently be empty.
    """
    return entity.model_copy(deep=True) if entity is not None else None


def _detach_all(entities):
    return [e.model_copy(deep=True) for e in entities]


class _WorldRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, world_id: str) -> World | None:
        return _detach(self.s.worlds.get(world_id))

    async def save(self, world: World) -> None:
        self.s.worlds[world.id] = world.model_copy(deep=True)

    async def list_all(self) -> list[World]:
        return _detach_all(self.s.worlds.values())


class _LocationRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, location_id: str) -> Location | None:
        return self.s.locations.get(location_id)

    async def get_by_key(self, world_id: str, key: str) -> Location | None:
        return next(
            (loc for loc in self.s.locations.values() if loc.world_id == world_id and loc.key == key),
            None,
        )

    async def list_for_world(self, world_id: str) -> list[Location]:
        return [loc for loc in self.s.locations.values() if loc.world_id == world_id]

    async def children(self, location_id: str) -> list[Location]:
        return [loc for loc in self.s.locations.values() if loc.parent_id == location_id]


class _FactionRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, faction_id: str) -> Faction | None:
        return self.s.factions.get(faction_id)

    async def get_by_key(self, world_id: str, key: str) -> Faction | None:
        return next(
            (f for f in self.s.factions.values() if f.world_id == world_id and f.key == key), None
        )

    async def list_for_world(self, world_id: str) -> list[Faction]:
        return [f for f in self.s.factions.values() if f.world_id == world_id]


class _CharacterRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, character_id: str) -> Character | None:
        return _detach(self.s.characters.get(character_id))

    async def get_by_key(self, world_id: str, key: str) -> Character | None:
        return _detach(
            next(
                (c for c in self.s.characters.values() if c.world_id == world_id and c.key == key),
                None,
            )
        )

    async def list_for_world(self, world_id: str, *, alive_only: bool = True) -> list[Character]:
        return _detach_all(
            c
            for c in self.s.characters.values()
            if c.world_id == world_id and (c.alive or not alive_only)
        )

    async def list_at_location(
        self, world_id: str, location_id: str, *, alive_only: bool = True
    ) -> list[Character]:
        return _detach_all(
            c
            for c in self.s.characters.values()
            if c.world_id == world_id and c.location_id == location_id and (c.alive or not alive_only)
        )

    async def list_by_type(self, world_id: str, character_type: str) -> list[Character]:
        return _detach_all(
            c
            for c in self.s.characters.values()
            if c.world_id == world_id and str(c.character_type) == character_type
        )


class _RelationshipRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, character_a_id: str, character_b_id: str) -> Relationship | None:
        return self.s.relationships.get((character_a_id, character_b_id))

    async def list_for_character(self, character_id: str) -> list[Relationship]:
        return [r for (a, _b), r in self.s.relationships.items() if a == character_id]

    async def list_changes(self, character_id: str, limit: int = 50) -> list[RelationshipChange]:
        rows = [
            c
            for c in self.s.relationship_changes
            if character_id in (c.character_a_id, c.character_b_id)
        ]
        return rows[-limit:]


class _KnowledgeRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get_fact(self, fact_id: str) -> Fact | None:
        return self.s.facts.get(fact_id)

    async def get_fact_by_key(self, world_id: str, key: str) -> Fact | None:
        return next(
            (f for f in self.s.facts.values() if f.world_id == world_id and f.key == key), None
        )

    async def list_facts(self, world_id: str) -> list[Fact]:
        return [f for f in self.s.facts.values() if f.world_id == world_id]

    async def get_knowledge(self, character_id: str, fact_id: str) -> CharacterKnowledge | None:
        return self.s.knowledge.get((character_id, fact_id))

    async def list_known(self, character_id: str) -> list[tuple[CharacterKnowledge, Fact]]:
        out: list[tuple[CharacterKnowledge, Fact]] = []
        for (char_id, fact_id), row in self.s.knowledge.items():
            if char_id != character_id:
                continue
            if row.knowledge_state is KnowledgeState.UNKNOWN:
                continue
            fact = self.s.facts.get(fact_id)
            if fact is not None:
                out.append((row, fact))
        return out

    async def list_knowers(self, fact_id: str) -> list[CharacterKnowledge]:
        return [
            row
            for (_c, f), row in self.s.knowledge.items()
            if f == fact_id and row.knowledge_state is not KnowledgeState.UNKNOWN
        ]


class _MemoryRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def list_for_owner(
        self, owner_character_id: str, *, memory_types: list[str] | None = None, limit: int = 200
    ) -> list[Memory]:
        rows = [m for m in self.s.memories.values() if m.owner_character_id == owner_character_id]
        if memory_types:
            wanted = set(memory_types)
            rows = [m for m in rows if str(m.memory_type) in wanted]
        rows.sort(key=lambda m: m.created_at_minute, reverse=True)
        return rows[:limit]

    async def add(self, memory: Memory) -> None:
        self.s.memories[memory.id] = memory

    async def touch(self, memory_id: str, at_minute: int) -> None:
        row = self.s.memories.get(memory_id)
        if row is not None:
            row.last_recalled_minute = at_minute
            row.recall_count += 1


class _ItemRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get_by_key(self, world_id: str, key: str) -> Item | None:
        return next(
            (i for i in self.s.items.values() if i.world_id == world_id and i.key == key), None
        )

    async def list_for_world(self, world_id: str) -> list[Item]:
        return [i for i in self.s.items.values() if i.world_id == world_id]

    async def list_inventory(self, character_id: str) -> list[InventoryItem]:
        return [row for (c, _k), row in self.s.inventory.items() if c == character_id]

    async def get_inventory_item(self, character_id: str, item_key: str) -> InventoryItem | None:
        return self.s.inventory.get((character_id, item_key))


class _SkillRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get_by_key(self, world_id: str, key: str) -> Skill | None:
        return next(
            (s for s in self.s.skills.values() if s.world_id == world_id and s.key == key), None
        )

    async def list_for_world(self, world_id: str) -> list[Skill]:
        return [s for s in self.s.skills.values() if s.world_id == world_id]

    async def list_for_character(self, character_id: str) -> list[CharacterSkill]:
        return [row for (c, _k), row in self.s.character_skills.items() if c == character_id]

    async def get_for_character(self, character_id: str, skill_key: str) -> CharacterSkill | None:
        return self.s.character_skills.get((character_id, skill_key))


class _QuestRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, quest_id: str) -> Quest | None:
        return self.s.quests.get(quest_id)

    async def get_by_key(self, world_id: str, key: str) -> Quest | None:
        return next(
            (q for q in self.s.quests.values() if q.world_id == world_id and q.key == key), None
        )

    async def list_for_world(self, world_id: str, *, status: str | None = None) -> list[Quest]:
        rows = [q for q in self.s.quests.values() if q.world_id == world_id]
        if status:
            rows = [q for q in rows if str(q.status) == status]
        return rows


class _EventRepo:
    """Append-only by construction: there is no way to mutate a stored event."""

    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def append(self, event: Event) -> None:
        self.s.events.append(event.model_copy(deep=True))

    async def list_recent(self, world_id: str, limit: int = 20) -> list[Event]:
        rows = [e for e in self.s.events if e.world_id == world_id]
        return rows[-limit:]

    async def list_for_actor(self, actor_id: str, limit: int = 20) -> list[Event]:
        rows = [e for e in self.s.events if e.actor_id == actor_id or actor_id in e.target_ids]
        return rows[-limit:]

    async def list_since(self, world_id: str, since_minute: int) -> list[Event]:
        return [e for e in self.s.events if e.world_id == world_id and e.world_minute >= since_minute]

    async def get(self, event_id: str) -> Event | None:
        return next((e for e in self.s.events if e.id == event_id), None)


class _PlotThreadRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get_by_key(self, world_id: str, key: str) -> PlotThread | None:
        return next(
            (t for t in self.s.plot_threads.values() if t.world_id == world_id and t.key == key),
            None,
        )

    async def list_for_world(self, world_id: str, *, status: str | None = None) -> list[PlotThread]:
        rows = [t for t in self.s.plot_threads.values() if t.world_id == world_id]
        if status:
            rows = [t for t in rows if str(t.status) == status]
        return rows


class _SessionRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def get(self, session_id: str) -> GameSession | None:
        return self.s.sessions.get(session_id)

    async def save(self, session: GameSession) -> None:
        self.s.sessions[session.id] = session

    async def list_for_world(self, world_id: str) -> list[GameSession]:
        return [s for s in self.s.sessions.values() if s.world_id == world_id]


class _TurnRepo:
    def __init__(self, store: MemoryStore) -> None:
        self.s = store

    async def record(self, turn: dict[str, Any]) -> None:
        self.s.turns[str(turn["id"])] = copy.deepcopy(turn)

    async def get(self, turn_id: str) -> dict[str, Any] | None:
        return self.s.turns.get(turn_id)

    async def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        return next(
            (t for t in self.s.turns.values() if t.get("idempotency_key") == key), None
        )

    async def list_for_session(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = [t for t in self.s.turns.values() if t.get("session_id") == session_id]
        rows.sort(key=lambda t: t.get("turn_number", 0))
        return rows[-limit:]

    async def append_narrative(self, segment: NarrativeSegment) -> None:
        self.s.narrative.append(segment)

    async def list_narrative(self, session_id: str, limit: int = 10) -> list[NarrativeSegment]:
        rows = [n for n in self.s.narrative if n.session_id == session_id]
        return rows[-limit:]

    async def save_trace(self, trace: dict[str, Any]) -> None:
        self.s.turn_traces[str(trace["turn_id"])] = copy.deepcopy(trace)

    async def get_trace(self, turn_id: str) -> dict[str, Any] | None:
        return self.s.turn_traces.get(turn_id)


# ---------------------------------------------------------------------------
class MemoryUnitOfWork:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.worlds = _WorldRepo(store)
        self.locations = _LocationRepo(store)
        self.factions = _FactionRepo(store)
        self.characters = _CharacterRepo(store)
        self.relationships = _RelationshipRepo(store)
        self.knowledge = _KnowledgeRepo(store)
        self.memories = _MemoryRepo(store)
        self.items = _ItemRepo(store)
        self.skills = _SkillRepo(store)
        self.quests = _QuestRepo(store)
        self.events = _EventRepo(store)
        self.plot_threads = _PlotThreadRepo(store)
        self.sessions = _SessionRepo(store)
        self.turns = _TurnRepo(store)
        self._snapshot: dict[str, Any] | None = None

    async def __aenter__(self) -> MemoryUnitOfWork:
        self._snapshot = self.store.snapshot()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            await self.rollback()
        self._snapshot = None

    async def commit(self) -> None:
        self._snapshot = self.store.snapshot()

    async def rollback(self) -> None:
        if self._snapshot is not None:
            self.store.restore(self._snapshot)

    # -- the write path -----------------------------------------------------
    async def apply(self, change_set: ChangeSet) -> None:
        for change in change_set.changes:
            self._apply_one(change)
        for event in change_set.events:
            self.store.events.append(event.model_copy(deep=True))
        for rc in change_set.relationship_changes:
            self.store.relationship_changes.append(rc)
        for memory in change_set.memories:
            self.store.memories[memory.id] = memory

    def _apply_one(self, change) -> None:
        s = self.store
        kind = change.kind
        if kind is ChangeKind.CHARACTER_FIELD:
            character = s.characters.get(change.target_id)
            if character is None:
                raise EngineError(f"unknown character {change.target_id}")
            setattr(character, change.field, change.after)
        elif kind is ChangeKind.CHARACTER_LOCATION:
            character = s.characters[change.target_id]
            character.location_id = change.after
            loc = s.locations.get(str(change.after))
            character.location_key = loc.key if loc else None
        elif kind is ChangeKind.CHARACTER_DEATH:
            character = s.characters[change.target_id]
            character.alive = False
            character.health = 0
            character.death_event_id = change.payload.get("death_event_id")
        elif kind is ChangeKind.CHARACTER_EMOTION:
            character = s.characters[change.target_id]
            payload = {k: v for k, v in change.payload.items() if k in Emotion.model_fields}
            character.current_emotion = character.current_emotion.model_copy(update=payload)
        elif kind is ChangeKind.CHARACTER_GOALS:
            character = s.characters[change.target_id]
            if "short_term_goals" in change.payload:
                character.short_term_goals = list(change.payload["short_term_goals"])
            if "long_term_goal" in change.payload:
                character.long_term_goal = str(change.payload["long_term_goal"])
        elif kind is ChangeKind.RELATIONSHIP_DELTA:
            self._apply_relationship(change)
        elif kind is ChangeKind.INVENTORY_ADD:
            self._inventory_add(change)
        elif kind is ChangeKind.INVENTORY_REMOVE:
            self._inventory_remove(change)
        elif kind is ChangeKind.SKILL_LEARN:
            key = (change.target_id, str(change.payload["skill_key"]))
            if key not in s.character_skills:
                s.character_skills[key] = CharacterSkill(
                    character_id=change.target_id, skill_key=key[1], mastery=0.1
                )
        elif kind is ChangeKind.SKILL_USED:
            row = s.character_skills.get((change.target_id, str(change.payload["skill_key"])))
            if row is not None:
                row.last_used_minute = int(change.payload.get("at_minute", 0))
                row.mastery = min(1.0, row.mastery + 0.005)
        elif kind is ChangeKind.KNOWLEDGE_SET:
            self._knowledge_set(change)
        elif kind is ChangeKind.MEMORY_ADD:
            pass  # memories arrive via ChangeSet.memories
        elif kind is ChangeKind.QUEST_STATUS:
            quest = s.quests.get(change.target_id)
            if quest is not None:
                quest.status = change.after
        elif kind is ChangeKind.FACTION_FIELD:
            faction = s.factions.get(change.target_id)
            if faction is not None:
                setattr(faction, change.field, change.after)
        elif kind is ChangeKind.PLOT_THREAD_UPDATE:
            thread = s.plot_threads.get(change.target_id)
            if thread is not None:
                for field_name, value in change.payload.items():
                    if hasattr(thread, field_name):
                        setattr(thread, field_name, value)
        elif kind is ChangeKind.WORLD_TIME:
            world = s.worlds[change.target_id]
            world.current_minute = int(change.after)
        elif kind is ChangeKind.WORLD_TENSION:
            world = s.worlds[change.target_id]
            world.tension_history = [*world.tension_history, world.narrative_tension][-20:]
            world.narrative_tension = float(change.after)
        elif kind is ChangeKind.LOCATION_FLAG:
            loc = s.locations.get(change.target_id)
            if loc is not None:
                loc.metadata.update(change.payload)

    def _apply_relationship(self, change) -> None:
        s = self.store
        a_id = change.target_id
        b_id = str(change.payload["other_id"])
        rel = s.relationships.get((a_id, b_id))
        if rel is None:
            actor = s.characters.get(a_id)
            rel = Relationship(
                world_id=actor.world_id if actor else "",
                character_a_id=a_id,
                character_b_id=b_id,
            )
            s.relationships[(a_id, b_id)] = rel
        for dim, delta in (change.payload.get("deltas") or {}).items():
            if not hasattr(rel, dim):
                continue
            setattr(rel, dim, int(getattr(rel, dim)) + int(delta))
        rel.interaction_count += 1

    def _inventory_add(self, change) -> None:
        s = self.store
        key = (change.target_id, str(change.payload["item_key"]))
        quantity = int(change.payload.get("quantity", 1))
        row = s.inventory.get(key)
        if row is None:
            s.inventory[key] = InventoryItem(
                character_id=key[0], item_key=key[1], quantity=quantity
            )
        else:
            row.quantity += quantity

    def _inventory_remove(self, change) -> None:
        s = self.store
        key = (change.target_id, str(change.payload["item_key"]))
        quantity = int(change.payload.get("quantity", 1))
        row = s.inventory.get(key)
        if row is None:
            raise EngineError(f"cannot remove {key[1]}: not owned", character_id=key[0])
        if row.quantity < quantity:
            raise EngineError(
                f"cannot remove {quantity} of {key[1]}: only {row.quantity} owned",
                character_id=key[0],
            )
        row.quantity -= quantity
        if row.quantity <= 0:
            s.inventory.pop(key, None)

    def _knowledge_set(self, change) -> None:
        s = self.store
        fact_id = str(change.payload["fact_id"])
        key = (change.target_id, fact_id)
        row = s.knowledge.get(key)
        state = KnowledgeState(str(change.payload["knowledge_state"]))
        confidence = float(change.payload.get("confidence", 0.5))
        source = KnowledgeSource(str(change.payload.get("source", "INFERRED")))
        if row is None:
            s.knowledge[key] = CharacterKnowledge(
                character_id=key[0],
                fact_id=fact_id,
                knowledge_state=state,
                confidence=confidence,
                source=source,
                source_character_id=change.payload.get("source_character_id"),
                learned_at_minute=int(change.payload.get("learned_at_minute", 0)),
            )
        else:
            row.knowledge_state = state
            row.confidence = confidence
            row.source = source
            row.learned_at_minute = int(change.payload.get("learned_at_minute", row.learned_at_minute))
