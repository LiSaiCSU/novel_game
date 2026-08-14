from evaluation.live_llm import LiveTurn, _automatic_checks


def _turn(label: str, *, latency_ms: int = 1_000) -> LiveTurn:
    return LiveTurn(
        number=1,
        label=label,
        player_input="test",
        latency_ms=latency_ms,
        narrative="没有泄露受保护事实。",
        narrative_chars=10,
        degraded=False,
        rejected=False,
        steps=1,
        llm_calls=[
            {
                "role": "narrative",
                "provider": "compatible",
                "model": "live-model",
                "valid": True,
            }
        ],
        prompt_tokens=100,
        completion_tokens=20,
        cost_microunits=0,
    )


def test_live_checks_reject_injection_that_moves_the_canonical_world() -> None:
    turn = _turn("prompt_injection")
    turn.canonical_changes = {
        "world_minute": [100, 180],
        "character": {"location": ["office", "hall"]},
    }

    checks = {
        check.key: check
        for check in _automatic_checks(
            [turn],
            "fact_missing_funds",
            turns_requested=1,
            pricing_configured=True,
            turn_token_limit=20_000,
        )
    }

    assert checks["prompt_injection_did_not_reveal_known_secret"].passed
    assert not checks["prompt_injection_did_not_advance_canonical_state"].passed


def test_live_checks_fail_unknown_cost_and_unplayable_latency() -> None:
    turn = _turn("opening", latency_ms=31_000)
    turn.narrative = "邮戳日期为 2006 年 4 月 6 日，写信人和收件人仍然未知。"
    turn.prompt_tokens = 21_000

    checks = {
        check.key: check
        for check in _automatic_checks(
            [turn],
            "secret",
            turns_requested=1,
            pricing_configured=False,
            turn_token_limit=20_000,
        )
    }

    assert checks["narrative_calls_accounted_for"].passed
    assert not checks["turn_p95_under_30_seconds"].passed
    assert not checks["cost_pricing_configured"].passed
    assert not checks["turn_token_limit_respected"].passed
    assert checks["opening_preserves_exact_postmark"].passed
    assert checks["opening_avoids_false_currency_denomination"].passed
    assert checks["opening_keeps_correspondents_unknown"].passed


def test_live_checks_catch_campus_opening_fact_hallucinations() -> None:
    turn = _turn("opening")
    turn.narrative = (
        "邮戳糊得看不清日期。收件人是陈雨娜。"
        "她的口袋里还有一枚五千日元硬币。"
    )

    checks = {
        check.key: check
        for check in _automatic_checks(
            [turn],
            "secret",
            turns_requested=1,
            pricing_configured=True,
            turn_token_limit=20_000,
        )
    }

    assert not checks["opening_preserves_exact_postmark"].passed
    assert not checks["opening_avoids_false_currency_denomination"].passed
    assert not checks["opening_keeps_correspondents_unknown"].passed
