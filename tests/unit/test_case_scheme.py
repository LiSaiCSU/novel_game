"""Scheme cases: one goal, several authored wins, hidden variants, graded endings."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path

import pytest

from engine.case.engine import CaseEngine, Move, MoveRejected
from engine.case.library import load_cases
from engine.case.schema import Effects
from engine.case.state import CaseState
from engine.case.view import case_view

CASES_DIR = str(Path(__file__).resolve().parents[2] / "content" / "cases")


@pytest.fixture(scope="module")
def engine() -> CaseEngine:
    return CaseEngine(load_cases(CASES_DIR)["wedding_fifteen"])


def seed_for(engine: CaseEngine, **wanted: str) -> str:
    for index in range(500):
        seed = f"variant-{index}"
        variables = engine.new_state(seed).variables
        if all(variables[key] == value for key, value in wanted.items()):
            return seed
    raise AssertionError(f"no seed rolls {wanted}")


def play(engine: CaseEngine, seed: str, *moves: Move) -> CaseState:
    state = engine.new_state(seed)
    for move in (Move("begin"), *moves):
        state = engine.apply(state, move)
    return state


def _harmless(effects: Effects) -> bool:
    # Spending a scarce item is a choice between routes, not a safe step:
    # the red packet buys the lawyer or the emcee, never both.
    return (
        effects.route is None
        and effects.patience >= 0
        and not effects.remove_evidence
        and all(delta >= 0 for delta in effects.stance.values())
    )


def explore(engine: CaseEngine, seed: str) -> CaseState:
    """Do every safe thing an attentive player could do, ignoring the clock."""
    case = engine.case
    state = engine.apply(
        engine.new_state(seed).model_copy(update={"minutes_left": 10_000}), Move("begin")
    )
    progress = True
    while progress:
        progress = False
        for location in case.locations:
            for spot in location.spots:
                if (
                    spot.key not in state.examined
                    and _harmless(spot.effects)
                    and engine.requirement_met(state, spot.requires)
                ):
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
                if (
                    option.gamble is None
                    and _harmless(option.effects)
                    and engine.option_available(state, character, option)
                ):
                    state = engine.apply(state, Move("option", option.key))
                    progress = True
    return state


def route_openers(engine: CaseEngine, state: CaseState) -> set[str]:
    opened: set[str] = set()
    for location in engine.case.locations:
        for spot in location.spots:
            if spot.effects.route and engine.requirement_met(state, spot.requires):
                opened.add(spot.effects.route)
    for character in engine.case.characters:
        for option in character.options:
            if option.effects.route and engine.option_available(state, character, option):
                opened.add(option.effects.route)
    return opened


def test_every_variant_can_reach_every_winning_route(engine: CaseEngine) -> None:
    variables = engine.case.variables
    assert engine.case.scheme is not None
    winning = {route.key for route in engine.case.scheme.routes if route.success}
    for values in product(*(variable.options for variable in variables)):
        wanted = dict(zip((v.key for v in variables), values, strict=True))
        state = explore(engine, seed_for(engine, **wanted))
        assert state.status == "active", wanted
        opened = route_openers(engine, state)
        # Each scarce trade is a fork: spend it here and see what that opens.
        for character in engine.case.characters:
            for option in character.options:
                if option.effects.remove_evidence and engine.option_available(
                    state, character, option
                ):
                    forked = engine.apply(state, Move("option", option.key))
                    opened |= route_openers(engine, forked)
        assert opened >= winning, wanted


def test_hidden_variables_change_where_the_proof_is(engine: CaseEngine) -> None:
    rooms = play(engine, seed_for(engine, affair_proof="room_card"))
    phones = play(engine, seed_for(engine, affair_proof="phone"))
    room_spots = {s["key"] for loc in case_view(engine, rooms)["locations"] for s in loc["spots"]}
    phone_spots = {s["key"] for loc in case_view(engine, phones)["locations"] for s in loc["spots"]}
    assert "coat" in room_spots and "coat" not in phone_spots


def test_the_clean_run_earns_every_star(engine: CaseEngine) -> None:
    state = play(
        engine,
        seed_for(engine, affair_proof="room_card", lawyer="conscience"),
        Move("examine", "agreement"),
        Move("talk", "father"),
        Move("option", "fa_show"),
        Move("examine", "record"),
        Move("examine", "coat"),
        Move("talk", "groom"),
        Move("present", "gr_suwan", evidence="room_card"),
        Move("talk", "lawyer"),
        Move("present", "lw_routine", evidence="clause7"),
        Move("option", "lw_conscience_win"),
        Move("talk", "groom"),
        Move("option", "gr_force"),
    )
    assert state.status == "closed"
    assert state.result is not None
    assert state.result["route"] == "r_himself"
    assert state.result["grade"] == "S"
    assert all(star["met"] for star in state.result["stars"])


def test_order_matters_recording_must_start_first(engine: CaseEngine) -> None:
    seed = seed_for(engine, affair_proof="room_card")
    late = play(
        engine,
        seed,
        Move("examine", "coat"),
        Move("talk", "groom"),
        Move("present", "gr_suwan", evidence="room_card"),
        Move("examine", "record"),
    )
    assert "recording" not in late.evidence
    early = play(
        engine,
        seed,
        Move("examine", "record"),
        Move("examine", "coat"),
        Move("talk", "groom"),
        Move("present", "gr_suwan", evidence="room_card"),
    )
    assert "recording" in early.evidence


def test_quick_escape_wins_but_is_capped(engine: CaseEngine) -> None:
    state = play(engine, "escape", Move("examine", "escape"))
    assert state.result is not None
    assert state.result["solved"] and state.result["route"] == "r_escape"
    assert state.result["grade"] in {"B", "C"}


def test_father_signs_on_his_own_unless_warned(engine: CaseEngine) -> None:
    idle = play(engine, "clock", *[Move("think")] * 7)
    assert "father_signed" in idle.flags
    warned = play(
        engine, "clock", Move("talk", "father"), Move("option", "fa_stop"), *[Move("think")] * 7
    )
    assert "father_signed" not in warned.flags


def test_time_running_out_is_a_loss(engine: CaseEngine) -> None:
    state = play(engine, "late", *[Move("think")] * engine.case.minutes_total)
    assert state.result is not None
    assert state.result["route"] == "r_wedding"
    assert state.result["grade"] == "F"
    with pytest.raises(MoveRejected):
        engine.apply(state, Move("think"))


def test_rousing_the_groom_ends_the_scheme(engine: CaseEngine) -> None:
    state = play(
        engine,
        "careless",
        Move("talk", "groom"),
        Move("present", "gr_process", evidence="red_packet"),
        Move("present", "gr_process", evidence="red_packet"),
    )
    assert state.result is not None
    assert state.result["route"] == "r_calmed" and not state.result["solved"]


def test_wrong_read_of_the_lawyer_costs_patience(engine: CaseEngine) -> None:
    state = play(
        engine,
        seed_for(engine, lawyer="conscience"),
        Move("examine", "agreement"),
        Move("talk", "lawyer"),
        Move("present", "lw_routine", evidence="clause7"),
        Move("option", "lw_money_fail"),
    )
    assert "red_packet" in state.evidence  # he refused it
    assert state.patience["lawyer"] == engine.case.character("lawyer").patience - 2
    assert "original" not in state.evidence


def test_threatening_the_mother_backfires(engine: CaseEngine) -> None:
    state = play(engine, "threat", Move("talk", "mother"), Move("option", "mo_threat"))
    assert state.stance["mother"] == -2
    view = case_view(engine, state)
    assert "mo_cancel" not in {
        option["key"] for c in view["characters"] for option in c["options"]
    }


def test_trading_away_the_red_packet_spends_it(engine: CaseEngine) -> None:
    state = play(
        engine,
        seed_for(engine, affair_proof="phone"),
        Move("talk", "suwan"),
        Move("option", "sw_photo"),
        Move("talk", "emcee"),
        Move("option", "mc_bribe"),
    )
    assert "red_packet" not in state.evidence
    assert "emcee_ready" in state.flags


def test_view_hides_variables_and_undiscovered_routes(engine: CaseEngine) -> None:
    state = play(engine, seed_for(engine, affair_proof="necklace", lawyer="money"))
    view = case_view(engine, state, discovered={"r_mother"})
    text = json.dumps(view, ensure_ascii=False)
    assert "affair_proof" not in text and "necklace\"" not in text
    assert "r_screen" not in text and "r_mother" in text
    routes = view["scheme"]["routes"]
    assert sum(route["discovered"] for route in routes) == 1
    assert all(route["teaser"] for route in routes)
    assert view["accusation"] is None
    with pytest.raises(MoveRejected):
        engine.apply(state, Move("accuse", culprit="groom", weapon="x", motive="y"))
