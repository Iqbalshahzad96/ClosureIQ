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

Cancellation Semantics & MVP Boundaries:
- Asynchronous task cancellations preserve and re-raise asyncio.CancelledError.
- Cleanups are bounded with a 5.0-second timeout to prevent indefinite hangs.
- This single-process MVP does not guarantee audit record persistence during hard
  process kills (SIGKILL / taskkill / unhandled OS termination) or abrupt runtime shutdowns.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from fastapi import Request
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import NodeCancelledError
from langgraph.types import Command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.database.database import SessionLocal
from app.database.models import AuditTrailRecord, ExceptionRecord
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.mcp.tools import FinancialMCPTools
from app.observability.metrics import MetricsCollector
from app.observability.tracing import format_run_trace
from app.orchestrator.graph import build_financial_close_graph
from app.orchestrator.nodes import WorkflowDeps, normalize_json_safe
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


class ObservabilityStorageError(Exception):
    """Raised when an underlying database read or write fails during observability operations.

    To protect against sensitive data leakage (credentials, connection strings, SQL queries,
    file paths), all public exception messages are generic: 'Observability storage unavailable'.
    Underlying raw exceptions must only be preserved as chained causes (__cause__) and logged
    securely to server logs.
    """

    DEFAULT_MESSAGE = "Observability storage unavailable"

    def __init__(self, message: str = DEFAULT_MESSAGE) -> None:
        super().__init__(self.DEFAULT_MESSAGE)


