"""What the player is allowed to see.

The browser never receives which statements are lies, which evidence breaks
them, the rolled hidden variables, how routes are triggered, or the solution.
It gets what the player character knows and the moves open to them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from engine.case.engine import CaseEngine
from engine.case.schema import CaseDefinition
from engine.case.state import CaseState


def case_summary(case: CaseDefinition) -> dict[str, Any]:
    winning = [route for route in case.scheme.routes if route.success] if case.scheme else []
    return {
        "key": case.key,
        "mode": case.mode,
        "title": case.title,
        "tagline": case.tagline,
        "setting": case.setting,
        "estimated_minutes": case.estimated_minutes,
        "minutes_total": case.minutes_total,
        "suspects": len([c for c in case.characters if c.suspect]),
        "routes_total": len(winning),
    }


def case_view(
    engine: CaseEngine, state: CaseState, discovered: Iterable[str] = ()
) -> dict[str, Any]:
    case = engine.case
    characters = []
    for character in case.characters:
        met = character.key in state.met
        characters.append(
            {
                "key": character.key,
                "name": character.name,
                "role": character.role,
                "description": character.description,
                "suspect": character.suspect,
                "met": met,
                "silent": character.key in state.silent,
                "patience": state.patience.get(character.key, character.patience),
                "patience_max": character.patience,
                "stance": state.stance.get(character.key),
                "statements": [
                    {
                        "key": statement.key,
                        "text": statement.text,
                        "broken": statement.key in state.broken,
                    }
                    for statement in character.statements
                    if statement.key in state.statements
                ],
                "options": [
                    {"key": option.key, "kind": option.kind, "label": option.label}
                    for option in character.options
                    if engine.option_available(state, character, option)
                ]
                if state.status == "active"
                else [],
            }
        )
    locations = []
    for location in case.locations:
        spots = [
            {"key": spot.key, "label": spot.label, "examined": spot.key in state.examined}
            for spot in location.spots
            if spot.key in state.examined or engine.requirement_met(state, spot.requires)
        ]
        if spots:
            locations.append(
                {
                    "key": location.key,
                    "name": location.name,
                    "description": location.description,
                    "spots": spots,
                }
            )
    lies_total = len([s for c in case.characters for s in c.statements if s.lie])
    view: dict[str, Any] = {
        "case": {
            **case_summary(case),
            "goal": case.goal,
            "victim": case.victim,
            "clock_label": case.clock_label,
            "action_minutes": case.action_minutes,
            "briefing": [page.model_dump() for page in case.briefing],
            "rules": [page.model_dump() for page in case.rules],
        },
        "status": state.status,
        "minutes_left": state.minutes_left,
        "current": state.current,
        "characters": characters,
        "locations": locations,
        "evidence": [case.evidence_item(key).model_dump() for key in state.evidence],
        "log": [entry.model_dump() for entry in state.log],
        "progress": {
            "lies_broken": len([key for key in state.broken if case.statement(key)[1].lie]),
            "lies_total": lies_total,
            "evidence_found": len(state.evidence),
            "evidence_total": len(case.evidence),
        },
        "accusation": None,
        "scheme": None,
        "result": state.result,
    }
    if case.accusation is not None:
        view["accusation"] = {
            "suspects": [
                {"key": c.key, "name": c.name, "role": c.role} for c in case.characters if c.suspect
            ],
            "weapons": [w.model_dump() for w in case.accusation.weapons],
            "motives": [m.model_dump() for m in case.accusation.motives],
            "max_evidence": case.accusation.max_evidence,
            "pillars": [p.label for p in case.accusation.pillars],
        }
    if case.scheme is not None:
        found = set(discovered)
        if state.result and state.result.get("solved"):
            found.add(str(state.result.get("route")))
        view["scheme"] = {
            "stars": [star.label for star in case.scheme.stars],
            "routes": [
                {
                    "key": route.key if route.key in found else None,
                    "title": route.title if route.key in found else None,
                    "label": route.label if route.key in found else None,
                    "teaser": route.teaser,
                    "discovered": route.key in found,
                }
                for route in case.scheme.routes
                if route.success
            ],
        }
    return view
