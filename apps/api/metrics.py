"""Low-cardinality Prometheus text metrics without a runtime dependency."""

from __future__ import annotations

from collections import defaultdict


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class CommerceMetrics:
    """Low-cardinality billing and model-usage signals for the operator SLOs."""

    def __init__(self) -> None:
        self.reservations: dict[str, int] = defaultdict(int)
        self.settlements: dict[str, int] = defaultdict(int)
        self.credits_settled = 0
        self.llm_calls: dict[tuple[str, str], int] = defaultdict(int)
        self.llm_tokens: dict[str, int] = defaultdict(int)
        self.llm_cost_microunits: dict[str, int] = defaultdict(int)

    def reservation(self, outcome: str) -> None:
        self.reservations[outcome] += 1

    def settlement(self, outcome: str, credits: int) -> None:
        self.settlements[outcome] += 1
        self.credits_settled += max(0, credits)

    def llm_usage(
        self, *, provider: str, model: str, tokens: int, cost_microunits: int, success: bool
    ) -> None:
        # Provider and model are deployment-selected, bounded labels.  Never
        # attach user, prompt, story, payment or idempotency data to metrics.
        self.llm_calls[(provider or "unknown", "success" if success else "failed")] += 1
        self.llm_tokens[provider or "unknown"] += max(0, tokens)
        self.llm_cost_microunits[provider or "unknown"] += max(0, cost_microunits)

    def render(self) -> list[str]:
        lines = [
            "# HELP narrative_billing_turn_reservations_total Turn credit reservation attempts.",
            "# TYPE narrative_billing_turn_reservations_total counter",
        ]
        for outcome, count in sorted(self.reservations.items()):
            lines.append(
                f'narrative_billing_turn_reservations_total{{outcome="{_escape(outcome)}"}} {count}'
            )
        lines.extend(
            [
                "# HELP narrative_billing_turn_settlements_total Turn credit settlements.",
                "# TYPE narrative_billing_turn_settlements_total counter",
            ]
        )
        for outcome, count in sorted(self.settlements.items()):
            lines.append(
                f'narrative_billing_turn_settlements_total{{outcome="{_escape(outcome)}"}} {count}'
            )
        lines.extend(
            [
                "# HELP narrative_billing_credits_settled_total Narrative credits settled from turns.",
                "# TYPE narrative_billing_credits_settled_total counter",
                f"narrative_billing_credits_settled_total {self.credits_settled}",
                "# HELP narrative_llm_calls_total LLM calls by provider and final validity.",
                "# TYPE narrative_llm_calls_total counter",
            ]
        )
        for (provider, outcome), count in sorted(self.llm_calls.items()):
            labels = f'provider="{_escape(provider)}",outcome="{_escape(outcome)}"'
            lines.append(f"narrative_llm_calls_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP narrative_llm_tokens_total LLM tokens recorded by provider.",
                "# TYPE narrative_llm_tokens_total counter",
            ]
        )
        for provider, tokens in sorted(self.llm_tokens.items()):
            lines.append(f'narrative_llm_tokens_total{{provider="{_escape(provider)}"}} {tokens}')
        lines.extend(
            [
                "# HELP narrative_llm_cost_microunits_total LLM cost in deployment microunits.",
                "# TYPE narrative_llm_cost_microunits_total counter",
            ]
        )
        for provider, cost in sorted(self.llm_cost_microunits.items()):
            lines.append(
                f'narrative_llm_cost_microunits_total{{provider="{_escape(provider)}"}} {cost}'
            )
        return lines


class HttpMetrics:
    _DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)

    def __init__(self) -> None:
        self.in_flight = 0
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)

    def start(self) -> None:
        self.in_flight += 1

    def observe(self, method: str, route: str, status: int, duration: float) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        key = (method, route)
        self.requests[(method, route, status)] += 1
        self.duration_sum[key] += duration
        self.duration_count[key] += 1
        for bound in self._DURATION_BUCKETS:
            if duration <= bound:
                self.duration_buckets[(method, route, bound)] += 1
        # Prometheus histogram buckets are cumulative; +Inf must include
        # every observed request, even a pathological slow one.
        self.duration_buckets[(method, route, float("inf"))] += 1

    def render(self) -> str:
        lines = [
            "# HELP narrative_http_requests_total Completed HTTP requests.",
            "# TYPE narrative_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(self.requests.items()):
            labels = f'method="{_escape(method)}",route="{_escape(route)}",status="{status}"'
            lines.append(f"narrative_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP narrative_http_request_duration_seconds Request duration by route.",
                "# TYPE narrative_http_request_duration_seconds histogram",
            ]
        )
        duration_keys = sorted(self.duration_sum)
        for method, route in duration_keys:
            labels = f'method="{_escape(method)}",route="{_escape(route)}"'
            for bound in (*self._DURATION_BUCKETS, float("inf")):
                le = "+Inf" if bound == float("inf") else f"{bound:g}"
                bucket_labels = f'{labels},le="{le}"'
                lines.append(
                    "narrative_http_request_duration_seconds_bucket"
                    f"{{{bucket_labels}}} {self.duration_buckets[(method, route, bound)]}"
                )
            total = self.duration_sum[(method, route)]
            lines.append(f"narrative_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
            lines.append(
                f"narrative_http_request_duration_seconds_count{{{labels}}} "
                f"{self.duration_count[(method, route)]}"
            )
        lines.extend(
            [
                "# HELP narrative_http_requests_in_flight Current HTTP requests.",
                "# TYPE narrative_http_requests_in_flight gauge",
                f"narrative_http_requests_in_flight {self.in_flight}",
            ]
        )
        lines.extend(commerce_metrics.render())
        return "\n".join(lines) + "\n"


commerce_metrics = CommerceMetrics()
http_metrics = HttpMetrics()