def canonicalize_details(details: Any) -> str:
    """Canonically normalize details dictionary/payload to a sorted, compact JSON string.

    Handles:
    - None -> empty dict
    - JSON-encoded strings -> parsed to Python structures first
    - normalize_json_safe for numbers, dates, UUIDs, decimals, models
    - Recursively sorts dictionary keys via sort_keys=True
    - Strips extraneous whitespace via separators=(',', ':')
    """
    if details is None:
        details = {}
    elif isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            pass
    safe = normalize_json_safe(details)
    return json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_current_mcp_calls: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "_current_mcp_calls", default=None
)


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
        """Fetch input data and record only MCP calls that actually execute."""
        if workflow_type == "reconciliation":
            account_code = input_params.get("account_code")
            if not account_code or not str(account_code).strip():
                raise ValueError("account_code is required for reconciliation workflow")
            account_code = str(account_code)
            limit = int(input_params.get("limit", 50))
            run_calls = _current_mcp_calls.get()
            local_calls: List[Dict[str, Any]] = []

            async def invoke(tool_name: str, operation: Callable[..., Awaitable[List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
                started = time.monotonic()
                try:
                    records = await operation(account_code=account_code, limit=limit)
                except Exception as exc:
                    event = {
                        "node": "fetch_data",
                        "workflow_type": workflow_type,
                        "tool": tool_name,
                        "status": "error",
                        "latency_ms": round((time.monotonic() - started) * 1000, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "parameters": {"account_code": account_code, "limit": limit},
                        "records_fetched": 0,
                        "error": str(exc),
                    }
                    local_calls.append(event)
                    if run_calls is not None:
                        run_calls.append(event)
                    raise
                event = {
                    "node": "fetch_data",
                    "workflow_type": workflow_type,
                    "tool": tool_name,
                    "status": "success",
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "parameters": {"account_code": account_code, "limit": limit},
                    "records_fetched": len(records),
                    "error": None,
                }
                local_calls.append(event)
                if run_calls is not None:
                    run_calls.append(event)
                return records

            gl_records = await invoke("query_gl_transactions", mcp_tools.query_gl_transactions)
            bank_records = await invoke("query_bank_transactions", mcp_tools.query_bank_transactions)
            return {
                "account_code": account_code,
                "gl_transactions": gl_records,
                "bank_transactions": bank_records,
                "mcp_calls": local_calls,
            }

        if workflow_type == "accrual":
            accrual_entries = input_params.get("accrual_entries")
            historical_baseline = input_params.get("historical_baseline")
            if accrual_entries is None:
                raise ValueError("accrual_entries is required for accrual workflow")
            if historical_baseline is None:
                raise ValueError("historical_baseline is required for accrual workflow")
            return {
                "accrual_entries": accrual_entries,
                "historical_baseline": historical_baseline,
                "mcp_calls": [],
            }

        if workflow_type == "depreciation":
            asset_records = input_params.get("asset_records")
            period_posted_depreciation = input_params.get("period_posted_depreciation")
            if asset_records is None:
                raise ValueError("asset_records is required for depreciation workflow")
            if period_posted_depreciation is None:
                raise ValueError("period_posted_depreciation is required for depreciation workflow")
            return {
                "asset_records": asset_records,
                "period_posted_depreciation": period_posted_depreciation,
                "mcp_calls": [],
            }

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
            committed = False
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
                committed = True
            except Exception as e:
                db.rollback()
                logger.error("Exception persistence failed: %s", e)
                raise RuntimeError(f"Database persistence failed: {e}") from e
            finally:
                if not committed:
                    try:
                        db.rollback()
                    except Exception:
                        pass
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
        metrics_collector: Optional[MetricsCollector] = None,
    ) -> None:
        self.session_factory = session_factory or SessionLocal
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self.metrics_collector = metrics_collector or MetricsCollector()

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

        # In-memory state is only a live-service cache. The database reservation
        # record is the authority for run ID uniqueness across service instances.
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._reservation_lock = asyncio.Lock()
        self._run_locks: Dict[str, asyncio.Lock] = {}

    def _get_thread_config(self, run_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    async def _get_run_lock(self, run_id: str) -> asyncio.Lock:
        async with self._reservation_lock:
            if run_id not in self._run_locks:
                self._run_locks[run_id] = asyncio.Lock()
            return self._run_locks[run_id]

    @staticmethod
    def _rollback(db: Session, operation: str) -> None:
        try:
            db.rollback()
        except Exception as exc:
            logger.error("Failed to roll back %s: %s", operation, exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc

    @staticmethod
    def _close(db: Session, operation: str) -> None:
        try:
            db.close()
        except Exception as exc:
            logger.error("Failed to close session after %s: %s", operation, exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc

    def _reserve_run_id(
        self,
        run_id: str,
        workflow_type: str,
        period: str,
        input_params: Dict[str, Any],
        created_at: datetime,
    ) -> None:
        """Atomically reserve a run with the immutable RUN_STARTED record."""
        if self.session_factory is None:
            logger.error("Database session factory is unavailable")
            raise ObservabilityStorageError("Observability storage unavailable")
        try:
            db = self.session_factory()
        except Exception as exc:
            logger.error("Failed to open database session: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        committed = False
        try:
            db.add(
                AuditTrailRecord(
                    id=f"{run_id}_RUN_STARTED",
                    run_id=run_id,
                    event_type="RUN_STARTED",
                    details=normalize_json_safe(
                        {
                            "run_id": run_id,
                            "workflow_type": workflow_type,
                            "period": period,
                            "input_params": input_params,
                            "status": "running",
                            "created_at": created_at.isoformat(),
                        }
                    ),
                    created_at=created_at.replace(tzinfo=None),
                )
            )
            db.commit()
            committed = True
        except IntegrityError as exc:
            self._rollback(db, "run reservation")
            raise RunConflictError(f"Run ID '{run_id}' already exists.") from exc
        except Exception as exc:
            self._rollback(db, "run reservation")
            logger.error("Failed to reserve run ID: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        finally:
            if not committed:
                try:
                    self._rollback(db, "run reservation")
                except Exception:
                    pass
            self._close(db, "run reservation")

    def _persist_audit_event(
        self,
        record_id: str,
        run_id: str,
        event_type: str,
        details: Dict[str, Any],
    ) -> None:
        """Persist an audit trail record idempotently, JSON-safely, and rollback on error.
        Existing records are immutable and are never overwritten.
        Identical identity and identical normalized payload = idempotent success.
        Identical identity but different payload = RunConflictError (HTTP 409).
        """
        if self.session_factory is None:
            logger.error("Database session factory is unavailable")
            raise ObservabilityStorageError("Observability storage unavailable")
        try:
            db = self.session_factory()
        except Exception as exc:
            logger.error("Failed to open database session: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        committed = False
        try:
            safe_details = normalize_json_safe(details)
            incoming_canonical = canonicalize_details(safe_details)
            existing = db.get(AuditTrailRecord, record_id)
            if existing is None:
                rec = AuditTrailRecord(
                    id=record_id,
                    run_id=run_id,
                    event_type=event_type,
                    details=safe_details,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(rec)
                db.commit()
                committed = True
            else:
                if existing.run_id != run_id or existing.event_type != event_type:
                    raise RunConflictError(
                        f"Audit record conflict for '{record_id}': existing identity ({existing.run_id}, {existing.event_type}) conflicts with incoming ({run_id}, {event_type})"
                    )
                logger.debug("Audit record %s already exists; checking payload identity", record_id)
                existing_canonical = canonicalize_details(existing.details)
                if incoming_canonical != existing_canonical:
                    raise RunConflictError(
                        f"Audit record conflict for '{record_id}': incoming details conflict with existing details"
                    )
                logger.debug("Audit record %s already exists with identical payload; preserving existing content", record_id)
        except IntegrityError as exc:
            self._rollback(db, "audit write")
            try:
                existing = db.get(AuditTrailRecord, record_id)
            except Exception as read_exc:
                logger.error("Failed to verify concurrent audit write: %s", read_exc, exc_info=True)
                raise ObservabilityStorageError("Observability storage unavailable") from read_exc
            if (
                existing is not None
                and existing.run_id == run_id
                and existing.event_type == event_type
            ):
                if canonicalize_details(existing.details) == incoming_canonical:
                    return
                raise RunConflictError(
                    f"Audit record conflict for '{record_id}': incoming details conflict with existing details"
                ) from exc
            raise RunConflictError(
                f"Audit record conflict for '{record_id}': concurrent write conflict"
            ) from exc
        except (RunConflictError, ObservabilityStorageError):
            raise
        except Exception as e:
            self._rollback(db, "audit write")
            logger.error("Audit trail persistence failed: %s", e, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from e
        finally:
            if not committed:
                try:
                    self._rollback(db, "audit write")
                except Exception:
                    pass
            self._close(db, "audit write")

    async def _safe_record_cancellation(
        self,
        run_id: str,
        workflow_type: str,
        period: str,
        input_params: Dict[str, Any],
        created_at_iso: str,
        elapsed_ms: float,
        cached_data: Optional[Dict[str, Any]] = None,
        mcp_log: Optional[List[Dict[str, Any]]] = None,
        hitl_decision: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Atomically persist a terminal cancelled snapshot and finalize metrics exactly once."""
        base = dict(cached_data or {})
        fin_data = base.get("financial_data") or {}
        if mcp_log and isinstance(fin_data, dict) and not fin_data.get("mcp_calls"):
            fin_data = {**fin_data, "mcp_calls": list(mcp_log)}

        cancelled_summary = normalize_json_safe({
            **base,
            "run_id": run_id,
            "workflow_type": base.get("workflow_type", workflow_type),
            "period": base.get("period", period),
            "status": "cancelled",
            "total_latency_ms": elapsed_ms,
            "validation_results": base.get("validation_results", {}),
            "exceptions_count": base.get("exceptions_count", len(base.get("exceptions", []))),
            "exceptions": base.get("exceptions", []),
            "agent_1_review": base.get("agent_1_review", {}),
            "agent_2_analyses": base.get("agent_2_analyses", []),
            "policy_contexts": base.get("policy_contexts", []),
            "recommendations_count": base.get("recommendations_count", len(base.get("recommendations", []))),
            "recommendations": base.get("recommendations", []),
            "financial_data": fin_data,
            "input_params": base.get("input_params") or input_params,
            "hitl_decision": hitl_decision or base.get("hitl_decision", {}),
            "errors": list(base.get("errors", [])) + ["Workflow execution was cancelled"],
            "trace_log": base.get("trace_log", []),
            "created_at": created_at_iso,
        })

        try:
            await asyncio.to_thread(
                self._persist_audit_event,
                f"{run_id}_RUN_ERROR",
                run_id,
                "RUN_ERROR",
                cancelled_summary,
            )
        except RunConflictError as exc:
            logger.warning("Audit record %s_RUN_ERROR conflict during cancellation: %s", run_id, exc)
            raise
        except Exception as exc:
            logger.error("Failed to persist cancellation audit record for %s: %s", run_id, exc, exc_info=True)
            raise

        async with self._reservation_lock:
            self._runs[run_id] = cancelled_summary

        await self.metrics_collector.finalize_run(
            run_id=run_id,
            status="cancelled",
            latency_ms=elapsed_ms,
            tokens=0,
            has_error=True,
        )

    async def start_workflow(
        self,
        workflow_type: str = "reconciliation",
        period: str = "CURRENT",
        input_params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a workflow only after a successful database-backed reservation."""
        effective_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        created_at_dt = datetime.now(timezone.utc)
        created_at_iso = created_at_dt.isoformat()

        # A per-run lock avoids redundant same-instance work. The database insert,
        # not memory state, remains the sole source of reservation conflicts.
        run_lock = await self._get_run_lock(effective_run_id)
        async with run_lock:
            await asyncio.to_thread(
                self._reserve_run_id,
                effective_run_id,
                workflow_type,
                period,
                input_params or {},
                created_at_dt,
            )

        await self.metrics_collector.register_run(effective_run_id)
        config = self._get_thread_config(effective_run_id)
        initial_state = OrchestratorState(
            run_id=effective_run_id,
            workflow_type=workflow_type,
            period=period,
            input_params=input_params or {},
        )

        current_mcp_log: List[Dict[str, Any]] = []
        token = _current_mcp_calls.set(current_mcp_log)
        t_start = time.monotonic()
        terminal_recorded = False
        try:
            try:
                result = await self.graph.ainvoke(initial_state, config=config)

                # Determine if paused at hitl_gate interrupt
                snapshot = await self.graph.aget_state(config)
                is_hitl_pending = bool(snapshot and snapshot.next and "hitl_gate" in snapshot.next)

                if is_hitl_pending:
                    effective_status = "hitl_pending"
                else:
                    effective_status = result.get("status", "error" if result.get("errors") else "completed")

                trace_log = result.get("trace_log", [])
                sum_latency = sum(float(e.get("latency_ms", 0.0)) for e in trace_log if isinstance(e, dict))
                wall_latency = (time.monotonic() - t_start) * 1000
                total_latency = round(sum_latency, 2) if sum_latency > 0 else round(wall_latency, 2)

                fin_data = result.get("financial_data") or {}
                if isinstance(fin_data, dict) and not fin_data.get("mcp_calls") and current_mcp_log:
                    fin_data = dict(fin_data)
                    fin_data["mcp_calls"] = list(current_mcp_log)

                run_summary = normalize_json_safe({
                    "run_id": effective_run_id,
                    "workflow_type": workflow_type,
                    "period": period,
                    "status": effective_status,
                    "total_latency_ms": total_latency,
                    "validation_results": result.get("validation_results", {}),
                    "exceptions_count": len(result.get("exceptions", [])),
                    "exceptions": result.get("exceptions", []),
                    "agent_1_review": result.get("agent_1_review", {}),
                    "agent_2_analyses": result.get("agent_2_analyses", []),
                    "policy_contexts": result.get("policy_contexts", []),
                    "recommendations_count": len(result.get("recommendations", [])),
                    "recommendations": result.get("recommendations", []),
                    "financial_data": fin_data,
                    "input_params": input_params or {},
                    "hitl_decision": result.get("hitl_decision", {}),
                    "errors": result.get("errors", []),
                    "trace_log": trace_log,
                    "created_at": created_at_iso,
                })

                if is_hitl_pending:
                    await asyncio.to_thread(
                        self._persist_audit_event,
                        f"{effective_run_id}_HITL_PENDING",
                        effective_run_id,
                        "HITL_PENDING",
                        run_summary,
                    )
                    terminal_recorded = True
                    async with self._reservation_lock:
                        self._runs[effective_run_id] = run_summary
                    await self.metrics_collector.record_hitl_pending(effective_run_id)
                else:
                    event_type = "RUN_ERROR" if effective_status == "error" else "RUN_COMPLETED"
                    await asyncio.to_thread(
                        self._persist_audit_event,
                        f"{effective_run_id}_{event_type}",
                        effective_run_id,
                        event_type,
                        run_summary,
                    )
                    terminal_recorded = True
                    async with self._reservation_lock:
                        self._runs[effective_run_id] = run_summary
                    await self.metrics_collector.finalize_run(
                        run_id=effective_run_id,
                        status=effective_status,
                        latency_ms=total_latency,
                        tokens=0,
                        has_error=(effective_status == "error" or bool(result.get("errors"))),
                    )

                return run_summary

            except (RunConflictError, ObservabilityStorageError):
                raise

            except (asyncio.CancelledError, NodeCancelledError) as cancel_err:
                orig_cancel = (
                    cancel_err
                    if isinstance(cancel_err, asyncio.CancelledError)
                    else (
                        cancel_err.__cause__
                        if isinstance(cancel_err.__cause__, asyncio.CancelledError)
                        else asyncio.CancelledError(str(cancel_err))
                    )
                )
                if not terminal_recorded:
                    terminal_recorded = True
                    wall_latency = round((time.monotonic() - t_start) * 1000, 2)
                    cleanup_task = asyncio.create_task(
                        self._safe_record_cancellation(
                            effective_run_id,
                            workflow_type,
                            period,
                            input_params or {},
                            created_at_iso,
                            wall_latency,
                            mcp_log=current_mcp_log,
                        )
                    )
                    # MVP Limitation: Cleanup is bounded (5.0s max) to prevent indefinite hanging during cancellation.
                    # Hard process kills or fast runtime shutdowns may prevent final cancellation audit persistence.
                    deadline = time.monotonic() + 5.0
                    while not cleanup_task.done() and time.monotonic() < deadline:
                        try:
                            remaining = max(0.05, deadline - time.monotonic())
                            await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=remaining)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
                        except Exception as clean_err:
                            logger.warning("Cancellation cleanup failed for %s: %s", effective_run_id, clean_err)
                            break
                raise orig_cancel

            except Exception as exc:
                if not terminal_recorded:
                    terminal_recorded = True
                    wall_latency = round((time.monotonic() - t_start) * 1000, 2)
                    error_summary = normalize_json_safe({
                        "run_id": effective_run_id,
                        "workflow_type": workflow_type,
                        "period": period,
                        "status": "error",
                        "total_latency_ms": wall_latency,
                        "validation_results": {},
                        "exceptions_count": 0,
                        "exceptions": [],
                        "agent_1_review": {},
                        "agent_2_analyses": [],
                        "policy_contexts": [],
                        "recommendations_count": 0,
                        "recommendations": [],
                        "financial_data": {"mcp_calls": list(current_mcp_log)},
                        "input_params": input_params or {},
                        "hitl_decision": {},
                        "errors": [str(exc)],
                        "trace_log": [],
                        "created_at": created_at_iso,
                    })
                    await asyncio.to_thread(
                        self._persist_audit_event,
                        f"{effective_run_id}_RUN_ERROR",
                        effective_run_id,
                        "RUN_ERROR",
                        error_summary,
                    )
                    async with self._reservation_lock:
                        self._runs[effective_run_id] = error_summary
                    await self.metrics_collector.finalize_run(
                        run_id=effective_run_id,
                        status="error",
                        latency_ms=wall_latency,
                        tokens=0,
                        has_error=True,
                    )
                raise
        finally:
            _current_mcp_calls.reset(token)


    async def get_run_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the canonical live snapshot, or the persisted snapshot after restart."""
        async with self._reservation_lock:
            cached = self._runs.get(run_id)
            if cached is not None:
                return dict(cached)
        return await asyncio.to_thread(self._load_persisted_snapshot, run_id)

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

            async with self._reservation_lock:
                cached = dict(self._runs.get(run_id, {}))
            created_at = cached.get("created_at", "")
            decision_snapshot = {**resume_payload, "created_at": created_at}
            await asyncio.to_thread(
                self._persist_audit_event,
                f"{run_id}_HITL_DECISION",
                run_id,
                "HITL_DECISION",
                decision_snapshot,
            )

            t_start = time.monotonic()
            terminal_recorded = False
            try:
                resumed_result = await self.graph.ainvoke(Command(resume=resume_payload), config=config)

                final_status = resumed_result.get("status", normalized)
                trace_log = resumed_result.get("trace_log", [])
                resume_wall_latency = (time.monotonic() - t_start) * 1000
                total_latency = round(float(cached.get("total_latency_ms", 0.0)) + resume_wall_latency, 2)

                resumed_summary = normalize_json_safe({
                    "run_id": run_id,
                    "workflow_type": resumed_result.get("workflow_type", cached.get("workflow_type", "reconciliation")),
                    "period": resumed_result.get("period", cached.get("period", "")),
                    "status": final_status,
                    "total_latency_ms": total_latency,
                    "validation_results": resumed_result.get("validation_results", cached.get("validation_results", {})),
                    "exceptions_count": len(resumed_result.get("exceptions", cached.get("exceptions", []))),
                    "exceptions": resumed_result.get("exceptions", cached.get("exceptions", [])),
                    "agent_1_review": resumed_result.get("agent_1_review", cached.get("agent_1_review", {})),
                    "agent_2_analyses": resumed_result.get("agent_2_analyses", cached.get("agent_2_analyses", [])),
                    "policy_contexts": resumed_result.get("policy_contexts", cached.get("policy_contexts", [])),
                    "recommendations_count": len(resumed_result.get("recommendations", cached.get("recommendations", []))),
                    "recommendations": resumed_result.get("recommendations", cached.get("recommendations", [])),
                    "financial_data": resumed_result.get("financial_data", cached.get("financial_data", {})),
                    "input_params": resumed_result.get("input_params", cached.get("input_params", {})),
                    "hitl_decision": resume_payload,
                    "errors": resumed_result.get("errors", cached.get("errors", [])),
                    "trace_log": trace_log,
                    "created_at": created_at,
                })

                event_type = "RUN_ERROR" if final_status == "error" else "RUN_COMPLETED"
                await asyncio.to_thread(
                    self._persist_audit_event,
                    f"{run_id}_{event_type}",
                    run_id,
                    event_type,
                    resumed_summary,
                )
                terminal_recorded = True
                async with self._reservation_lock:
                    self._runs[run_id] = resumed_summary
                await self.metrics_collector.finalize_run(
                    run_id=run_id,
                    status=final_status,
                    latency_ms=total_latency,
                    tokens=0,
                    has_error=(final_status == "error" or bool(resumed_result.get("errors"))),
                )

                return {
                    "run_id": run_id,
                    "status": final_status,
                    "decision": normalized,
                    "reviewer": reviewer,
                    "comments": comments,
                }
            except (RunConflictError, ObservabilityStorageError):
                raise
            except (asyncio.CancelledError, NodeCancelledError) as cancel_err:
                orig_cancel = (
                    cancel_err
                    if isinstance(cancel_err, asyncio.CancelledError)
                    else (
                        cancel_err.__cause__
                        if isinstance(cancel_err.__cause__, asyncio.CancelledError)
                        else asyncio.CancelledError(str(cancel_err))
                    )
                )
                if not terminal_recorded:
                    terminal_recorded = True
                    elapsed = round((time.monotonic() - t_start) * 1000, 2)
                    total_latency = round(float(cached.get("total_latency_ms", 0.0)) + elapsed, 2)
                    cleanup_task = asyncio.create_task(
                        self._safe_record_cancellation(
                            run_id=run_id,
                            workflow_type=cached.get("workflow_type", "reconciliation"),
                            period=cached.get("period", ""),
                            input_params=cached.get("input_params", {}),
                            created_at_iso=created_at,
                            elapsed_ms=total_latency,
                            cached_data=cached,
                            hitl_decision=resume_payload,
                        )
                    )
                    # MVP Limitation: Cleanup is bounded (5.0s max) to prevent indefinite hanging during cancellation.
                    # Hard process kills or fast runtime shutdowns may prevent final cancellation audit persistence.
                    deadline = time.monotonic() + 5.0
                    while not cleanup_task.done() and time.monotonic() < deadline:
                        try:
                            remaining = max(0.05, deadline - time.monotonic())
                            await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=remaining)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
                        except Exception as clean_err:
                            logger.warning("Cancellation cleanup failed for %s: %s", run_id, clean_err)
                            break
                raise orig_cancel

            except Exception as exc:
                if not terminal_recorded:
                    terminal_recorded = True
                    elapsed = round((time.monotonic() - t_start) * 1000, 2)
                    error_summary = normalize_json_safe({
                        **cached,
                        "run_id": run_id,
                        "status": "error",
                        "total_latency_ms": round(float(cached.get("total_latency_ms", 0.0)) + elapsed, 2),
                        "hitl_decision": resume_payload,
                        "errors": list(cached.get("errors", [])) + [str(exc)],
                        "created_at": created_at,
                    })
                    await asyncio.to_thread(
                        self._persist_audit_event,
                        f"{run_id}_RUN_ERROR",
                        run_id,
                        "RUN_ERROR",
                        error_summary,
                    )
                    async with self._reservation_lock:
                        self._runs[run_id] = error_summary
                    await self.metrics_collector.finalize_run(
                        run_id=run_id,
                        status="error",
                        latency_ms=error_summary["total_latency_ms"],
                        tokens=0,
                        has_error=True,
                    )
                raise

    async def list_runs(self) -> List[Dict[str, Any]]:
        """
        List all active and historical workflow runs.
        Active runs come from memory; completed history comes from AuditTrailRecord.
        Raises ObservabilityStorageError on DB read failure.
        """
        runs_by_id = await asyncio.to_thread(self._load_run_summaries)
        async with self._reservation_lock:
            memory_runs = dict(self._runs)

        for rid, rdata in memory_runs.items():
            created_val = rdata.get("created_at") or (runs_by_id.get(rid, {}).get("created_at", ""))
            runs_by_id[rid] = {
                "run_id": rid,
                "workflow_type": rdata.get("workflow_type", "reconciliation"),
                "period": rdata.get("period", ""),
                "status": rdata.get("status", "unknown"),
                "exceptions_count": len(rdata.get("exceptions", [])),
                "recommendations_count": len(rdata.get("recommendations", [])),
                "created_at": created_val,
            }

        # Return stable sorted list
        return sorted(runs_by_id.values(), key=lambda r: (r.get("created_at") or "", r["run_id"]), reverse=True)

    async def get_run_trace(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve formatted full trace and audit trail for a specific run ID.
        Reconstructs full normalized snapshot from DB audit records if not in memory.
        Raises ObservabilityStorageError on database read failure.
        """
        state = await self.get_run_state(run_id)
        return format_run_trace(state) if state is not None else None

    def _query_audit_records(self, run_id: Optional[str] = None) -> List[AuditTrailRecord]:
        """Read detached audit records and consistently classify storage failures."""
        if self.session_factory is None:
            logger.error("Database session factory is unavailable")
            raise ObservabilityStorageError("Observability storage unavailable")
        try:
            db = self.session_factory()
        except Exception as exc:
            logger.error("Failed to open database session: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        try:
            query = db.query(AuditTrailRecord)
            if run_id is not None:
                query = query.filter(AuditTrailRecord.run_id == run_id)
            return query.order_by(AuditTrailRecord.created_at.asc()).all()
        except Exception as exc:
            logger.error("Failed to read audit records: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _load_persisted_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        records = self._query_audit_records(run_id)
        if not records:
            return None

        by_type = {record.event_type: record for record in records}
        started = by_type.get("RUN_STARTED")
        terminal = by_type.get("RUN_COMPLETED") or by_type.get("RUN_ERROR")
        selected = terminal or by_type.get("HITL_PENDING") or started
        details = dict(selected.details or {}) if selected is not None else {}

        if started is not None:
            started_details = dict(started.details or {})
            details.setdefault("run_id", run_id)
            details.setdefault("workflow_type", started_details.get("workflow_type", "reconciliation"))
            details.setdefault("period", started_details.get("period", ""))
            details.setdefault("input_params", started_details.get("input_params", {}))
            details.setdefault(
                "created_at",
                started_details.get("created_at")
                or (started.created_at.isoformat() if started.created_at else ""),
            )
        decision = by_type.get("HITL_DECISION")
        if decision is not None and not details.get("hitl_decision"):
            decision_details = dict(decision.details or {})
            decision_details.pop("created_at", None)
            details["hitl_decision"] = decision_details
        return self._complete_snapshot(run_id, details)

    @staticmethod
    def _complete_snapshot(run_id: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """Fill only structural defaults; never invent execution events or latency."""
        snapshot = {
            "run_id": run_id,
            "workflow_type": "reconciliation",
            "period": "",
            "status": "unknown",
            "total_latency_ms": 0.0,
            "validation_results": {},
            "exceptions_count": 0,
            "exceptions": [],
            "agent_1_review": {},
            "agent_2_analyses": [],
            "policy_contexts": [],
            "recommendations_count": 0,
            "recommendations": [],
            "financial_data": {},
            "input_params": {},
            "hitl_decision": {},
            "errors": [],
            "trace_log": [],
            "created_at": "",
        }
        snapshot.update(details)
        return normalize_json_safe(snapshot)

    def _load_run_summaries(self) -> Dict[str, Dict[str, Any]]:
        records = self._query_audit_records()
        run_ids = {record.run_id for record in records}
        summaries: Dict[str, Dict[str, Any]] = {}
        for run_id in run_ids:
            run_records = [record for record in records if record.run_id == run_id]
            by_type = {record.event_type: record for record in run_records}
            selected = (
                by_type.get("RUN_COMPLETED")
                or by_type.get("RUN_ERROR")
                or by_type.get("HITL_PENDING")
                or by_type.get("RUN_STARTED")
            )
            if selected is None:
                continue
            details = dict(selected.details or {})
            started = by_type.get("RUN_STARTED")
            created_at = details.get("created_at", "")
            if started is not None:
                start_details = dict(started.details or {})
                created_at = start_details.get("created_at") or (
                    started.created_at.isoformat() if started.created_at else ""
                )
                details.setdefault("workflow_type", start_details.get("workflow_type", "reconciliation"))
                details.setdefault("period", start_details.get("period", ""))
            summaries[run_id] = {
                "run_id": run_id,
                "workflow_type": details.get("workflow_type", "reconciliation"),
                "period": details.get("period", ""),
                "status": details.get("status", "unknown"),
                "exceptions_count": details.get("exceptions_count", len(details.get("exceptions", []))),
                "recommendations_count": details.get(
                    "recommendations_count", len(details.get("recommendations", []))
                ),
                "created_at": created_at,
            }
        return summaries


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
