"""Authored case definitions.

A case is a closed, hand-written situation. Two shapes share one engine:

- ``deduction``: the truth is fixed, every lie names the evidence that breaks
  it, and a single accusation is graded against declared pillars.
- ``scheme``: one goal with several authored ways to reach it. Each route ends
  the run the moment it is triggered; bonus stars grade how cleanly it was
  done, and hidden variables rolled from the seed move the keys around so the
  same story plays differently next time.

Nothing here is generated at play time, which is what lets the choices be
good - each one was written by somebody who knew every answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.core.errors import ContentValidationError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Requirement(_Strict):
    """Conditions over what the player has found, broken, triggered and rolled."""

    evidence: list[str] = Field(default_factory=list)
    any_evidence: list[str] = Field(default_factory=list)
    broken: list[str] = Field(default_factory=list)
    unbroken: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    not_flags: list[str] = Field(default_factory=list)
    examined: list[str] = Field(default_factory=list)
    lacks_evidence: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    stance_min: dict[str, int] = Field(default_factory=dict)


class Effects(_Strict):
    evidence: list[str] = Field(default_factory=list)
    remove_evidence: list[str] = Field(default_factory=list)
    statements: list[str] = Field(default_factory=list)
    breaks: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    patience: int = 0
    stance: dict[str, int] = Field(default_factory=dict)
    silence: bool = False
    #: Scheme mode: end the run through this route.
    route: str | None = None


class Extra(_Strict):
    """Effects that only happen if something was already true - order matters."""

    requires: Requirement
    lines: list[str] = Field(default_factory=list)
    effects: Effects = Effects()


class Evidence(_Strict):
    key: str
    name: str
    kind: Literal["physical", "document", "testimony", "observation"]
    description: str


class Spot(_Strict):
    key: str
    label: str
    narration: str
    requires: Requirement = Requirement()
    effects: Effects = Effects()


class Location(_Strict):
    key: str
    name: str
    description: str
    spots: list[Spot]


class StatementBreak(_Strict):
    lines: list[str]
    effects: Effects = Effects()
    extras: list[Extra] = Field(default_factory=list)


class Statement(_Strict):
    key: str
    text: str
    initial: bool = False
    lie: bool = False
    contradicted_by: list[str] = Field(default_factory=list)
    on_break: StatementBreak | None = None

    @model_validator(mode="after")
    def _lies_can_break(self) -> Statement:
        if self.lie and (not self.contradicted_by or self.on_break is None):
            raise ValueError(f"lie {self.key} needs contradicted_by and on_break")
        if not self.lie and self.contradicted_by:
            raise ValueError(f"true statement {self.key} cannot be contradicted")
        return self


class Gamble(_Strict):
    """A bluff: it works ``chance`` of the time, and costs dearly when it does not."""

    chance: float = Field(gt=0, lt=1)
    failure_lines: list[str]
    failure_patience: int = -2


class Option(_Strict):
    key: str
    kind: Literal["ask", "press", "comfort", "bluff", "trade", "act"]
    label: str
    requires: Requirement = Requirement()
    lines: list[str]
    effects: Effects = Effects()
    extras: list[Extra] = Field(default_factory=list)
    gamble: Gamble | None = None
    repeatable: bool = False

    @model_validator(mode="after")
    def _bluffs_gamble(self) -> Option:
        if (self.kind == "bluff") != (self.gamble is not None):
            raise ValueError(f"option {self.key}: bluffs and only bluffs carry a gamble")
        return self


class Character(_Strict):
    key: str
    name: str
    role: str
    description: str
    voice: str
    suspect: bool = True
    patience: int = Field(default=3, ge=1, le=9)
    #: Scheme mode: how far this person leans toward the player. ``None`` hides it.
    stance: int | None = Field(default=None, ge=-3, le=3)
    intro: str
    statements: list[Statement] = Field(default_factory=list)
    options: list[Option] = Field(default_factory=list)
    wrong_present: list[str] = Field(min_length=1)
    silent_line: str
    #: What happens when patience runs out, beyond falling silent.
    on_silence: Effects = Effects()


class Choice(_Strict):
    key: str
    label: str


class Pillar(_Strict):
    key: str
    label: str
    any_of: list[list[str]] = Field(min_length=1)
    rebuttal: str
    established: str


class Ending(_Strict):
    title: str
    text: str


class Epilogue(_Strict):
    flag: str
    text: str
    unless_culprit: str | None = None
    if_culprit: str | None = None
    unless_flag: str | None = None


class Accusation(_Strict):
    culprit: str
    weapon: str
    motive: str
    weapons: list[Choice]
    motives: list[Choice]
    max_evidence: int = Field(default=6, ge=1, le=10)
    pillars: list[Pillar]
    forced_line: str


class Endings(_Strict):
    truth: Ending
    partial: Ending
    escaped: Ending
    wrong: dict[str, Ending]
    epilogues: list[Epilogue] = Field(default_factory=list)


class Route(_Strict):
    """One authored way a scheme ends: a win to collect, or a way to lose."""

    key: str
    title: str
    #: How it was done, in a few words, for the collection.
    label: str
    text: str
    success: bool = True
    #: Shown while the route is undiscovered, to tempt another run.
    teaser: str = ""
    flags: list[str] = Field(default_factory=list)
    grade_cap: Literal["S", "A", "B", "C"] | None = None


class Star(_Strict):
    key: str
    label: str
    requires: Requirement


class Variable(_Strict):
    """A hidden fact rolled once per run, so the keys are not where they were."""

    key: str
    options: list[str] = Field(min_length=2)


class Scheme(_Strict):
    routes: list[Route]
    timeout_route: str
    stars: list[Star] = Field(default_factory=list)
    epilogues: list[Epilogue] = Field(default_factory=list)


class TimedEvent(_Strict):
    key: str
    at_minutes_left: int
    speaker: str | None = None
    text: str
    #: The event only happens if this still holds when its time comes.
    requires: Requirement = Requirement()
    effects: Effects = Effects()


class CaseTexts(_Strict):
    """Every sentence the engine itself writes, as ``str.format`` templates.

    The engine knows when to say something; the case decides how it reads.
    """

    player_name: str
    list_separator: str
    examine: str
    evidence_gained: str
    lie_broken: str
    present: str
    present_quote_cut: str
    present_failed: str
    bluff_failed: str
    patience_lost: str
    accuse: str = ""
    accuse_nothing: str = ""
    hint_breakable: str
    hint_spot: str
    hint_person: str
    hint_unmet: str
    hint_ready: str = ""
    hint_unseen: str
    hint_exhausted: str
    evidence_lost: str = ""
    stance_up: str = ""
    stance_down: str = ""


class BriefingPage(_Strict):
    title: str
    body: str


class CaseDefinition(_Strict):
    key: str
    version: int
    mode: Literal["deduction", "scheme"] = "deduction"
    title: str
    tagline: str
    setting: str
    estimated_minutes: str
    clock_label: str = ""
    minutes_total: int = Field(ge=5)
    action_minutes: int = Field(default=5, ge=1)
    goal: str
    briefing: list[BriefingPage]
    rules: list[BriefingPage]
    opening: str
    victim: str = ""
    characters: list[Character]
    locations: list[Location]
    evidence: list[Evidence]
    starting_evidence: list[str] = Field(default_factory=list)
    variables: list[Variable] = Field(default_factory=list)
    events: list[TimedEvent] = Field(default_factory=list)
    accusation: Accusation | None = None
    endings: Endings | None = None
    scheme: Scheme | None = None
    texts: CaseTexts

    # ------------------------------------------------------------------
    def character(self, key: str) -> Character:
        for character in self.characters:
            if character.key == key:
                return character
        raise KeyError(key)

    def statement(self, key: str) -> tuple[Character, Statement]:
        for character in self.characters:
            for statement in character.statements:
                if statement.key == key:
                    return character, statement
        raise KeyError(key)

    def option(self, key: str) -> tuple[Character, Option]:
        for character in self.characters:
            for option in character.options:
                if option.key == key:
                    return character, option
        raise KeyError(key)

    def spot(self, key: str) -> tuple[Location, Spot]:
        for location in self.locations:
            for spot in location.spots:
                if spot.key == key:
                    return location, spot
        raise KeyError(key)

    def evidence_item(self, key: str) -> Evidence:
        for item in self.evidence:
            if item.key == key:
                return item
        raise KeyError(key)

    def route(self, key: str) -> Route:
        assert self.scheme is not None
        for route in self.scheme.routes:
            if route.key == key:
                return route
        raise KeyError(key)

    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _references_resolve(self) -> CaseDefinition:
        problems: list[str] = []
        evidence = {item.key for item in self.evidence}
        characters = {character.key for character in self.characters}
        statements = {s.key for c in self.characters for s in c.statements}
        options = {o.key for c in self.characters for o in c.options}
        spots = {s.key for loc in self.locations for s in loc.spots}
        variables = {v.key: set(v.options) for v in self.variables}
        routes = {r.key for r in self.scheme.routes} if self.scheme else set()

        keys = [item.key for item in self.evidence] + list(statements) + list(options) + list(spots)
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            problems.append(f"duplicate keys: {sorted(duplicates)}")

        def check_requirement(where: str, requirement: Requirement) -> None:
            for key in requirement.evidence + requirement.lacks_evidence + requirement.any_evidence:
                if key not in evidence:
                    problems.append(f"{where}: unknown evidence {key}")
            for key in requirement.broken + requirement.unbroken:
                if key not in statements:
                    problems.append(f"{where}: unknown statement {key}")
            for key in requirement.examined:
                if key not in spots:
                    problems.append(f"{where}: unknown spot {key}")
            for key, value in requirement.variables.items():
                if value not in variables.get(key, set()):
                    problems.append(f"{where}: unknown variable value {key}={value}")
            for key in requirement.stance_min:
                if key not in characters or self.character(key).stance is None:
                    problems.append(f"{where}: {key} has no stance")

        def check_effects(where: str, effects: Effects) -> None:
            for key in effects.evidence + effects.remove_evidence:
                if key not in evidence:
                    problems.append(f"{where}: unknown evidence {key}")
            for key in effects.statements + effects.breaks:
                if key not in statements:
                    problems.append(f"{where}: unknown statement {key}")
            for key in effects.stance:
                if key not in characters or self.character(key).stance is None:
                    problems.append(f"{where}: {key} has no stance")
            if effects.route is not None and effects.route not in routes:
                problems.append(f"{where}: unknown route {effects.route}")

        def check_extras(where: str, extras: list[Extra]) -> None:
            for extra in extras:
                check_requirement(where, extra.requires)
                check_effects(where, extra.effects)

        for key in self.starting_evidence:
            if key not in evidence:
                problems.append(f"starting evidence: unknown evidence {key}")
        for location in self.locations:
            for spot in location.spots:
                check_requirement(f"spot {spot.key}", spot.requires)
                check_effects(f"spot {spot.key}", spot.effects)
        for character in self.characters:
            check_effects(f"character {character.key} on_silence", character.on_silence)
            for statement in character.statements:
                for key in statement.contradicted_by:
                    if key not in evidence:
                        problems.append(f"statement {statement.key}: unknown evidence {key}")
                if statement.on_break:
                    check_effects(f"statement {statement.key}", statement.on_break.effects)
                    check_extras(f"statement {statement.key}", statement.on_break.extras)
            for option in character.options:
                check_requirement(f"option {option.key}", option.requires)
                check_effects(f"option {option.key}", option.effects)
                check_extras(f"option {option.key}", option.extras)
            own = {s.key for s in character.statements}
            for option in character.options:
                for key in option.effects.breaks:
                    if key not in own:
                        problems.append(f"option {option.key} breaks another character's statement")
        for event in self.events:
            if event.speaker and event.speaker not in characters:
                problems.append(f"event {event.key}: unknown speaker {event.speaker}")
            check_requirement(f"event {event.key}", event.requires)
            check_effects(f"event {event.key}", event.effects)

        if self.mode == "deduction":
            problems.extend(self._deduction_problems(characters, evidence))
        else:
            problems.extend(self._scheme_problems(routes, check_requirement))
        if problems:
            raise ContentValidationError("; ".join(problems), case=self.key)
        return self

    def _deduction_problems(self, characters: set[str], evidence: set[str]) -> list[str]:
        problems: list[str] = []
        accusation, endings = self.accusation, self.endings
        if accusation is None or endings is None:
            return ["a deduction case needs an accusation and endings"]
        if accusation.culprit not in characters:
            problems.append(f"accusation culprit {accusation.culprit} is not a character")
        if accusation.weapon not in {w.key for w in accusation.weapons}:
            problems.append("accusation weapon is not one of the offered weapons")
        if accusation.motive not in {m.key for m in accusation.motives}:
            problems.append("accusation motive is not one of the offered motives")
        for pillar in accusation.pillars:
            for group in pillar.any_of:
                if len(group) > accusation.max_evidence:
                    problems.append(f"pillar {pillar.key} needs more evidence than may be presented")
                for key in group:
                    if key not in evidence:
                        problems.append(f"pillar {pillar.key}: unknown evidence {key}")
        suspects = {c.key for c in self.characters if c.suspect}
        for key in suspects - {accusation.culprit}:
            if key not in endings.wrong:
                problems.append(f"no wrong-accusation ending for suspect {key}")
        return problems

    def _scheme_problems(self, routes: set[str], check_requirement) -> list[str]:  # type: ignore[no-untyped-def]
        scheme = self.scheme
        if scheme is None:
            return ["a scheme case needs routes"]
        problems: list[str] = []
        if scheme.timeout_route not in routes:
            problems.append(f"unknown timeout route {scheme.timeout_route}")
        if not any(route.success for route in scheme.routes):
            problems.append("a scheme needs at least one winning route")
        for star in scheme.stars:
            check_requirement(f"star {star.key}", star.requires)
        triggered = {
            effects.route
            for effects in self._all_effects()
            if effects.route is not None
        } | {scheme.timeout_route}
        for route in routes - triggered:
            problems.append(f"route {route} can never be reached")
        return problems

    def _all_effects(self) -> list[Effects]:
        found: list[Effects] = []
        for location in self.locations:
            found.extend(spot.effects for spot in location.spots)
        for character in self.characters:
            found.append(character.on_silence)
            for statement in character.statements:
                if statement.on_break:
                    found.append(statement.on_break.effects)
                    found.extend(extra.effects for extra in statement.on_break.extras)
            for option in character.options:
                found.append(option.effects)
                found.extend(extra.effects for extra in option.extras)
        found.extend(event.effects for event in self.events)
        return found
