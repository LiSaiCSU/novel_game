"""Engine-level enumerations.

These are *structural* vocabulary only. No content-pack specific values live
here: realms, factions, locations and item keys are all plain strings resolved
against the loaded ContentPack.
"""

from __future__ import annotations

from enum import StrEnum


class ActionType(StrEnum):
    """The only behaviours the world recognises (Prompt section 7)."""

    MOVE = "MOVE"
    TALK = "TALK"
    ASK = "ASK"
    CONVERSATION = "CONVERSATION"
    OBSERVE = "OBSERVE"
    FOLLOW = "FOLLOW"
    HIDE = "HIDE"
    SEARCH = "SEARCH"
    ATTACK = "ATTACK"
    DEFEND = "DEFEND"
    USE_ITEM = "USE_ITEM"
    GIVE_ITEM = "GIVE_ITEM"
    STEAL = "STEAL"
    BUY = "BUY"
    SELL = "SELL"
    CULTIVATE = "CULTIVATE"
    BREAKTHROUGH = "BREAKTHROUGH"
    USE_SKILL = "USE_SKILL"
    PICKUP = "PICKUP"
    DROP = "DROP"
    REST = "REST"
    WAIT = "WAIT"
    ACCEPT_QUEST = "ACCEPT_QUEST"
    REJECT_QUEST = "REJECT_QUEST"
    CUSTOM = "CUSTOM"
    # Query-only actions: resolved straight from the repositories, never an LLM.
    QUERY_STATUS = "QUERY_STATUS"
    QUERY_INVENTORY = "QUERY_INVENTORY"
    QUERY_RELATIONSHIPS = "QUERY_RELATIONSHIPS"
    QUERY_QUESTS = "QUERY_QUESTS"


QUERY_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.QUERY_STATUS,
        ActionType.QUERY_INVENTORY,
        ActionType.QUERY_RELATIONSHIPS,
        ActionType.QUERY_QUESTS,
    }
)

SOCIAL_ACTIONS: frozenset[ActionType] = frozenset(
    {ActionType.TALK, ActionType.ASK, ActionType.CONVERSATION, ActionType.GIVE_ITEM}
)


class SocialMethod(StrEnum):
    """How a social action is attempted (Prompt section 38)."""

    DIRECT_QUESTION = "direct_question"
    INDIRECT_QUESTIONING = "indirect_questioning"
    PERSUADE = "persuade"
    DECEIVE = "deceive"
    INTIMIDATE = "intimidate"
    FLIRT = "flirt"
    NEGOTIATE = "negotiate"
    BRIBE = "bribe"
    THREATEN = "threaten"
    COMFORT = "comfort"
    PROMISE = "promise"
    SMALL_TALK = "small_talk"


class RequestSize(StrEnum):
    TRIVIAL = "trivial"
    SMALL = "small"
    MODERATE = "moderate"
    LARGE = "large"
    EXTREME = "extreme"


class CharacterType(StrEnum):
    PLAYER = "PLAYER"
    MAJOR_NPC = "MAJOR_NPC"
    MINOR_NPC = "MINOR_NPC"
    BACKGROUND = "BACKGROUND"


class GoalStatus(StrEnum):
    """Persistent lifecycle of an important NPC's long-running goal."""

    ACTIVE = "ACTIVE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ACHIEVED = "ACHIEVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class GoalStepStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    CANCELLED = "CANCELLED"


class GoalActionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class KnowledgeState(StrEnum):
    """Prompt section 15."""

    UNKNOWN = "UNKNOWN"
    HEARD = "HEARD"
    SUSPECTED = "SUSPECTED"
    BELIEVED = "BELIEVED"
    KNOWN = "KNOWN"
    DISBELIEVED = "DISBELIEVED"


#: States that may be surfaced to an NPC agent. UNKNOWN never leaves the database.
VISIBLE_KNOWLEDGE_STATES: frozenset[KnowledgeState] = frozenset(
    {
        KnowledgeState.HEARD,
        KnowledgeState.SUSPECTED,
        KnowledgeState.BELIEVED,
        KnowledgeState.KNOWN,
        KnowledgeState.DISBELIEVED,
    }
)


class KnowledgeSource(StrEnum):
    WITNESSED = "WITNESSED"
    TOLD_BY = "TOLD_BY"
    INFERRED = "INFERRED"
    RUMOR = "RUMOR"
    DOCUMENT = "DOCUMENT"
    SEED = "SEED"


class FactScope(StrEnum):
    WORLD = "WORLD"
    FACTION = "FACTION"
    PERSONAL = "PERSONAL"


class MemoryType(StrEnum):
    """Prompt section 16: four layers."""

    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    RELATIONSHIP = "RELATIONSHIP"
    SEMANTIC = "SEMANTIC"


