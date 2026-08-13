"""Low-cardinality Prometheus text metrics without a runtime dependency."""

from __future__ import annotations

from collections import defaultdict


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class HttpMetrics:
    def __init__(self) -> None:
        self.in_flight = 0
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)

    def start(self) -> None:
        self.in_flight += 1

    def observe(self, method: str, route: str, status: int, duration: float) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        key = (method, route)
        self.requests[(method, route, status)] += 1
        self.duration_sum[key] += duration
        self.duration_count[key] += 1

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
                "# TYPE narrative_http_request_duration_seconds summary",
            ]
        )
        for (method, route), total in sorted(self.duration_sum.items()):
            labels = f'method="{_escape(method)}",route="{_escape(route)}"'
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
        return "\n".join(lines) + "\n"


http_metrics = HttpMetrics()
