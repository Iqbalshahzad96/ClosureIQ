"""
WorkflowService: Production Orchestrator Integration Service

Wires the existing MCP tools, deterministic Financial Engine, ExceptionGenerator,
Agent 1, Policy RAG Retriever, Agent 2, and LangGraph HITL into production FastAPI workflows.

NOTE:
Pending workflows are held in the application-lifetime MemorySaver and do not
survive server restarts.
- ClosureIQ uses an in-memory MemorySaver checkpointer for the MVP.
- The service is explicitly designed and documented for single-process, single-worker execution (e.g. uvicorn --workers 1).
- Pending workflows are maintained in application memory and do not survive server restarts.
- Do not add a persistent checkpointer dependency in this branch.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Union

from fastapi import Request
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.database.database import SessionLocal
from app.database.models import ExceptionRecord
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.mcp.tools import FinancialMCPTools
from app.orchestrator.graph import build_financial_close_graph
from app.orchestrator.nodes import WorkflowDeps
from app.orchestrator.state import OrchestratorState
from app.rag.retriever import PolicyRetriever

logger = logging.getLogger("closureiq.workflow_service")

# Map exception categories to ChromaDB policy categories
RAG_CATEGORY_MAP: Dict[str, str] = {
    "RECONCILIATION": "BANK_RECONCILIATION",
    "ACCRUAL": "ACCRUAL",
    "DEPRECIATION": "DEPRECIATION",
}


class RunConflictError(Exception):
    """Raised when an operation conflicts with existing run state (HTTP 409)."""


class RunNotFoundError(Exception):
    """Raised when a run cannot be found (HTTP 404)."""


def _build_production_deps(
    session_factory: Callable[[], Session],
    mcp_tools: FinancialMCPTools,
    reconciliation_engine: ReconciliationEngine,
    accrual_engine: AccrualEngine,
    depreciation_engine: DepreciationEngine,
    exception_generator: ExceptionGenerator,
    financial_review_agent: FinancialReviewAgent,
    policy_retriever: PolicyRetriever,
    exception_analysis_agent: ExceptionAnalysisAgent,
) -> WorkflowDeps:
    """Construct real production WorkflowDeps binding existing components."""

    async def fetch_data(workflow_type: str, input_params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch data via MCP or validated input params."""
        if workflow_type == "reconciliation":
            account_code = input_params.get("account_code")
            if not account_code or not str(account_code).strip():
                raise ValueError("account_code is required for reconciliation workflow")
            limit = int(input_params.get("limit", 50))
            gl_records = await mcp_tools.query_gl_transactions(account_code=str(account_code), limit=limit)
            bank_records = await mcp_tools.query_bank_transactions(account_code=str(account_code), limit=limit)
            return {
                "account_code": account_code,
                "gl_transactions": gl_records,
                "bank_transactions": bank_records,
            }

        elif workflow_type == "accrual":
            accrual_entries = input_params.get("accrual_entries")
            historical_baseline = input_params.get("historical_baseline")
            if accrual_entries is None:
                raise ValueError("accrual_entries is required for accrual workflow")
            if historical_baseline is None:
                raise ValueError("historical_baseline is required for accrual workflow")
            return {
                "accrual_entries": accrual_entries,
                "historical_baseline": historical_baseline,
            }

        elif workflow_type == "depreciation":
            asset_records = input_params.get("asset_records")
            period_posted_depreciation = input_params.get("period_posted_depreciation")
            if asset_records is None:
                raise ValueError("asset_records is required for depreciation workflow")
            if period_posted_depreciation is None:
                raise ValueError("period_posted_depreciation is required for depreciation workflow")
            return {
                "asset_records": asset_records,
                "period_posted_depreciation": period_posted_depreciation,
            }

        else:
            raise ValueError(f"Unsupported workflow_type: {workflow_type}")

    async def run_validation(workflow_type: str, financial_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run deterministic financial math inside financial_engine."""
        if workflow_type == "reconciliation":
            gl = financial_data.get("gl_transactions", [])
            bank = financial_data.get("bank_transactions", [])
            return reconciliation_engine.reconcile(gl_transactions=gl, bank_transactions=bank)

        elif workflow_type == "accrual":
            accrual_entries = financial_data.get("accrual_entries", [])
            baseline = financial_data.get("historical_baseline", {})
            return accrual_engine.validate_accruals(
                accrual_entries=accrual_entries,
                historical_baseline=baseline,
            )

        elif workflow_type == "depreciation":
            assets = financial_data.get("asset_records", [])
            posted = financial_data.get("period_posted_depreciation", {})
            return depreciation_engine.validate_depreciation_schedule(
                asset_records=assets,
                period_posted_depreciation=posted,
            )

        else:
            raise ValueError(f"Unsupported workflow_type: {workflow_type}")

    async def detect_exceptions(
        workflow_type: str,
        validation_results: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[Dict[str, Any]]:
        """Generate structured exceptions and persist them to exception_records."""
        cat_map = {
            "reconciliation": "RECONCILIATION",
            "accrual": "ACCRUAL",
            "depreciation": "DEPRECIATION",
        }
        category = cat_map.get(workflow_type, "GENERAL")
        effective_period = period or "CURRENT"

        raw_exceptions = exception_generator.generate_exceptions(
            engine_output=validation_results,
            period=effective_period,
            category=category,
        )

        serialized: List[Dict[str, Any]] = []
        for exc in raw_exceptions:
            if hasattr(exc, "to_dict"):
                item = exc.to_dict()
            elif hasattr(exc, "model_dump"):
                item = exc.model_dump(mode="json")
            else:
                item = dict(exc)
            item["period"] = effective_period
            serialized.append(item)

        # Persist exceptions idempotently to existing exception_records table
        if session_factory is not None:
            db = session_factory()
            try:
                for item in serialized:
                    exc_id = item.get("id")
                    if not exc_id:
                        continue
                    existing = db.get(ExceptionRecord, exc_id)
                    if existing is None:
                        created_at_val = item.get("created_at")
                        if isinstance(created_at_val, str):
                            try:
                                dt = datetime.fromisoformat(created_at_val.replace("Z", "+00:00"))
                                if dt.tzinfo is not None:
                                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                            except Exception:
                                dt = datetime.utcnow()
                        elif isinstance(created_at_val, datetime):
                            dt = created_at_val
                        else:
                            dt = datetime.utcnow()

                        rec = ExceptionRecord(
                            id=exc_id,
                            period=item.get("period") or effective_period,
                            category=item.get("category", category),
                            severity=item.get("severity", "MEDIUM"),
                            amount_variance=float(item.get("amount_variance", 0.0)),
                            description=str(item.get("description", "")),
                            status=item.get("status", "OPEN"),
                            created_at=dt,
                        )
                        db.add(rec)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Exception persistence failed: %s", e)
                raise RuntimeError(f"Database persistence failed: {e}") from e
            finally:
                db.close()

        return serialized

    async def run_agent_1(exceptions: List[Dict[str, Any]], validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Agent 1 (Financial Review Agent)."""
        return await financial_review_agent.run_agent_1(exceptions, validation_results)

    async def retrieve_policies(exc: Dict[str, Any], agent_1_review: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve grounded accounting policy context for a single exception."""
        query = exc.get("description") or f"{exc.get('category', '')} exception"
        category = exc.get("category")
        mapped_cat = RAG_CATEGORY_MAP.get(category, category) if category else None

        # Attempt retrieval with mapped category filter
        evidence = await policy_retriever.retrieve_policy_context(
            query=query,
            top_k=3,
            category=mapped_cat,
        )

        # Fallback to unrestricted search if category-specific filter returned no evidence
        if not evidence and mapped_cat:
            evidence = await policy_retriever.retrieve_policy_context(
                query=query,
                top_k=3,
                category=None,
            )

        return evidence

    async def run_agent_2(
        exc: Dict[str, Any],
        agent_1_review: Dict[str, Any],
        matched_evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute Agent 2 (Exception Analysis Agent) for one exception."""
        return await exception_analysis_agent.run_agent_2(exc, agent_1_review, matched_evidence)

    async def log_event(event_type: str, details: Dict[str, Any]) -> None:
        """Log observability events."""
        logger.debug("Workflow event [%s]: %s", event_type, details)

    return WorkflowDeps(
        fetch_data=fetch_data,
        run_validation=run_validation,
        detect_exceptions=detect_exceptions,
        run_agent_1=run_agent_1,
        retrieve_policies=retrieve_policies,
        run_agent_2=run_agent_2,
        log_event=log_event,
    )


class WorkflowService:
    """Production workflow management service for ClosureIQ."""

    def __init__(
        self,
        session_factory: Optional[Callable[[], Session]] = None,
        mcp_tools: Optional[FinancialMCPTools] = None,
        reconciliation_engine: Optional[ReconciliationEngine] = None,
        accrual_engine: Optional[AccrualEngine] = None,
        depreciation_engine: Optional[DepreciationEngine] = None,
        exception_generator: Optional[ExceptionGenerator] = None,
        financial_review_agent: Optional[FinancialReviewAgent] = None,
        policy_retriever: Optional[PolicyRetriever] = None,
        exception_analysis_agent: Optional[ExceptionAnalysisAgent] = None,
        checkpointer: Optional[Any] = None,
        custom_deps: Optional[WorkflowDeps] = None,
    ) -> None:
        self.session_factory = session_factory or SessionLocal
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()

        # Wire dependencies if custom_deps is not provided
        if custom_deps is not None:
            self.deps = custom_deps
        else:
            _mcp = mcp_tools or FinancialMCPTools(session_factory=self.session_factory)
            _rec = reconciliation_engine or ReconciliationEngine()
            _acc = accrual_engine or AccrualEngine()
            _dep = depreciation_engine or DepreciationEngine()
            _exc = exception_generator or ExceptionGenerator()
            _a1 = financial_review_agent or FinancialReviewAgent()
            _rag = policy_retriever or PolicyRetriever()
            _a2 = exception_analysis_agent or ExceptionAnalysisAgent()

            self.deps = _build_production_deps(
                session_factory=self.session_factory,
                mcp_tools=_mcp,
                reconciliation_engine=_rec,
                accrual_engine=_acc,
                depreciation_engine=_dep,
                exception_generator=_exc,
                financial_review_agent=_a1,
                policy_retriever=_rag,
                exception_analysis_agent=_a2,
            )

        # Compile graph once with shared checkpointer
        self.graph = build_financial_close_graph(self.deps, checkpointer=self.checkpointer)

        # Track active runs and synchronization locks in memory
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._reserved_run_ids: Set[str] = set()
        self._reservation_lock = asyncio.Lock()
        self._run_locks: Dict[str, asyncio.Lock] = {}

    def _get_thread_config(self, run_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    async def _get_run_lock(self, run_id: str) -> asyncio.Lock:
        async with self._reservation_lock:
            if run_id not in self._run_locks:
                self._run_locks[run_id] = asyncio.Lock()
            return self._run_locks[run_id]

    async def start_workflow(
        self,
        workflow_type: str = "reconciliation",
        period: str = "CURRENT",
        input_params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a financial close workflow run with atomic run ID reservation."""
        effective_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

        # Atomically reserve unique run ID
        async with self._reservation_lock:
            if effective_run_id in self._reserved_run_ids or effective_run_id in self._runs:
                raise RunConflictError(
                    f"Run ID '{effective_run_id}' already exists or is currently in progress."
                )
            self._reserved_run_ids.add(effective_run_id)

        config = self._get_thread_config(effective_run_id)

        initial_state = OrchestratorState(
            run_id=effective_run_id,
            workflow_type=workflow_type,
            period=period,
            input_params=input_params or {},
        )

        try:
            result = await self.graph.ainvoke(initial_state, config=config)
        except Exception as exc:
            # Record failed state
            error_summary = {
                "run_id": effective_run_id,
                "workflow_type": workflow_type,
                "period": period,
                "status": "error",
                "validation_results": {},
                "exceptions_count": 0,
                "exceptions": [],
                "agent_1_review": {},
                "recommendations_count": 0,
                "recommendations": [],
                "errors": [str(exc)],
                "trace_log": [],
            }
            async with self._reservation_lock:
                self._runs[effective_run_id] = error_summary
            raise

        # Determine if paused at hitl_gate interrupt
        snapshot = await self.graph.aget_state(config)
        is_hitl_pending = bool(snapshot and snapshot.next and "hitl_gate" in snapshot.next)

        if is_hitl_pending:
            effective_status = "hitl_pending"
        else:
            effective_status = result.get("status", "error" if result.get("errors") else "completed")

        run_summary = {
            "run_id": effective_run_id,
            "workflow_type": workflow_type,
            "period": period,
            "status": effective_status,
            "validation_results": result.get("validation_results", {}),
            "exceptions_count": len(result.get("exceptions", [])),
            "exceptions": result.get("exceptions", []),
            "agent_1_review": result.get("agent_1_review", {}),
            "recommendations_count": len(result.get("recommendations", [])),
            "recommendations": result.get("recommendations", []),
            "errors": result.get("errors", []),
            "trace_log": result.get("trace_log", []),
        }

        async with self._reservation_lock:
            self._runs[effective_run_id] = run_summary

        return run_summary

    async def get_run_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve state for a given run ID from checkpointer or memory cache."""
        config = self._get_thread_config(run_id)
        snapshot = await self.graph.aget_state(config)

        if snapshot is None or not snapshot.values:
            async with self._reservation_lock:
                return self._runs.get(run_id)

        values = snapshot.values
        is_hitl_pending = bool(snapshot.next and "hitl_gate" in snapshot.next)
        status = "hitl_pending" if is_hitl_pending else values.get("status", "unknown")

        return {
            "run_id": run_id,
            "workflow_type": values.get("workflow_type", "reconciliation"),
            "period": values.get("period", ""),
            "status": status,
            "validation_results": values.get("validation_results", {}),
            "exceptions_count": len(values.get("exceptions", [])),
            "exceptions": values.get("exceptions", []),
            "agent_1_review": values.get("agent_1_review", {}),
            "recommendations_count": len(values.get("recommendations", [])),
            "recommendations": values.get("recommendations", []),
            "hitl_decision": values.get("hitl_decision", {}),
            "errors": values.get("errors", []),
            "trace_log": values.get("trace_log", []),
        }

    async def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """List all active runs currently paused at the HITL gate."""
        pending: List[Dict[str, Any]] = []

        async with self._reservation_lock:
            active_run_ids = list(self._runs.keys())

        for run_id in active_run_ids:
            config = self._get_thread_config(run_id)
            snapshot = await self.graph.aget_state(config)
            if snapshot and snapshot.next and "hitl_gate" in snapshot.next:
                values = snapshot.values
                pending.append({
                    "run_id": run_id,
                    "workflow_type": values.get("workflow_type", "reconciliation"),
                    "period": values.get("period", ""),
                    "exceptions_count": len(values.get("exceptions", [])),
                    "recommendations": values.get("recommendations", []),
                })

        return pending

    async def resume_decision(
        self,
        run_id: str,
        decision: str,
        reviewer: str = "",
        comments: str = "",
    ) -> Dict[str, Any]:
        """Resume a paused workflow with a human decision under a per-run lock."""
        # Normalize decision case-insensitively to "approved" or "rejected"
        normalized = str(decision).strip().lower()
        if normalized not in ("approved", "rejected"):
            raise ValueError(
                f"Invalid decision: '{decision}'. Expected 'approved' or 'rejected' (case-insensitive)."
            )

        run_lock = await self._get_run_lock(run_id)
        async with run_lock:
            config = self._get_thread_config(run_id)
            snapshot = await self.graph.aget_state(config)

            if snapshot is None or not snapshot.values:
                raise RunNotFoundError(f"Run ID '{run_id}' not found.")

            current_status = snapshot.values.get("status", "unknown")
            if not (snapshot.next and "hitl_gate" in snapshot.next):
                raise RunConflictError(
                    f"Run ID '{run_id}' has already completed with status '{current_status}' and cannot be resumed."
                )

            resume_payload = {
                "decision": normalized,
                "reviewer": reviewer,
                "comments": comments,
            }

            resumed_result = await self.graph.ainvoke(Command(resume=resume_payload), config=config)
            final_status = resumed_result.get("status", normalized)

            # Update cache
            async with self._reservation_lock:
                if run_id in self._runs:
                    self._runs[run_id]["status"] = final_status
                    self._runs[run_id]["hitl_decision"] = resume_payload
                    self._runs[run_id]["trace_log"] = resumed_result.get("trace_log", [])

            return {
                "run_id": run_id,
                "status": final_status,
                "decision": normalized,
                "reviewer": reviewer,
                "comments": comments,
            }


# ---------------------------------------------------------------------------
# FastAPI Dependency
# ---------------------------------------------------------------------------


def get_workflow_service(request: Request) -> WorkflowService:
    """Retrieve the singleton WorkflowService stored in app.state during lifespan."""
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        raise RuntimeError(
            "WorkflowService is not initialized on app.state. "
            "Ensure the application was started with its lifespan context manager."
        )
    return service
