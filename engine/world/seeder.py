"""World seeding: ContentPack -> a fully populated set of domain objects.

Both the SQL layer and the in-memory test fakes consume the same bundle, so
"the world the tests exercise" and "the world the API serves" are the same
world.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core.ids import PLAYER_KEY, deterministic_id
from engine.core.models import (
    Character,
    CharacterKnowledge,
    CharacterSkill,
    Emotion,
    Fact,
    Faction,
    GameSession,
    InventoryItem,
    Item,
    Location,
    Personality,
    PlotThread,
    Quest,
    Relationship,
    Reputation,
    Schedule,
    ScheduleSlot,
    Skill,
    World,
)
from engine.core.types import (
    Activity,
    CharacterType,
    FactScope,
    KnowledgeSource,
    KnowledgeState,
    QuestStatus,
    ThreadStatus,
)
from engine.world.clock import WorldClock


@dataclass(slots=True)
class SeedBundle:
    world: World
    locations: list[Location] = field(default_factory=list)
    factions: list[Faction] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    knowledge: list[CharacterKnowledge] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    inventory: list[InventoryItem] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    character_skills: list[CharacterSkill] = field(default_factory=list)
    quests: list[Quest] = field(default_factory=list)
    plot_threads: list[PlotThread] = field(default_factory=list)
    session: GameSession | None = None

    def character_by_key(self, key: str) -> Character | None:
        return next((c for c in self.characters if c.key == key), None)


@dataclass(slots=True)
class PlayerSpec:
    name: str
    gender: str = "unspecified"
    age: int = 18
    realm: str | None = None
    realm_stage: str | None = None
    spiritual_root: str | None = None
    background: str = ""
    stats: dict[str, int] = field(default_factory=dict)


def _oid(world_id: str, kind: str, key: str) -> str:
    return deterministic_id(f"{world_id}/{kind}", key)


def build_world(
    pack: ContentPack,
    *,
    world_seed: str | None = None,
    world_name: str | None = None,
    player: PlayerSpec | None = None,
    session_seed: str = "session-1",
) -> SeedBundle:
    meta = pack.world_meta
    seed = world_seed or str(meta.get("world_seed_default", "seed"))
    world_id = deterministic_id("world", f"{pack.key}:{seed}")
    clock = WorldClock(pack.calendar)

    world = World(
        id=world_id,
        name=world_name or str(meta.get("name", pack.name)),
        description=str(meta.get("description", "")),
        current_minute=clock.start_minute,
        calendar_config=pack.calendar,
        world_seed=seed,
        content_pack=pack.key,
        narrative_tension=float(pack.rule("narrative.tension_start", 20.0)),
    )
    bundle = SeedBundle(world=world)

    _seed_locations(pack, bundle)
    _seed_factions(pack, bundle)
    _seed_catalog(pack, bundle)
    _seed_characters(pack, bundle)
    if player is not None:
        _seed_player(pack, bundle, player)
    _seed_relationships(pack, bundle)
    _seed_facts(pack, bundle)
    _seed_plot(pack, bundle)

    if player is not None:
        pc = bundle.character_by_key(PLAYER_KEY)
        if pc is not None:
            bundle.session = GameSession(
                id=deterministic_id(f"{world.id}/session", session_seed),
                world_id=world.id,
                player_character_id=pc.id,
                session_seed=session_seed,
            )
    return bundle


# ---------------------------------------------------------------------------
def _seed_locations(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    for raw in pack.locations:
        key = str(raw["key"])
        bundle.locations.append(
            Location(
                id=_oid(world_id, "location", key),
                world_id=world_id,
                parent_id=(
                    _oid(world_id, "location", str(raw["parent"])) if raw.get("parent") else None
                ),
                key=key,
                name=str(raw.get("name", key)),
                location_type=str(raw.get("type", "wilderness")),
                description=str(raw.get("description", "")).strip(),
                danger_level=int(raw.get("danger", 0)),
                spirit_density=float(raw.get("spirit_density", 1.0)),
                faction_key=raw.get("faction"),
                accessible=bool(raw.get("accessible", True)),
                travel_minutes={k: int(v) for k, v in (raw.get("travel") or {}).items()},
                metadata=dict(raw.get("metadata", {}) or {}),
            )
        )


def _seed_factions(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    for raw in pack.factions:
        key = str(raw["key"])
        bundle.factions.append(
            Faction(
                id=_oid(world_id, "faction", key),
                world_id=world_id,
                key=key,
                name=str(raw.get("name", key)),
                description=str(raw.get("description", "")).strip(),
                faction_type=str(raw.get("type", "sect")),
                headquarters_key=raw.get("headquarters"),
                resources={k: float(v) for k, v in (raw.get("resources") or {}).items()},
                member_count=int(raw.get("member_count", 0)),
                territory=list(raw.get("territory", []) or []),
                military_power=float(raw.get("military_power", 0)),
                reputation=float(raw.get("reputation", 0)),
                leader_key=raw.get("leader"),
                alliances=list(raw.get("alliances", []) or []),
                enemies=list(raw.get("enemies", []) or []),
                goals=list(raw.get("goals", []) or []),
                internal_conflicts=list(raw.get("internal_conflicts", []) or []),
                metadata=dict(raw.get("metadata", {}) or {}),
            )
        )


def _seed_catalog(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    for raw in pack.items:
        key = str(raw["key"])
        bundle.items.append(
            Item(
                id=_oid(world_id, "item", key),
                world_id=world_id,
                key=key,
                name=str(raw.get("name", key)),
                item_type=str(raw.get("type", "misc")),
                rarity=str(raw.get("rarity", "common")),
                description=str(raw.get("description", "")).strip(),
                effects=dict(raw.get("effects", {}) or {}),
                value=int(raw.get("value", 0)),
                stackable=bool(raw.get("stackable", True)),
                metadata=dict(raw.get("metadata", {}) or {}),
            )
        )
    for raw in pack.skills:
        key = str(raw["key"])
        bundle.skills.append(
            Skill(
                id=_oid(world_id, "skill", key),
                world_id=world_id,
                key=key,
                name=str(raw.get("name", key)),
                category=str(raw.get("category", "attack")),
                required_realm=str(raw.get("required_realm", "mortal")),
                required_stage=str(
                    raw.get("required_stage", pack.realms.first_stage(str(raw.get("required_realm", "mortal"))).key)
                ),
                spiritual_cost=int(raw.get("spiritual_cost", 0)),
                cooldown_minutes=int(raw.get("cooldown_minutes", 0)),
                power=float(raw.get("power", 0)),
                description=str(raw.get("description", "")).strip(),
                effects=dict(raw.get("effects", {}) or {}),
            )
        )


def _personality_from(raw: dict[str, Any]) -> Personality:
    p = raw.get("personality") or {}
    return Personality(
        traits={k: float(v) for k, v in (p.get("traits") or {}).items()},
        values=list(p.get("values", []) or []),
        taboos=list(p.get("taboos", []) or []),
        speech_style=str(p.get("speech_style", "")),
        risk_tolerance=float(p.get("risk_tolerance", 0.5)),
    )


def _schedule_from(raw: dict[str, Any]) -> Schedule:
    s = raw.get("schedule") or {}
    slots = []
    for entry in s.get("slots", []) or []:
        try:
            activity = Activity(str(entry.get("activity", "work")))
        except ValueError:
            activity = Activity.WORK
        slots.append(
            ScheduleSlot(
                phase=str(entry.get("phase", "morning")),
                activity=activity,
                location_key=entry.get("location"),
            )
        )
    try:
        default = Activity(str(s.get("default", "work")))
    except ValueError:
        default = Activity.WORK
    return Schedule(default=default, slots=slots)


def _seed_characters(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    ladder = pack.realms
    start_minute = bundle.world.current_minute
    for raw in pack.characters:
        key = str(raw["key"])
        realm = str(raw.get("realm", "mortal"))
        stage = str(raw.get("realm_stage", ladder.first_stage(realm).key))
        stats = raw.get("stats") or {}
        max_hp = ladder.max_health(realm, stage)
        max_sp = ladder.max_spiritual_power(realm, stage)
        emotion_raw = raw.get("emotion") or {}
        rep_raw = raw.get("reputation") or {}
        location_key = raw.get("location")

        character = Character(
            id=_oid(world_id, "character", key),
            world_id=world_id,
            key=key,
            name=str(raw.get("name", key)),
            title=raw.get("title"),
            character_type=CharacterType(str(raw.get("type", "BACKGROUND"))),
            age=int(raw.get("age", 20)),
            gender=str(raw.get("gender", "unspecified")),
            location_id=_oid(world_id, "location", str(location_key)) if location_key else None,
            location_key=location_key,
            faction_key=raw.get("faction"),
            faction_rank=raw.get("faction_rank"),
            realm=realm,
            realm_stage=stage,
            cultivation_progress=float(raw.get("cultivation_progress", 0.0)),
            spiritual_root=str(raw.get("spiritual_root", "")),
            mental_state=float(raw.get("mental_state", 0.5)),
            foundation_quality=float(raw.get("foundation_quality", 0.5)),
            health=max_hp,
            max_health=max_hp,
            spiritual_power=max_sp,
            max_spiritual_power=max_sp,
            strength=int(stats.get("strength", 10)),
            agility=int(stats.get("agility", 10)),
            perception=int(stats.get("perception", 10)),
            intelligence=int(stats.get("intelligence", 10)),
            willpower=int(stats.get("willpower", 10)),
            charisma=int(stats.get("charisma", 10)),
            personality=_personality_from(raw),
            background=str(raw.get("background", "")).strip(),
            long_term_goal=str(raw.get("long_term_goal", "")),
            short_term_goals=list(raw.get("short_term_goals", []) or []),
            current_emotion=Emotion(
                dominant=str(emotion_raw.get("dominant", "neutral")),
                valence=float(emotion_raw.get("valence", 0.0)),
                arousal=float(emotion_raw.get("arousal", 0.2)),
                intensity=float(emotion_raw.get("intensity", 0.3)),
                updated_at_minute=start_minute,
            ),
            schedule=_schedule_from(raw),
            reputation=Reputation(
                global_=float(rep_raw.get("global", 0.0)),
                by_faction={k: float(v) for k, v in (rep_raw.get("by_faction") or {}).items()},
            ),
            capabilities=list(raw.get("capabilities", []) or []),
            metadata={"secret": raw.get("secret")} if raw.get("secret") else {},
        )
        bundle.characters.append(character)

        for skill_key in raw.get("skills", []) or []:
            bundle.character_skills.append(
                CharacterSkill(
                    id=_oid(world_id, "cskill", f"{key}:{skill_key}"),
                    character_id=character.id,
                    skill_key=str(skill_key),
                    mastery=0.5 if character.character_type is CharacterType.MAJOR_NPC else 0.3,
                    learned_at_minute=start_minute,
                )
            )
        for entry in raw.get("items", []) or []:
            bundle.inventory.append(
                InventoryItem(
                    id=_oid(world_id, "inv", f"{key}:{entry['key']}"),
                    character_id=character.id,
                    item_key=str(entry["key"]),
                    quantity=int(entry.get("qty", 1)),
                    acquired_at_minute=start_minute,
                )
            )


def _seed_player(pack: ContentPack, bundle: SeedBundle, spec: PlayerSpec) -> None:
    world_id = bundle.world.id
    ladder = pack.realms
    meta = pack.world_meta
    realm = spec.realm or _default_player_realm(pack)
    stage = spec.realm_stage or ladder.first_stage(realm).key
    max_hp = ladder.max_health(realm, stage)
    max_sp = ladder.max_spiritual_power(realm, stage)
    start_location = str(meta.get("start_location", pack.locations[0]["key"]))
    stats = spec.stats or {}

    player = Character(
        id=_oid(world_id, "character", PLAYER_KEY),
        world_id=world_id,
        key=PLAYER_KEY,
        name=spec.name,
        character_type=CharacterType.PLAYER,
        age=spec.age,
        gender=spec.gender,
        location_id=_oid(world_id, "location", start_location),
        location_key=start_location,
        faction_key=_default_player_faction(pack, start_location),
        faction_rank=None,
        realm=realm,
        realm_stage=stage,
        cultivation_progress=0.0,
        spiritual_root=spec.spiritual_root or _default_root(pack),
        mental_state=0.6,
        foundation_quality=0.5,
        health=max_hp,
        max_health=max_hp,
        spiritual_power=max_sp,
        max_spiritual_power=max_sp,
        strength=int(stats.get("strength", 11)),
        agility=int(stats.get("agility", 11)),
        perception=int(stats.get("perception", 11)),
        intelligence=int(stats.get("intelligence", 11)),
        willpower=int(stats.get("willpower", 11)),
        charisma=int(stats.get("charisma", 11)),
        background=spec.background,
        long_term_goal="",
        current_emotion=Emotion(updated_at_minute=bundle.world.current_minute),
    )
    bundle.characters.append(player)

    starter_items = _starter_items(pack)
    for item_key, qty in starter_items:
        bundle.inventory.append(
            InventoryItem(
                id=_oid(world_id, "inv", f"{PLAYER_KEY}:{item_key}"),
                character_id=player.id,
                item_key=item_key,
                quantity=qty,
                acquired_at_minute=bundle.world.current_minute,
            )
        )
    for skill_key in _starter_skills(pack, realm, stage):
        bundle.character_skills.append(
            CharacterSkill(
                id=_oid(world_id, "cskill", f"{PLAYER_KEY}:{skill_key}"),
                character_id=player.id,
                skill_key=skill_key,
                mastery=0.2,
                learned_at_minute=bundle.world.current_minute,
            )
        )


def _default_player_realm(pack: ContentPack) -> str:
    """The lowest tier that has any spiritual power - a fresh initiate."""
    for realm in pack.realms.realms:
        if realm.max_spiritual_power > 0 and realm.playable:
            return realm.key
    return pack.realms.realms[0].key


def _default_player_faction(pack: ContentPack, start_location_key: str) -> str | None:
    loc = pack.location(start_location_key)
    if loc and loc.get("faction"):
        return str(loc["faction"])
    parent_key = loc.get("parent") if loc else None
    while parent_key:
        parent = pack.location(str(parent_key))
        if parent is None:
            break
        if parent.get("faction"):
            return str(parent["faction"])
        parent_key = parent.get("parent")
    return None


def _default_root(pack: ContentPack) -> str:
    roots = pack.realms.spiritual_roots
    if not roots:
        return ""
    mid = sorted(roots, key=lambda r: float(r.get("speed", 1.0)))[len(roots) // 2]
    return str(mid.get("key", ""))


def _starter_items(pack: ContentPack) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    currency = str(pack.rule("economy.currency_key", ""))
    if currency and pack.item(currency):
        out.append((currency, 50))
    for item in pack.items:
        effects = item.get("effects", {}) or {}
        if effects.get("teaches_skill") and item.get("rarity") == "common":
            out.append((str(item["key"]), 1))
            break
    for item in pack.items:
        if item.get("type") == "armor" and item.get("rarity") == "common":
            out.append((str(item["key"]), 1))
            break
    return out


def _starter_skills(pack: ContentPack, realm: str, stage: str) -> list[str]:
    ladder = pack.realms
    for skill in pack.skills:
        if skill.get("category") != "attack":
            continue
        required_realm = str(skill.get("required_realm", "mortal"))
        required_stage = str(skill.get("required_stage", ladder.first_stage(required_realm).key))
        if ladder.meets_requirement(realm, stage, required_realm, required_stage):
            return [str(skill["key"])]
    return []


def _seed_relationships(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    by_key = {c.key: c for c in bundle.characters}
    for raw in pack.seed_relationships:
        a, b = by_key.get(str(raw.get("a"))), by_key.get(str(raw.get("b")))
        if a is None or b is None:
            continue
        bundle.relationships.append(
            Relationship(
                id=_oid(world_id, "rel", f"{a.key}:{b.key}"),
                world_id=world_id,
                character_a_id=a.id,
                character_b_id=b.id,
                affection=int(raw.get("affection", 0)),
                trust=int(raw.get("trust", 0)),
                respect=int(raw.get("respect", 0)),
                fear=int(raw.get("fear", 0)),
                hatred=int(raw.get("hatred", 0)),
                suspicion=int(raw.get("suspicion", 0)),
                dependency=int(raw.get("dependency", 0)),
                familiarity=int(raw.get("familiarity", 0)),
                last_interaction_minute=bundle.world.current_minute,
                interaction_count=1,
            )
        )


def _seed_facts(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    by_key = {c.key: c for c in bundle.characters}
    for raw in pack.facts:
        key = str(raw["key"])
        fact = Fact(
            id=_oid(world_id, "fact", key),
            world_id=world_id,
            key=key,
            statement=str(raw.get("statement", "")),
            truth_value=raw.get("truth_value", True),
            scope=FactScope(str(raw.get("scope", "WORLD"))),
            sensitivity=float(raw.get("sensitivity", 0.0)),
            subject_character_key=raw.get("subject"),
            related_characters=list(raw.get("related", []) or []),
            created_at_minute=bundle.world.current_minute,
        )
        bundle.facts.append(fact)
        for holder_key, spec in (raw.get("initial_knowledge") or {}).items():
            holder = by_key.get(str(holder_key))
            if holder is None:
                continue
            bundle.knowledge.append(
                CharacterKnowledge(
                    id=_oid(world_id, "know", f"{holder_key}:{key}"),
                    character_id=holder.id,
                    fact_id=fact.id,
                    knowledge_state=KnowledgeState(str(spec.get("state", "UNKNOWN"))),
                    confidence=float(spec.get("confidence", 0.0)),
                    source=KnowledgeSource(str(spec.get("source", "SEED"))),
                    learned_at_minute=bundle.world.current_minute,
                )
            )


def _seed_plot(pack: ContentPack, bundle: SeedBundle) -> None:
    world_id = bundle.world.id
    by_key = {c.key: c for c in bundle.characters}
    for raw in pack.plot_threads:
        key = str(raw["key"])
        bundle.plot_threads.append(
            PlotThread(
                id=_oid(world_id, "thread", key),
                world_id=world_id,
                key=key,
                name=str(raw.get("name", key)),
                status=ThreadStatus(str(raw.get("status", "active"))),
                importance=float(raw.get("importance", 0.5)),
                stage=int(raw.get("stage", 0)),
                participants=list(raw.get("participants", []) or []),
                unresolved_questions=list(raw.get("unresolved_questions", []) or []),
                foreshadowing=list(raw.get("foreshadowing", []) or []),
                related_facts=list(raw.get("related_facts", []) or []),
                last_advanced_minute=bundle.world.current_minute,
                next_beat_hint=str(raw.get("next_beat_hint", "")),
                escalation_pressure=float(raw.get("escalation_pressure", 0.1)),
                metadata={"scheduled_beats": raw.get("scheduled_beats", [])},
            )
        )
    for raw in pack.quests:
        key = str(raw["key"])
        giver = by_key.get(str(raw.get("giver"))) if raw.get("giver") else None
        constraints = raw.get("constraints") or {}
        deadline = constraints.get("deadline_minutes")
        bundle.quests.append(
            Quest(
                id=_oid(world_id, "quest", key),
                world_id=world_id,
                key=key,
                name=str(raw.get("name", key)),
                giver_character_key=giver.key if giver else None,
                status=QuestStatus(str(raw.get("status", "offered"))),
                goal=dict(raw.get("goal", {}) or {}),
                constraints=dict(constraints),
                participants=list(raw.get("participants", []) or []),
                rewards=dict(raw.get("rewards", {}) or {}),
                failure_conditions=list(raw.get("failure_conditions", []) or []),
                expires_at_minute=(
                    bundle.world.current_minute + int(deadline) if deadline else None
                ),
                world_consequences=dict(raw.get("world_consequences", {}) or {}),
                plot_thread_key=raw.get("plot_thread"),
            )
        )
