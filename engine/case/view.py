"""What the player is allowed to see.

The browser never receives which statements are lies, which evidence breaks
them, or the solution. It gets what Dr. Lin knows and the moves open to her.
"""

from __future__ import annotations

from typing import Any

from engine.case.engine import CaseEngine
from engine.case.schema import CaseDefinition
from engine.case.state import CaseState


def case_summary(case: CaseDefinition) -> dict[str, Any]:
    return {
        "key": case.key,
        "title": case.title,
        "tagline": case.tagline,
        "setting": case.setting,
        "estimated_minutes": case.estimated_minutes,
        "minutes_total": case.minutes_total,
        "suspects": len([c for c in case.characters if c.suspect]),
    }


def case_view(engine: CaseEngine, state: CaseState) -> dict[str, Any]:
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
        locations.append(
            {
                "key": location.key,
                "name": location.name,
                "description": location.description,
                "spots": spots,
            }
        )
    lies_total = len([s for c in case.characters for s in c.statements if s.lie])
    return {
        "case": {
            **case_summary(case),
            "goal": case.goal,
            "victim": case.victim,
            "action_minutes": case.action_minutes,
            "briefing": [page.model_dump() for page in case.briefing],
            "rules": [page.model_dump() for page in case.rules],
        },
        "status": state.status,
        "minutes_left": state.minutes_left,
        "current": state.current,
        "characters": characters,
        "locations": locations,
        "evidence": [
            case.evidence_item(key).model_dump() for key in state.evidence
        ],
        "log": [entry.model_dump() for entry in state.log],
        "progress": {
            "lies_broken": len(
                [key for key in state.broken if case.statement(key)[1].lie]
            ),
            "lies_total": lies_total,
            "evidence_found": len(state.evidence),
            "evidence_total": len(case.evidence),
        },
        "accusation": {
            "suspects": [
                {"key": c.key, "name": c.name, "role": c.role}
                for c in case.characters
                if c.suspect
            ],
            "weapons": [w.model_dump() for w in case.accusation.weapons],
            "motives": [m.model_dump() for m in case.accusation.motives],
            "max_evidence": case.accusation.max_evidence,
            "pillars": [p.label for p in case.accusation.pillars],
        },
        "result": state.result,
    }
