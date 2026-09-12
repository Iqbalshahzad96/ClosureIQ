"""Concurrency-safe in-process workflow metrics."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Set


class MetricsCollector:
    """Collect workflow lifecycle metrics under one nonblocking asyncio lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tracked_runs: Set[str] = set()
        self._pending_runs: Set[str] = set()
        self._finalized_runs: Set[str] = set()
        self.total_runs = 0
        self.finalized_runs_count = 0
        self.total_tokens = 0
        self.error_count = 0
        self.total_latency_ms = 0.0
        self.hitl_approvals_count = 0
        self.approved_count = 0
        self.rejected_count = 0

    async def register_run(self, run_id: str) -> None:
        """Count a run ID once."""
        async with self._lock:
            if run_id not in self._tracked_runs:
                self._tracked_runs.add(run_id)
                self.total_runs += 1

    async def record_hitl_pending(self, run_id: str) -> None:
        """Mark a run pending without counting it again."""
        async with self._lock:
            if run_id not in self._tracked_runs:
                self._tracked_runs.add(run_id)
                self.total_runs += 1
            self._pending_runs.add(run_id)

    async def finalize_run(
        self,
        run_id: str,
        status: str,
        latency_ms: float = 0.0,
        tokens: int = 0,
        has_error: bool = False,
    ) -> None:
        """Record terminal metrics once for a run ID."""
        async with self._lock:
            if run_id not in self._tracked_runs:
                self._tracked_runs.add(run_id)
                self.total_runs += 1
            self._pending_runs.discard(run_id)
            if run_id in self._finalized_runs:
                return

            self._finalized_runs.add(run_id)
            self.finalized_runs_count += 1
            self.total_latency_ms += latency_ms
            self.total_tokens += tokens
            if has_error or status in ("error", "cancelled"):
                self.error_count += 1
            if status == "approved":
                self.hitl_approvals_count += 1
                self.approved_count += 1
            elif status == "rejected":
                self.rejected_count += 1

    async def get_summary(self) -> Dict[str, Any]:
        """Return an internally consistent metrics snapshot."""
        async with self._lock:
            avg_latency = (
                self.total_latency_ms / self.finalized_runs_count
                if self.finalized_runs_count
                else 0.0
            )
            return {
                "total_runs": self.total_runs,
                "avg_latency_ms": round(avg_latency, 2),
                "total_token_usage": self.total_tokens,
                "error_count": self.error_count,
                "hitl_approvals_count": self.hitl_approvals_count,
            }


metrics_collector = MetricsCollector()
