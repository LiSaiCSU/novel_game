from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from engine.core.errors import LLMError, LLMTruncated
from engine.llm.failover import FailoverProvider, FailoverTarget
from engine.llm.provider import LLMMessage, LLMRequest, LLMResponse, LLMUsage


class Recorder:
    """A provider that either answers or raises, and remembers what it saw."""

    name = "recorder"
    available = True

    def __init__(self, *, fails: bool = False, fail_after: int | None = None) -> None:
        self.fails = fails
        self.fail_after = fail_after
        self.seen: list[LLMRequest] = []

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        self.seen.append(request)
        if self.fails:
            raise RuntimeError("endpoint down")
        return LLMResponse(text=f"ok:{request.model}", usage=LLMUsage(), latency_ms=1)

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        self.seen.append(request)
        if self.fails and self.fail_after is None:
            raise RuntimeError("endpoint down")
        for index, chunk in enumerate(["前半段", "后半段"]):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("endpoint died mid-stream")
            yield chunk


def _request(role: str = "narrative") -> LLMRequest:
    return LLMRequest(model="primary-model", messages=[LLMMessage(content="hi")], role=role)


async def test_moves_to_the_next_endpoint_and_uses_its_own_model_name() -> None:
    broken, spare = Recorder(fails=True), Recorder()
    provider = FailoverProvider(
        [
            FailoverTarget(broken, name="primary", models={"narrative": "big-model"}),
            FailoverTarget(spare, name="spare", models={"narrative": "gateway-model"}),
        ]
    )

    response = await provider.generate_text(_request())

    # The spare endpoint names the same capability differently, so replaying
    # the first endpoint's model name would have produced a 404 there.
    assert response.text == "ok:gateway-model"
    assert broken.seen[0].model == "big-model"
    assert spare.seen[0].model == "gateway-model"


async def test_each_role_picks_the_model_configured_for_it() -> None:
    endpoint = Recorder()
    provider = FailoverProvider(
        [
            FailoverTarget(
                endpoint,
                name="primary",
                models={"narrative": "prose-model", "director": "cheap-model"},
                default_model="prose-model",
            )
        ]
    )

    await provider.generate_text(_request("narrative"))
    await provider.generate_text(_request("director"))
    await provider.generate_text(_request("memory"))

    assert [item.model for item in endpoint.seen] == [
        "prose-model",
        "cheap-model",
        "prose-model",
    ]


async def test_reports_the_failure_when_no_endpoint_answers() -> None:
    provider = FailoverProvider(
        [
            FailoverTarget(Recorder(fails=True), name="a"),
            FailoverTarget(Recorder(fails=True), name="b"),
        ]
    )

    with pytest.raises(LLMError, match="every configured endpoint failed"):
        await provider.generate_text(_request())


async def test_streaming_fails_over_while_nothing_has_been_sent() -> None:
    broken, spare = Recorder(fails=True), Recorder()
    provider = FailoverProvider(
        [FailoverTarget(broken, name="primary"), FailoverTarget(spare, name="spare")]
    )

    chunks = [chunk async for chunk in provider.stream_text(_request())]

    assert chunks == ["前半段", "后半段"]


async def test_streaming_does_not_fail_over_once_the_player_has_seen_text() -> None:
    # Restarting here would splice two different continuations into one scene.
    dying, spare = Recorder(fail_after=1), Recorder()
    provider = FailoverProvider(
        [FailoverTarget(dying, name="primary"), FailoverTarget(spare, name="spare")]
    )

    chunks: list[str] = []
    with pytest.raises(RuntimeError, match="mid-stream"):
        async for chunk in provider.stream_text(_request()):
            chunks.append(chunk)

    assert chunks == ["前半段"]
    assert spare.seen == []


async def test_skips_endpoints_that_report_themselves_unavailable() -> None:
    missing_credential = Recorder()
    missing_credential.available = False
    spare = Recorder()
    provider = FailoverProvider(
        [
            FailoverTarget(missing_credential, name="unconfigured"),
            FailoverTarget(spare, name="spare", models={"narrative": "gateway-model"}),
        ]
    )

    response = await provider.generate_text(_request())

    assert response.text == "ok:gateway-model"
    assert missing_credential.seen == []


async def test_health_callback_sees_each_outcome() -> None:
    seen: list[tuple[str, bool]] = []
    provider = FailoverProvider(
        [
            FailoverTarget(Recorder(fails=True), name="primary"),
            FailoverTarget(Recorder(), name="spare"),
        ],
        on_result=lambda name, ok, _detail: seen.append((name, ok)),
    )

    await provider.generate_text(_request())

    assert seen == [("primary", False), ("spare", True)]


class Truncating:
    """An endpoint that answers HTTP 200 but spends the budget on hidden thought."""

    name = "truncating"
    available = True

    def __init__(self, *, succeed_at: int) -> None:
        self.succeed_at = succeed_at
        self.budgets: list[int] = []

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        self.budgets.append(request.max_output_tokens)
        if request.max_output_tokens < self.succeed_at:
            raise LLMTruncated("no usable content [finish_reason=length]")
        return LLMResponse(text="正文", usage=LLMUsage(), latency_ms=1)

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        self.budgets.append(request.max_output_tokens)
        if request.max_output_tokens < self.succeed_at:
            raise LLMTruncated("no usable content [finish_reason=length]")
        yield "正文"


async def test_a_truncated_answer_is_not_treated_as_a_broken_endpoint() -> None:
    # The client answers LLMTruncated by doubling the budget and asking again.
    # Failing over instead sends the same too-small budget somewhere else and
    # hides the signal, so the turn ends with no text despite HTTP 200s.
    primary, spare = Truncating(succeed_at=4096), Recorder()
    provider = FailoverProvider(
        [FailoverTarget(primary, name="primary"), FailoverTarget(spare, name="spare")]
    )

    with pytest.raises(LLMTruncated):
        await provider.generate_text(_request())

    assert spare.seen == []


async def test_streaming_also_lets_a_truncation_reach_the_budget_escalator() -> None:
    primary, spare = Truncating(succeed_at=4096), Recorder()
    provider = FailoverProvider(
        [FailoverTarget(primary, name="primary"), FailoverTarget(spare, name="spare")]
    )

    with pytest.raises(LLMTruncated):
        async for _chunk in provider.stream_text(_request()):
            pass

    assert spare.seen == []


async def test_the_chain_survives_a_budget_escalation_end_to_end() -> None:
    """The real path: client -> failover -> endpoint, with the retry intact."""
    from engine.core.config import Settings
    from engine.core.types import LLMRole
    from engine.llm.client import LLMClient
    from engine.llm.router import ModelRouter

    endpoint = Truncating(succeed_at=4096)
    provider = FailoverProvider([FailoverTarget(endpoint, name="primary")])
    settings = Settings(llm_model="prose-model", narrative_model="prose-model")
    client = LLMClient(
        provider, ModelRouter(settings), registry=None, truncation_retries=4
    )

    response = await client.generate_text(LLMRole.NARRATIVE, "写一段场景。")

    assert response.text == "正文"
    # Each retry doubles, which is what turns an empty answer into a scene.
    assert endpoint.budgets == sorted(endpoint.budgets)
    assert endpoint.budgets[-1] >= 4096
