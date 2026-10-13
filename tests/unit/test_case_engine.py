"""Deduction cases: authored content stays solvable, rules stay deterministic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.case.engine import CaseEngine, Move, MoveRejected
from engine.case.library import load_cases
from engine.case.state import CaseState
from engine.case.view import case_view

CASES_DIR = str(Path(__file__).resolve().parents[2] / "content" / "cases")


@pytest.fixture(scope="module")
def engine() -> CaseEngine:
    return CaseEngine(load_cases(CASES_DIR)["egret_purser"])


def play(engine: CaseEngine, *moves: Move, seed: str = "test") -> CaseState:
    state = engine.new_state(seed)
    for move in (Move("begin"), *moves):
        state = engine.apply(state, move)
    return state


GOLDEN = (
    Move("examine", "body"),
    Move("examine", "safe"),
    Move("examine", "brazier"),
    Move("examine", "floor"),
    Move("examine", "cards"),
    Move("examine", "log"),
    Move("talk", "han"),
    Move("present", "hz_bridge", evidence="log_hand"),
    Move("option", "hz_ask_seen"),
    Move("talk", "song"),
    Move("present", "sb_cards", evidence="score_sheet"),
    Move("present", "sb_deck", evidence="cigar_ash"),
    Move("present", "sb_left", evidence="t_song_seen"),
)


def test_every_authored_case_loads() -> None:
    cases = load_cases(CASES_DIR)
    assert "egret_purser" in cases
    for case in cases.values():
        assert case.briefing and case.rules
        assert any(c.suspect for c in case.characters)


def test_golden_path_reaches_the_truth(engine: CaseEngine) -> None:
    state = play(
        engine,
        *GOLDEN,
        Move(
            "accuse",
            culprit="song",
            weapon="cane",
            motive="fraud",
            exhibits=("t_song_seen", "wound", "cane", "burnt_scrap", "insurance"),
        ),
    )
    assert state.status == "closed"
    assert state.result is not None
    assert state.result["ending"] == "truth"
    assert all(pillar["met"] for pillar in state.result["pillars"])
    # Cornering the culprit silences him but hands over the weapon detail.
    assert "song" in state.silent
    assert "cane" in state.evidence


def test_each_action_costs_time_but_talking_does_not(engine: CaseEngine) -> None:
    state = play(engine, Move("talk", "song"))
    assert state.minutes_left == engine.case.minutes_total
    state = engine.apply(state, Move("examine", "body"))
    assert state.minutes_left == engine.case.minutes_total - engine.case.action_minutes


def test_wrong_evidence_costs_patience_until_silence(engine: CaseEngine) -> None:
    state = play(engine, Move("examine", "body"), Move("talk", "zhou"))
    for _ in range(engine.case.character("zhou").patience):
        state = engine.apply(state, Move("present", "zy_home", evidence="wound"))
    assert state.patience["zhou"] == 0
    assert "zhou" in state.silent
    assert "zy_home" not in state.broken
    with pytest.raises(MoveRejected):
        engine.apply(state, Move("present", "zy_home", evidence="wound"))
    assert case_view(engine, state)["characters"][1]["options"] == []


def test_cannot_present_evidence_not_in_hand(engine: CaseEngine) -> None:
    state = play(engine, Move("talk", "xiaoshun"))
    with pytest.raises(MoveRejected):
        engine.apply(state, Move("present", "xs_untouched", evidence="watch_chain"))


def test_breaking_a_lie_reveals_new_testimony(engine: CaseEngine) -> None:
    state = play(engine, Move("examine", "desk"), Move("talk", "zhou"))
    assert "zy_corridor" not in state.statements
    state = engine.apply(state, Move("present", "zy_home", evidence="two_cups"))
    assert "zy_home" in state.broken
    assert {"zy_alive", "zy_corridor"} <= set(state.statements)
    assert "t_cane_sound" in state.evidence


def test_leverage_breaks_a_lie_but_leaves_a_mark(engine: CaseEngine) -> None:
    state = play(
        engine, Move("examine", "safe"), Move("examine", "safe_drawer"), Move("talk", "zhou")
    )
    state = engine.apply(state, Move("option", "zy_press_ticket"))
    assert "zy_home" in state.broken
    assert "exposed_zhou" in state.flags
    assert state.patience["zhou"] == engine.case.character("zhou").patience - 1


def test_bluff_is_seeded_and_both_outcomes_exist(engine: CaseEngine) -> None:
    outcomes = {}
    for seed in (f"seed-{index}" for index in range(40)):
        state = play(engine, Move("talk", "han"), Move("option", "hz_bluff_ma"), seed=seed)
        again = play(engine, Move("talk", "han"), Move("option", "hz_bluff_ma"), seed=seed)
        assert state.broken == again.broken
        outcomes["hz_bridge" in state.broken] = state
    assert set(outcomes) == {True, False}
    failed = outcomes[False]
    assert failed.patience["han"] == engine.case.character("han").patience - 2
    assert "hz_bluff_ma" in failed.used_options


def test_deadline_leaves_only_the_accusation(engine: CaseEngine) -> None:
    state = play(engine)
    for _ in range(engine.case.minutes_total // engine.case.action_minutes):
        state = engine.apply(state, Move("think"))
    assert state.status == "deadline"
    assert {event.key for event in engine.case.events} <= set(state.fired_events)
    with pytest.raises(MoveRejected):
        engine.apply(state, Move("examine", "body"))
    state = engine.apply(
        state, Move("accuse", culprit="xiaoshun", weapon="tongs", motive="robbery")
    )
    assert state.result is not None and state.result["ending"] == "wrong:xiaoshun"


def test_right_culprit_without_proof_escapes(engine: CaseEngine) -> None:
    state = play(engine, Move("accuse", culprit="song", weapon="cane", motive="fraud"))
    assert state.result is not None and state.result["ending"] == "escaped"
    assert [entry.kind for entry in state.log[-3:]] == ["npc", "npc", "npc"]


def test_wrong_weapon_fails_the_means_pillar(engine: CaseEngine) -> None:
    state = play(
        engine,
        *GOLDEN,
        Move(
            "accuse",
            culprit="song",
            weapon="paperweight",
            motive="fraud",
            exhibits=("t_song_seen", "wound", "cane", "burnt_scrap", "insurance"),
        ),
    )
    assert state.result is not None and state.result["ending"] == "partial"
    assert {p["key"]: p["met"] for p in state.result["pillars"]}["means"] is False


def test_epilogue_remembers_what_the_player_traded(engine: CaseEngine) -> None:
    state = play(
        engine,
        Move("examine", "safe"),
        Move("examine", "safe_drawer"),
        Move("talk", "zhou"),
        Move("option", "zy_press_ticket"),
        Move("accuse", culprit="song", weapon="cane", motive="fraud"),
    )
    assert state.result is not None
    assert any("借据" in text for text in state.result["epilogues"])


def test_view_never_leaks_the_solution(engine: CaseEngine) -> None:
    state = play(engine, Move("talk", "song"), Move("examine", "cards"))
    view = json.dumps(case_view(engine, state), ensure_ascii=False)
    for secret in ("contradicted_by", '"lie"', "on_break", "沈墨卿那个死脑筋", "生丝掉包骗保，被账房查了出来\", \"correct"):
        assert secret not in view
    # Statements appear only once they have been said.
    assert engine.case.statement("sb_left")[1].text not in view
    assert engine.case.statement("sb_cards")[1].text in view
    assert '"solution"' not in view and '"culprit": "song"' not in view


def test_hint_points_at_a_breakable_lie(engine: CaseEngine) -> None:
    state = play(engine, Move("examine", "cards"), Move("talk", "song"), Move("think"))
    assert engine.case.statement("sb_cards")[1].text in state.log[-1].text


def test_case_is_solvable_by_exhaustive_honest_play(engine: CaseEngine) -> None:
    """Every evidence item is reachable and the truth needs nothing hidden."""
    case = engine.case
    state = engine.apply(engine.new_state("explore").model_copy(update={"minutes_left": 10_000}), Move("begin"))
    progress = True
    while progress:
        progress = False
        for location in case.locations:
            for spot in location.spots:
                if spot.key not in state.examined and engine.requirement_met(state, spot.requires):
                    state = engine.apply(state, Move("examine", spot.key))
                    progress = True
        for character in case.characters:
            state = engine.apply(state, Move("talk", character.key))
            for statement in character.statements:
                if statement.key in engine.challengeable(state, character):
                    held = [key for key in statement.contradicted_by if key in state.evidence]
                    if held:
                        state = engine.apply(state, Move("present", statement.key, evidence=held[0]))
                        progress = True
            for option in character.options:
                if option.kind == "ask" and engine.option_available(state, character, option):
                    state = engine.apply(state, Move("option", option.key))
                    progress = True
    missing = {item.key for item in case.evidence} - set(state.evidence)
    for pillar in case.accusation.pillars:
        assert any(set(group) <= set(state.evidence) for group in pillar.any_of), pillar.key
    # What honest play can miss: what only pressing reveals, and what is lost
    # by cornering the culprit before asking him everything.
    assert missing <= {"t_song_slip", "wet_sleeve", "t_song_buyer"}
    lies = {s.key for c in case.characters for s in c.statements if s.lie}
    assert lies <= set(state.broken)
