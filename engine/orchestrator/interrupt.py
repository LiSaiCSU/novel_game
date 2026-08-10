"""When the story must stop and wait for the player.

A text RPG that asks "what do you do?" after every single action is a command
prompt wearing a novel's clothes. The fix is not to ask less politely - it is
to let the character keep acting until something happens that only the player
can answer, and to decide *that* here, in code.

The narrator gets a vote (it can see that a scene ended on a question), but it
is only a vote. Everything that actually matters - a blade drawn, a bargain
offered, a major character speaking to you directly - is detected from
committed facts, so the handover never depends on a model being in the mood.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from engine.actions.schema import ActionOutcome
from engine.contentpack.pack import ContentPack
from engine.core.models import Character
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import CharacterType
from engine.world.state_view import WorldStateView


class InterruptReason(StrEnum):
    """Why the story handed control back."""

    #: Someone the player cares about spoke to them and is waiting.
    ADDRESSED = "ADDRESSED"
    #: An NPC acted on the player - blocked, attacked, offered, gave.
    ACTED_UPON = "ACTED_UPON"
    #: Blood, or the credible promise of it.
    DANGER = "DANGER"
    #: Someone present died.
    DEATH = "DEATH"
    #: A bargain is on the table and refusing is a real option.
    OFFER = "OFFER"
    #: The director put something in motion that the player should react to.
    MAJOR_EVENT = "MAJOR_EVENT"
    #: The narrator ended the scene on an open question.
    SCENE_QUESTION = "SCENE_QUESTION"
    #: Nothing dramatic happened; we simply ran far enough for one sitting.
    BUDGET = "BUDGET"
    #: The character could not carry on with what they were doing.
    STUCK = "STUCK"


#: Reasons that mean "something happened", as opposed to "we stopped counting".
DRAMATIC: frozenset[InterruptReason] = frozenset(
    {
        InterruptReason.ADDRESSED,
        InterruptReason.ACTED_UPON,
        InterruptReason.DANGER,
        InterruptReason.DEATH,
        InterruptReason.OFFER,
        InterruptReason.MAJOR_EVENT,
    }
)


@dataclass(slots=True)
class Interrupt:
    reason: InterruptReason
    detail: str = ""
    #: Characters the player is now expected to answer, most relevant first.
    involves: list[str] = field(default_factory=list)

    @property
    def dramatic(self) -> bool:
        return self.reason in DRAMATIC

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason": str(self.reason),
            "detail": self.detail,
            "involves": self.involves,
        }


class InterruptDetector:
    """Reads one committed step and decides whether the player is needed.

    Thresholds come from the content pack, so a gentler or harsher genre can
    tune how often it takes the wheel without touching this logic.
    """

    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.importance_threshold = float(
            pack.rule("auto_advance.interrupt_importance", 0.5)
        )
        self.health_loss_fraction = float(
            pack.rule("auto_advance.interrupt_health_loss", 0.08)
        )
        self.hostile_actions: set[str] = set(
            pack.rule("auto_advance.hostile_actions", []) or ["ATTACK", "STEAL"]
        )
        self.engaging_actions: set[str] = set(
            pack.rule("auto_advance.engaging_actions", [])
            or ["GIVE_ITEM", "ASK", "TALK", "CONVERSATION"]
        )
        self.offer_events: set[str] = set(
            pack.rule("auto_advance.offer_events", []) or ["QUEST_OFFER"]
        )

    # ------------------------------------------------------------------
    def detect(
        self,
        state: WorldStateView,
        *,
        outcome: ActionOutcome,
        change_set: ChangeSet,
        npc_decisions: list[dict[str, Any]],
        present: list[Character],
        health_before: int,
        director: dict[str, Any] | None = None,
        scene_question: bool = False,
    ) -> Interrupt | None:
        by_key = {c.key: c for c in present}
        player = state.player

        # -- someone is bleeding ------------------------------------------
        if not player.alive:
            return Interrupt(InterruptReason.DEATH, "player_died")
        deaths = [
            change.target_id
            for change in change_set.by_kind(ChangeKind.CHARACTER_DEATH)
        ]
        if deaths:
            names = [
                c.display_name for c in present if c.id in deaths
            ] or ["someone"]
            return Interrupt(InterruptReason.DEATH, "death", involves=names)

        lost = health_before - player.health
        if lost > 0 and lost >= player.max_health * self.health_loss_fraction:
            return Interrupt(
                InterruptReason.DANGER, f"health_lost:{lost}"
            )

        # -- an NPC did something to the player ----------------------------
        for record in npc_decisions:
            decision = record.get("decision") or {}
            body = decision.get("decision") or {}
            action_type = str(body.get("action_type") or "")
            targets_player = str(body.get("target") or "") in (player.key, "player")
            npc = by_key.get(str(record.get("npc") or ""))
            name = npc.display_name if npc else str(record.get("npc") or "")

            if action_type in self.hostile_actions and targets_player:
                return Interrupt(
                    InterruptReason.DANGER, f"hostile:{action_type}", involves=[name]
                )
            if action_type in self.engaging_actions and targets_player:
                return Interrupt(
                    InterruptReason.ACTED_UPON,
                    f"npc_action:{action_type}",
                    involves=[name],
                )
            # A major character speaking to you is the whole point of the genre.
            if (
                decision.get("spoken_line")
                and npc is not None
                and npc.character_type is CharacterType.MAJOR_NPC
            ):
                return Interrupt(
                    InterruptReason.ADDRESSED, "major_npc_spoke", involves=[name]
                )

        # -- a bargain is on the table -------------------------------------
        for event in change_set.events:
            if event.event_type in self.offer_events:
                return Interrupt(InterruptReason.OFFER, f"event:{event.event_type}")
        for change in change_set.by_kind(ChangeKind.QUEST_STATUS):
            if str(change.after) == "offered":
                return Interrupt(InterruptReason.OFFER, "quest_offered")

        # -- the director moved the world ----------------------------------
        if director:
            decision = director.get("decision") or {}
            immediate = int(decision.get("schedule_after_minutes", 0) or 0) == 0
            triggered = str(decision.get("decision", "")) == "TRIGGER_EVENT"
            if triggered and immediate and not director.get("rejections"):
                return Interrupt(InterruptReason.MAJOR_EVENT, "director_event")

        # -- something simply mattered -------------------------------------
        if outcome.importance >= self.importance_threshold:
            return Interrupt(
                InterruptReason.MAJOR_EVENT, f"importance:{outcome.importance:.2f}"
            )
        for event in change_set.events:
            if event.importance >= self.importance_threshold:
                return Interrupt(
                    InterruptReason.MAJOR_EVENT, f"event:{event.event_type}"
                )

        # -- the narrator's vote, counted last ------------------------------
        if scene_question:
            return Interrupt(InterruptReason.SCENE_QUESTION, "narrator")
        return None
