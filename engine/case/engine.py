"""Deterministic rules for authored cases (deduction and scheme modes).

Every outcome here is decided by the authored case, never by a model: a lie
breaks only under the evidence written against it, patience and stance move
by fixed amounts, a bluff and the hidden variables roll a seeded die. The language model is allowed to *pick*
one of these moves on the player's behalf when they type freely, and to say
something in character when nothing applies - it cannot invent a result.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from engine.case.schema import (
    CaseDefinition,
    Character,
    Effects,
    Extra,
    Option,
    Requirement,
)
from engine.case.state import CaseState, LogEntry, LogKind
from engine.core.errors import EngineError
from engine.rng.game_rng import GameRNG


class MoveRejected(EngineError):
    """The move is not legal right now. The state is unchanged."""

    code = "CASE_MOVE_REJECTED"


MoveKind = Literal["begin", "talk", "examine", "option", "present", "think", "chat", "accuse"]


@dataclass(frozen=True, slots=True)
class Move:
    kind: MoveKind
    target: str | None = None
    evidence: str | None = None
    #: The player's own words, when the move came from free text.
    said: str | None = None
    reply: str | None = None
    culprit: str | None = None
    weapon: str | None = None
    motive: str | None = None
    exhibits: tuple[str, ...] = ()


class CaseEngine:
    def __init__(self, case: CaseDefinition) -> None:
        self.case = case

    # ------------------------------------------------------------------
    def new_state(self, seed: str) -> CaseState:
        rng = GameRNG(seed).derive("variables")
        return CaseState(
            case_key=self.case.key,
            case_version=self.case.version,
            seed=seed,
            minutes_left=self.case.minutes_total,
            patience={c.key: c.patience for c in self.case.characters},
            stance={c.key: c.stance for c in self.case.characters if c.stance is not None},
            variables={v.key: rng.choice(v.options) for v in self.case.variables},
            evidence=list(self.case.starting_evidence),
        )

    def apply(self, state: CaseState, move: Move) -> CaseState:
        """Return a new state with ``move`` applied, or raise ``MoveRejected``."""
        next_state = state.model_copy(deep=True)
        before = len(next_state.log)
        handler = getattr(self, f"_{move.kind}", None)
        if handler is None:
            raise MoveRejected(f"unknown move {move.kind}")
        if next_state.status == "closed":
            raise MoveRejected("case is closed")
        if next_state.status == "briefing" and move.kind != "begin":
            raise MoveRejected("case has not begun")
        if next_state.status == "deadline" and move.kind not in {"accuse", "talk"}:
            raise MoveRejected("time is up; only an accusation remains")
        handler(next_state, move)
        if len(next_state.log) != before or move.kind != "talk":
            next_state.moves += 1
        return next_state

    # ------------------------------------------------------------------
    # Moves
    # ------------------------------------------------------------------
    def _begin(self, state: CaseState, move: Move) -> None:
        if state.status != "briefing":
            raise MoveRejected("case already begun")
        state.status = "active"
        self._log(state, "narration", self.case.opening)

    def _talk(self, state: CaseState, move: Move) -> None:
        character = self._character(move.target)
        state.current = character.key
        if character.key in state.met:
            return
        state.met.append(character.key)
        self._log(state, "npc", character.intro, speaker=character.key)
        for statement in character.statements:
            if statement.initial and statement.key not in state.statements:
                state.statements.append(statement.key)
                self._log(state, "npc", statement.text, speaker=character.key)

    def _examine(self, state: CaseState, move: Move) -> None:
        location, spot = self._lookup(self.case.spot, move.target, "spot")
        if spot.key in state.examined:
            raise MoveRejected("already examined")
        if not self.requirement_met(state, spot.requires):
            raise MoveRejected("spot is not reachable yet")
        state.examined.append(spot.key)
        state.current = None
        self._log(state, "player", self._text("examine", location=location.name, spot=spot.label))
        self._log(state, "narration", spot.narration)
        self._apply_effects(state, None, spot.effects)
        self._spend(state)

    def _option(self, state: CaseState, move: Move) -> None:
        character, option = self._lookup(self.case.option, move.target, "option")
        if not self.option_available(state, character, option):
            raise MoveRejected("option is not available")
        state.current = character.key
        if not option.repeatable:
            state.used_options.append(option.key)
        self._log(state, "player", move.said or option.label, speaker=character.key)
        succeeded = True
        if option.gamble is not None:
            rng = GameRNG(state.seed).derive(f"{state.moves}:{option.key}")
            succeeded = rng.chance(option.gamble.chance)
        if succeeded:
            for line in option.lines:
                self._log(state, "npc", line, speaker=character.key)
            self._apply_effects(state, character, option.effects)
            self._apply_extras(state, character, option.extras)
        else:
            assert option.gamble is not None
            self._log(state, "fail", self._text("bluff_failed"))
            for line in option.gamble.failure_lines:
                self._log(state, "npc", line, speaker=character.key)
            self._adjust_patience(state, character, option.gamble.failure_patience)
        self._spend(state)

    def _present(self, state: CaseState, move: Move) -> None:
        character, statement = self._lookup(self.case.statement, move.target, "statement")
        if statement.key not in state.statements or statement.key in state.broken:
            raise MoveRejected("statement is not open to challenge")
        if character.key in state.silent:
            raise MoveRejected("character will not talk")
        if move.evidence not in state.evidence:
            raise MoveRejected("evidence is not in hand")
        item = self.case.evidence_item(move.evidence)
        state.current = character.key
        quoted = (
            statement.text
            if len(statement.text) <= 16
            else self._text("present_quote_cut", text=statement.text[:15])
        )
        self._log(
            state,
            "player",
            move.said or self._text("present", quote=quoted, evidence=item.name),
            speaker=character.key,
            evidence=item.key,
        )
        if statement.lie and move.evidence in statement.contradicted_by:
            self._break(state, character, statement.key)
        else:
            count = state.wrong_presents.get(character.key, 0)
            state.wrong_presents[character.key] = count + 1
            self._log(
                state,
                "npc",
                character.wrong_present[count % len(character.wrong_present)],
                speaker=character.key,
            )
            self._log(state, "fail", self._text("present_failed", evidence=item.name))
            self._adjust_patience(state, character, -1)
        self._spend(state)

    def _chat(self, state: CaseState, move: Move) -> None:
        character = self._character(move.target)
        if character.key in state.silent:
            raise MoveRejected("character will not talk")
        if character.key not in state.met:
            raise MoveRejected("talk to the character first")
        if not move.said or not move.reply:
            raise MoveRejected("chat needs both sides")
        state.current = character.key
        self._log(state, "player", move.said, speaker=character.key)
        self._log(state, "npc", move.reply, speaker=character.key)
        self._spend(state)

    def _think(self, state: CaseState, move: Move) -> None:
        self._log(state, "note", self.hint(state))
        self._spend(state)

    def _accuse(self, state: CaseState, move: Move) -> None:
        accusation, endings = self.case.accusation, self.case.endings
        if accusation is None or endings is None:
            raise MoveRejected("this case has no accusation")
        suspects = {c.key for c in self.case.characters if c.suspect}
        if move.culprit not in suspects:
            raise MoveRejected("unknown suspect")
        if move.weapon not in {w.key for w in accusation.weapons}:
            raise MoveRejected("unknown weapon")
        if move.motive not in {m.key for m in accusation.motives}:
            raise MoveRejected("unknown motive")
        exhibits = list(dict.fromkeys(move.exhibits))
        if len(exhibits) > accusation.max_evidence:
            raise MoveRejected("too many exhibits")
        if any(key not in state.evidence for key in exhibits):
            raise MoveRejected("exhibit is not in hand")

        culprit = self.case.character(move.culprit)
        weapon = next(w for w in accusation.weapons if w.key == move.weapon)
        motive = next(m for m in accusation.motives if m.key == move.motive)
        names = self._join(self.case.evidence_item(key).name for key in exhibits)
        self._log(
            state,
            "player",
            self._text(
                "accuse",
                culprit=culprit.name,
                weapon=weapon.label,
                motive=motive.label,
                exhibits=names or self._text("accuse_nothing"),
            ),
        )

        right_culprit = move.culprit == accusation.culprit
        held = set(exhibits)
        pillars: list[dict[str, Any]] = []
        for pillar in accusation.pillars:
            met = right_culprit and any(set(group) <= held for group in pillar.any_of)
            if pillar.key == "means":
                met = met and move.weapon == accusation.weapon
            if pillar.key == "motive":
                met = met and move.motive == accusation.motive
            pillars.append({"key": pillar.key, "label": pillar.label, "met": met})
            if right_culprit:
                if met:
                    self._log(state, "verdict", pillar.established)
                else:
                    self._log(state, "npc", pillar.rebuttal, speaker=culprit.key)

        met_count = sum(1 for pillar in pillars if pillar["met"])
        if not right_culprit:
            ending_key = f"wrong:{move.culprit}"
            ending = endings.wrong[move.culprit]
        elif met_count == len(pillars):
            ending_key, ending = "truth", endings.truth
        elif met_count >= 2:
            ending_key, ending = "partial", endings.partial
        else:
            ending_key, ending = "escaped", endings.escaped

        epilogues = [
            item.text
            for item in endings.epilogues
            if item.flag in state.flags
            and (item.unless_culprit is None or item.unless_culprit != move.culprit)
            and (item.if_culprit is None or item.if_culprit == move.culprit)
        ]
        lies = [s.key for c in self.case.characters for s in c.statements if s.lie]
        state.status = "closed"
        state.current = None
        state.result = {
            "mode": "deduction",
            "ending": ending_key,
            "solved": ending_key == "truth",
            "title": ending.title,
            "text": ending.text.strip(),
            "epilogues": epilogues,
            "accused": culprit.name,
            "culprit_correct": right_culprit,
            "weapon_correct": move.weapon == accusation.weapon,
            "motive_correct": move.motive == accusation.motive,
            "pillars": pillars,
            "minutes_left": max(0, state.minutes_left),
            "lies_broken": len([key for key in state.broken if key in lies]),
            "lies_total": len(lies),
            "evidence_found": len(state.evidence),
            "evidence_total": len(self.case.evidence),
        }

    # ------------------------------------------------------------------
    # Rules shared by moves and the client view
    # ------------------------------------------------------------------
    def requirement_met(self, state: CaseState, requirement: Requirement) -> bool:
        return (
            all(key in state.evidence for key in requirement.evidence)
            and all(key in state.broken for key in requirement.broken)
            and all(
                key not in state.broken for key in requirement.unbroken
            )
            and all(key in state.flags for key in requirement.flags)
            and all(key not in state.flags for key in requirement.not_flags)
            and all(key in state.examined for key in requirement.examined)
            and all(key not in state.evidence for key in requirement.lacks_evidence)
            and (
                not requirement.any_evidence
                or any(key in state.evidence for key in requirement.any_evidence)
            )
            and all(state.variables.get(key) == value for key, value in requirement.variables.items())
            and all(
                state.stance.get(key, 0) >= value for key, value in requirement.stance_min.items()
            )
        )

    def option_available(self, state: CaseState, character: Character, option: Option) -> bool:
        if character.key in state.silent or character.key not in state.met:
            return False
        if option.key in state.used_options:
            return False
        # An option that only hands out evidence already in hand is a wasted turn.
        gives = option.effects.evidence
        if gives and all(key in state.evidence for key in gives) and not option.effects.breaks:
            return False
        return self.requirement_met(state, option.requires)

    def challengeable(self, state: CaseState, character: Character) -> list[str]:
        if character.key in state.silent:
            return []
        return [
            s.key
            for s in character.statements
            if s.key in state.statements and s.key not in state.broken
        ]

    def hint(self, state: CaseState) -> str:
        """What Dr. Lin's notebook says next. Ordered from sharpest to vaguest."""
        for character in self.case.characters:
            if character.key in state.silent:
                continue
            for statement in character.statements:
                if (
                    statement.key in state.statements
                    and statement.key not in state.broken
                    and statement.lie
                    and any(key in state.evidence for key in statement.contradicted_by)
                ):
                    return self._text(
                        "hint_breakable", name=character.name, statement=statement.text
                    )
        open_lies = [
            (character, statement)
            for character in self.case.characters
            if character.key not in state.silent
            for statement in character.statements
            if statement.lie and statement.key in state.statements and statement.key not in state.broken
        ]
        for character, statement in open_lies:
            for location in self.case.locations:
                for spot in location.spots:
                    if (
                        spot.key not in state.examined
                        and self.requirement_met(state, spot.requires)
                        and set(spot.effects.evidence) & set(statement.contradicted_by)
                    ):
                        return self._text(
                            "hint_spot",
                            name=character.name,
                            statement=statement.text,
                            location=location.name,
                        )
            for other in self.case.characters:
                for option in other.options:
                    if (
                        option.kind == "ask"
                        and self.option_available(state, other, option)
                        and set(option.effects.evidence) & set(statement.contradicted_by)
                    ):
                        return self._text(
                            "hint_person",
                            name=character.name,
                            statement=statement.text,
                            other=other.name,
                        )
        unmet = [c for c in self.case.characters if c.key not in state.met]
        if unmet:
            return self._text("hint_unmet", names=self._join(c.name for c in unmet))
        unseen = [
            location.name
            for location in self.case.locations
            if any(
                spot.key not in state.examined and self.requirement_met(state, spot.requires)
                for spot in location.spots
            )
        ]
        held = set(state.evidence)
        accusation = self.case.accusation
        ready = accusation is not None and all(
            any(set(group) <= held for group in pillar.any_of) for pillar in accusation.pillars
        )
        if ready:
            return self._text("hint_ready")
        if unseen:
            return self._text("hint_unseen", locations=self._join(unseen))
        return self._text("hint_exhausted")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _break(self, state: CaseState, character: Character, statement_key: str) -> None:
        _owner, statement = self.case.statement(statement_key)
        if statement_key in state.broken:
            return
        state.broken.append(statement_key)
        self._log(
            state,
            "break",
            self._text("lie_broken", statement=statement.text),
            speaker=character.key,
        )
        if statement.on_break:
            for line in statement.on_break.lines:
                self._log(state, "npc", line, speaker=character.key)
            self._apply_effects(state, character, statement.on_break.effects)
            self._apply_extras(state, character, statement.on_break.extras)

    def _apply_effects(self, state: CaseState, character: Character | None, effects: Effects) -> None:
        for key in effects.statements:
            if key not in state.statements:
                state.statements.append(key)
        for key in effects.evidence:
            if key not in state.evidence:
                state.evidence.append(key)
                item = self.case.evidence_item(key)
                self._log(
                    state, "evidence", self._text("evidence_gained", name=item.name), evidence=key
                )
        for key in effects.remove_evidence:
            if key in state.evidence:
                state.evidence.remove(key)
                if self.case.texts.evidence_lost:
                    item = self.case.evidence_item(key)
                    self._log(state, "system", self._text("evidence_lost", name=item.name))
        for key in effects.flags:
            if key not in state.flags:
                state.flags.append(key)
        for key, delta in effects.stance.items():
            self._adjust_stance(state, key, delta)
        for key in effects.breaks:
            assert character is not None
            self._break(state, character, key)
        if character is not None:
            if effects.patience:
                self._adjust_patience(state, character, effects.patience)
            if effects.silence and character.key not in state.silent:
                state.silent.append(character.key)
                state.patience[character.key] = 0
        if effects.route is not None and state.status != "closed":
            self._finish_route(state, effects.route)

    def _apply_extras(
        self, state: CaseState, character: Character | None, extras: list[Extra]
    ) -> None:
        for extra in extras:
            if state.status == "closed":
                return
            if self.requirement_met(state, extra.requires):
                for line in extra.lines:
                    kind: LogKind = "npc" if character is not None else "narration"
                    self._log(state, kind, line, speaker=character.key if character else None)
                self._apply_effects(state, character, extra.effects)

    def _adjust_stance(self, state: CaseState, key: str, delta: int) -> None:
        if not delta or key not in state.stance:
            return
        state.stance[key] = max(-3, min(3, state.stance[key] + delta))
        template = self.case.texts.stance_up if delta > 0 else self.case.texts.stance_down
        if template:
            name = self.case.character(key).name
            self._log(state, "system", template.format(name=name), speaker=key)

    def _finish_route(self, state: CaseState, route_key: str) -> None:
        """Close a scheme run through one authored route and grade it."""
        scheme = self.case.scheme
        assert scheme is not None
        route = self.case.route(route_key)
        for flag in route.flags:
            if flag not in state.flags:
                state.flags.append(flag)
        stars = [
            {"key": star.key, "label": star.label, "met": route.success
             and self.requirement_met(state, star.requires)}
            for star in scheme.stars
        ]
        earned = sum(1 for star in stars if star["met"])
        if not route.success:
            grade = "F"
        else:
            ladder = ["C", "B", "A", "S"]
            grade = ladder[min(len(ladder) - 1, len(ladder) - 1 - (len(stars) - earned))]
            if route.grade_cap and ladder.index(grade) > ladder.index(route.grade_cap):
                grade = route.grade_cap
        epilogues = [
            item.text
            for item in scheme.epilogues
            if item.flag in state.flags
            and (item.unless_flag is None or item.unless_flag not in state.flags)
        ]
        lies = [s.key for c in self.case.characters for s in c.statements if s.lie]
        self._log(state, "verdict", route.title)
        state.status = "closed"
        state.current = None
        state.result = {
            "mode": "scheme",
            "ending": route.key,
            "route": route.key,
            "solved": route.success,
            "title": route.title,
            "label": route.label,
            "text": route.text.strip(),
            "grade": grade,
            "stars": stars,
            "epilogues": epilogues,
            "minutes_left": max(0, state.minutes_left),
            "lies_broken": len([key for key in state.broken if key in lies]),
            "lies_total": len(lies),
            "evidence_found": len(state.evidence),
            "evidence_total": len(self.case.evidence),
        }

    def _adjust_patience(self, state: CaseState, character: Character, delta: int) -> None:
        if character.key in state.silent:
            return
        value = max(0, state.patience.get(character.key, character.patience) + delta)
        state.patience[character.key] = value
        if delta < 0:
            self._log(
                state,
                "fail",
                self._text("patience_lost", name=character.name, delta=delta),
                speaker=character.key,
            )
        if value == 0:
            state.silent.append(character.key)
            self._log(state, "narration", character.silent_line, speaker=character.key)
            self._apply_effects(state, character, character.on_silence)

    def _spend(self, state: CaseState) -> None:
        if state.status == "closed":
            return
        state.minutes_left = max(0, state.minutes_left - self.case.action_minutes)
        for event in sorted(self.case.events, key=lambda e: -e.at_minutes_left):
            if event.key in state.fired_events or state.minutes_left > event.at_minutes_left:
                continue
            # A moment that has passed is gone, whether or not it happened.
            state.fired_events.append(event.key)
            if self.requirement_met(state, event.requires):
                self._log(state, "event", event.text, speaker=event.speaker)
                self._apply_effects(state, None, event.effects)
            if state.status == "closed":
                return
        if state.minutes_left <= 0 and state.status == "active":
            if self.case.scheme is not None:
                self._finish_route(state, self.case.scheme.timeout_route)
            else:
                assert self.case.accusation is not None
                state.status = "deadline"
                self._log(state, "event", self.case.accusation.forced_line)

    def _log(
        self,
        state: CaseState,
        kind: LogKind,
        text: str,
        *,
        speaker: str | None = None,
        evidence: str | None = None,
    ) -> None:
        state.log.append(
            LogEntry(
                id=len(state.log) + 1,
                kind=kind,
                text=text.strip(),
                speaker=speaker,
                evidence=evidence,
                minutes_left=state.minutes_left,
            )
        )

    def _text(self, key: str, **values: object) -> str:
        template: str = getattr(self.case.texts, key)
        return template.format(**values)

    def _join(self, items: Iterable[str]) -> str:
        return self.case.texts.list_separator.join(items)

    def _character(self, key: str | None) -> Character:
        return self._lookup(self.case.character, key, "character")

    @staticmethod
    def _lookup(finder, key: str | None, what: str):  # type: ignore[no-untyped-def]
        if not key:
            raise MoveRejected(f"{what} is required")
        try:
            return finder(key)
        except KeyError as exc:
            raise MoveRejected(f"unknown {what}") from exc