class MemoryTag(StrEnum):
    PROMISE = "promise"
    BETRAYAL = "betrayal"
    RESCUE = "rescue"
    INSULT = "insult"
    CONFLICT = "conflict"
    GIFT = "gift"
    ROMANTIC_EVENT = "romantic_event"
    SHARED_DANGER = "shared_danger"
    MAJOR_CONVERSATION = "major_conversation"
    SECRET_DISCLOSURE = "secret_disclosure"
    TRAUMA = "trauma"
    VICTORY = "victory"
    FAILURE = "failure"
    OTHER = "other"


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"
    LOCAL = "LOCAL"
    FACTION = "FACTION"
    PRIVATE = "PRIVATE"
    SECRET = "SECRET"


class QuestStatus(StrEnum):
    OFFERED = "offered"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    TAKEN_BY_OTHER = "taken_by_other"
    REJECTED = "rejected"


class ThreadStatus(StrEnum):
    DORMANT = "dormant"
    ACTIVE = "active"
    RESOLVED = "resolved"
    FAILED = "failed"
    ABANDONED = "abandoned"


class ClockKind(StrEnum):
    """What a visible clock is counting.

    Players cannot plan against pressure they cannot see. A deadline runs on
    the world clock whatever anyone does; a danger fills when someone else
    makes progress against the player; a project fills when the player does.
    """

    DEADLINE = "deadline"
    DANGER = "danger"
    PROJECT = "project"


class ClockStatus(StrEnum):
    RUNNING = "running"
    #: Every segment is filled and whatever it was counting down to has landed.
    FILLED = "filled"
    #: Stopped before filling - the player defused it, or it stopped mattering.
    CLOSED = "closed"


class DirectorDecisionType(StrEnum):
    NO_EVENT = "NO_EVENT"
    TRIGGER_EVENT = "TRIGGER_EVENT"
    ADVANCE_THREAD = "ADVANCE_THREAD"
    PLANT_FORESHADOWING = "PLANT_FORESHADOWING"


class DirectorEventStatus(StrEnum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImportanceBand(StrEnum):
    """Caps how far a single event may move a relationship (Prompt section 14)."""

    TRIVIAL = "trivial"
    MINOR = "minor"
    MAJOR = "major"
    LIFE_CHANGING = "life_changing"


class Activity(StrEnum):
    """NPC schedule slots (Prompt section 32)."""

    SLEEP = "sleep"
    WORK = "work"
    EAT = "eat"
    CULTIVATE = "cultivate"
    SOCIAL = "social"
    PATROL = "patrol"
    TRAVEL = "travel"
    REST = "rest"
    INVESTIGATE = "investigate"


class LLMRole(StrEnum):
    """Task roles used by the ModelRouter (Prompt section 48)."""

    INTENT = "intent"
    NPC = "npc"
    NPC_MAJOR = "npc_major"
    DIRECTOR = "director"
    #: Fills in the world the player reached for but the pack never wrote down.
    STEWARD = "steward"
    NARRATIVE = "narrative"
    MEMORY = "memory"
    EMBEDDING = "embedding"


class ReasonCode(StrEnum):
    """Structured rejection reasons. The narrative layer may never override these."""

    OK = "OK"
    ACTOR_DEAD = "ACTOR_DEAD"
    TARGET_DEAD = "TARGET_DEAD"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_NOT_PRESENT = "TARGET_NOT_PRESENT"
    LOCATION_NOT_FOUND = "LOCATION_NOT_FOUND"
    LOCATION_UNREACHABLE = "LOCATION_UNREACHABLE"
    LOCATION_LOCKED = "LOCATION_LOCKED"
    REALM_TOO_LOW = "REALM_TOO_LOW"
    SKILL_NOT_LEARNED = "SKILL_NOT_LEARNED"
    SKILL_ON_COOLDOWN = "SKILL_ON_COOLDOWN"
    INSUFFICIENT_SPIRITUAL_POWER = "INSUFFICIENT_SPIRITUAL_POWER"
    INSUFFICIENT_HEALTH = "INSUFFICIENT_HEALTH"
    ITEM_NOT_OWNED = "ITEM_NOT_OWNED"
    ITEM_NOT_HERE = "ITEM_NOT_HERE"
    INVENTORY_FULL = "INVENTORY_FULL"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    NOT_FOR_SALE = "NOT_FOR_SALE"
    NO_MERCHANT_HERE = "NO_MERCHANT_HERE"
    CULTIVATION_NOT_READY = "CULTIVATION_NOT_READY"
    ALREADY_AT_MAX_REALM = "ALREADY_AT_MAX_REALM"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    QUEST_NOT_FOUND = "QUEST_NOT_FOUND"
    QUEST_NOT_OFFERED = "QUEST_NOT_OFFERED"
    FACTION_FORBIDS = "FACTION_FORBIDS"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    NOT_PHYSICALLY_POSSIBLE = "NOT_PHYSICALLY_POSSIBLE"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
