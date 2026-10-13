"""Free text in the deduction mode: the model recognises a move, or plays the part.

The model sees only what the character has already said in public - never
the truth, the lie map, or the solution - so a free reply cannot leak the
answer. Whatever it picks is re-checked by ``CaseEngine`` before it happens.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from engine.case.engine import CaseEngine, Move, MoveRejected
from engine.case.state import CaseState
from engine.core.types import LLMRole
from engine.llm.client import LLMClient

MAX_SAID_CHARS = 200
MAX_REPLY_CHARS = 160


class ActorDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["option", "present", "chat"]
    option: str | None = None
    statement: str | None = None
    evidence: str | None = None
    reply: str | None = None


def _clean_reply(text: str) -> str:
    """Drop JSON debris some models leave after the closing quote."""
    text = text.strip()
    while text and text[-1] in "}]\u3011`":
        text = text[:-1].rstrip()
    for opening, closing in (
        ("\u201c", "\u201d"),
        ("\u300c", "\u300d"),
        ("\uff08", "\uff09"),
    ):
        while text.endswith(closing) and text.count(closing) > text.count(opening):
            text = text[:-1].rstrip()
    return text.strip("\"' \n")


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "-"


def actor_prompt(
    registry: Any, engine: CaseEngine, state: CaseState, character_key: str, said: str
) -> str:
    case = engine.case
    character = case.character(character_key)
    open_statements = [
        f"{key}: {case.statement(key)[1].text}"
        for key in engine.challengeable(state, character)
    ]
    conceded = [
        case.statement(key)[1].text
        for key in state.broken
        if case.statement(key)[0].key == character.key
    ]
    recent = [
        f"{case.texts.player_name if entry.kind == 'player' else character.name}: {entry.text}"
        for entry in state.log
        if entry.kind in {"player", "npc"} and entry.speaker == character.key
    ][-10:]
    options = [
        f"{option.key}: {option.label}"
        for option in character.options
        if engine.option_available(state, character, option)
    ]
    evidence = [
        f"{key}: {case.evidence_item(key).name} | {case.evidence_item(key).description}"
        for key in state.evidence
    ]
    return registry.render(
        "case_actor",
        "v1",
        name=character.name,
        identity=character.role,
        description=character.description,
        voice=character.voice,
        open_statements=_bullet(open_statements),
        conceded=_bullet(conceded),
        recent=_bullet(recent),
        options=_bullet(options),
        evidence=_bullet(evidence),
        said=said,
    )


async def interpret(
    llm: LLMClient,
    engine: CaseEngine,
    state: CaseState,
    character_key: str,
    said: str,
) -> Move:
    """Turn the player's words into a legal move. Raises ``MoveRejected``."""
    said = " ".join(said.split())[:MAX_SAID_CHARS]
    if not said:
        raise MoveRejected("nothing was said")
    character = engine.case.character(character_key)
    if character.key in state.silent:
        raise MoveRejected("character will not talk")
    decision = await llm.generate_structured(
        LLMRole.NPC_MAJOR,
        ActorDecision,
        actor_prompt(llm.registry, engine, state, character_key, said),
        prompt_version="case_actor_v1",
        temperature=0.4,
        max_output_tokens=700,
    )
    if decision.action == "option" and decision.option:
        options = {option.key: option for option in character.options}
        option = options.get(decision.option)
        if option is not None and engine.option_available(state, character, option):
            return Move("option", target=option.key, said=said)
    if (
        decision.action == "present"
        and decision.statement in engine.challengeable(state, character)
        and decision.evidence in state.evidence
    ):
        return Move("present", target=decision.statement, evidence=decision.evidence, said=said)
    reply = _clean_reply(decision.reply or "")
    if not reply:
        raise MoveRejected("the character had nothing to say")
    if len(reply) > MAX_REPLY_CHARS:
        reply = reply[:MAX_REPLY_CHARS].rstrip("\uff0c\u3001\uff1b") + "\u2026\u2026"
    return Move("chat", target=character.key, said=said, reply=reply)
