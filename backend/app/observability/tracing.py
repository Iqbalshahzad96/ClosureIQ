"""
Workflow Tracing and Audit Trail
"""

from typing import Dict, Any, List
from datetime import datetime


class RunTracer:
    """Manages run traces and event sequences for explainability."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: List[Dict[str, Any]] = []

    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Append an event to the trace."""
        self.events.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "details": details
        })

    def get_trace(self) -> Dict[str, Any]:
        """Return the completed trace log."""
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": self.events
        }
