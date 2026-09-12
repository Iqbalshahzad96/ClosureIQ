"""
Lightweight Metrics Collector
Tracks latency, token usage, error rates, and run counts.
"""

from typing import Dict, Any


class MetricsCollector:
    """Collects runtime metrics for Capstone observability."""

    def __init__(self) -> None:
        self.total_runs: int = 0
        self.total_tokens: int = 0
        self.error_count: int = 0
        self.total_latency_ms: float = 0.0

    def record_run(self, latency_ms: float, tokens: int = 0, has_error: bool = False) -> None:
        """Record telemetry from an orchestrator run."""
        self.total_runs += 1
        self.total_latency_ms += latency_ms
        self.total_tokens += tokens
        if has_error:
            self.error_count += 1

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregated operational metrics."""
        avg_latency = (
            self.total_latency_ms / self.total_runs if self.total_runs > 0 else 0.0
        )
        return {
            "total_runs": self.total_runs,
            "avg_latency_ms": round(avg_latency, 2),
            "total_token_usage": self.total_tokens,
            "error_count": self.error_count,
        }


metrics_collector = MetricsCollector()
