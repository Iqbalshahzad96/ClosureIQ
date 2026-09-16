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
from decimal import Decimal
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
from app.database.models import AuditTrailRecord, ExceptionRecord, ReconciliationResult, ReconciliationRun
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.ap import APEngine
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
    "AP_REVIEW": "ACCRUAL",
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
    ap_engine: Optional[APEngine] = None,
    exception_generator: Optional[ExceptionGenerator] = None,
    financial_review_agent: Optional[FinancialReviewAgent] = None,
    policy_retriever: Optional[PolicyRetriever] = None,
    exception_analysis_agent: Optional[ExceptionAnalysisAgent] = None,
) -> WorkflowDeps:
    """Construct real production WorkflowDeps binding existing components."""
    _ap = ap_engine or APEngine()
    _exc = exception_generator or ExceptionGenerator()
    _a1 = financial_review_agent or FinancialReviewAgent()
    _rag = policy_retriever or PolicyRetriever()
    _a2 = exception_analysis_agent or ExceptionAnalysisAgent()

    async def fetch_data(workflow_type: str, input_params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch input data and record only MCP calls that actually execute."""
        run_calls = _current_mcp_calls.get()
        local_calls: List[Dict[str, Any]] = []

        async def invoke(
            tool_name: str,
            operation: Callable[..., Awaitable[Any]],
            **kwargs: Any,
        ) -> Any:
            started = time.monotonic()
            try:
                records = await operation(**kwargs)
            except Exception as exc:
                event = {
                    "node": "fetch_data",
                    "workflow_type": workflow_type,
                    "tool": tool_name,
                    "status": "error",
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "parameters": kwargs,
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
                "parameters": kwargs,
                "records_fetched": len(records) if isinstance(records, (list, tuple)) else (1 if records else 0),
                "error": None,
            }
            local_calls.append(event)
            if run_calls is not None:
                run_calls.append(event)
            return records

        async def fetch_all(tool_name, operation, **kwargs):
            records = []
            offset = 0
            while True:
                batch = await invoke(tool_name, operation, **kwargs, offset=offset)
                records.extend(batch)
                if len(batch) < kwargs["limit"]:
                    return records
                offset += len(batch)

        if workflow_type == "reconciliation":
            account_code = input_params.get("account_code")
            limit = int(input_params.get("limit", 50))
            period = input_params.get("period")

            account_codes = []
            if account_code and str(account_code).strip():
                account_codes = [str(account_code).strip()]
            else:
                db = session_factory()
                try:
                    from app.database.models import BankAccount, Account
                    bank_accounts = db.query(BankAccount, Account).join(
                        Account, BankAccount.linked_gl_account_id == Account.id
                    ).filter(
                        BankAccount.is_active == True,
                        Account.is_active == True
                    ).all()
                    account_codes = sorted({gl.account_code for bank, gl in bank_accounts
                        if gl.organization_id == mcp_tools.organization_id and bank.organization_id == mcp_tools.organization_id})
                finally:
                    db.close()

            if not account_codes:
                raise ValueError("No eligible bank accounts found for reconciliation.")

            accounts_data = []
            for acct in account_codes:
                gl_records = await fetch_all(f"query_gl_transactions_{acct}", mcp_tools.query_gl_transactions, account_code=acct, limit=limit, fiscal_period=period)
                bank_records = await fetch_all(f"query_bank_transactions_{acct}", mcp_tools.query_bank_transactions, account_code=acct, limit=limit, fiscal_period=period)

                accounts_data.append({
                    "account_code": acct,
                    "gl_transactions": gl_records,
                    "bank_transactions": bank_records,
                })

            return {
                "account_code": account_code,  # For backward compatibility if single account
                "accounts_data": accounts_data,
                "mcp_calls": local_calls,
                "is_multi_account": len(accounts_data) > 1 or not account_code
            }

        if workflow_type == "accrual":
            accrual_entries = input_params.get("accrual_entries")
            historical_baseline = input_params.get("historical_baseline")
            account_code = input_params.get("account_code")
            limit = int(input_params.get("limit", 50))

            if accrual_entries is None:
                period = input_params.get("period", "CURRENT")
                accounts = ([{"account_code": account_code}] if account_code else
                    await invoke("query_accrual_accounts", mcp_tools.query_accrual_accounts, fiscal_period=period))
                if not accounts:
                    raise ValueError("No eligible accrual accounts with posted activity were found for this period.")
                gl_records = []
                for account in accounts:
                    rows = await fetch_all("query_gl_transactions", mcp_tools.query_gl_transactions,
                        account_code=account["account_code"], limit=limit, fiscal_period=period)
                    gl_records.extend(r for r in rows if r.get("entry_status") == "POSTED")
                if not gl_records:
                    raise ValueError("No posted accrual transactions were found for this period.")
                accrual_entries = [
                    {
                        "id": r.get("id"),
                        "account_code": r.get("account_code"),
                        "vendor": r.get("description") or r.get("reference"),
                        "name": r.get("description") or r.get("reference"),
                        "amount": abs(float(r.get("amount", 0.0))),
                        "description": r.get("description"),
                        "period": input_params.get("period", "CURRENT"),
                    }
                    for r in gl_records
                ]

            if accrual_entries is None:
                raise ValueError("accrual_entries is required for accrual workflow")
            if historical_baseline is None:
                historical_baseline = {}

            return {
                "accrual_entries": accrual_entries,
                "historical_baseline": historical_baseline,
                "mcp_calls": local_calls,
            }

        if workflow_type == "depreciation":
            asset_records = input_params.get("asset_records")
            period_posted_depreciation = input_params.get("period_posted_depreciation")
            limit = int(input_params.get("limit", 50))

            if asset_records is None:
                category = input_params.get("category")
                status_filter = input_params.get("status") or "ACTIVE"
                assets = await fetch_all("query_fixed_assets", mcp_tools.query_fixed_assets, category=category, status=status_filter, limit=limit, fiscal_period=input_params.get("period"))
                if not assets:
                    raise ValueError("No eligible fixed assets were found for this period.")
                asset_records = assets

            if period_posted_depreciation is None:
                period_posted_depreciation = {}

            if asset_records is None:
                raise ValueError("asset_records is required for depreciation workflow")

            return {
                "asset_records": asset_records,
                "period_posted_depreciation": period_posted_depreciation,
                "mcp_calls": local_calls,
            }

        if workflow_type in ("ap_review", "ap", "ap_invoices"):
            invoices = input_params.get("invoices")
            limit = int(input_params.get("limit", 50))

            if invoices is None:
                vendor_name = input_params.get("vendor_name")
                status_filter = input_params.get("status")
                fetched = await fetch_all("query_ap_invoices", mcp_tools.query_ap_invoices, vendor_name=vendor_name, status=status_filter, limit=limit, fiscal_period=input_params.get("period"))
                if not fetched:
                    raise ValueError("No eligible AP invoices were found for this period.")
                invoices = fetched

            if invoices is None:
                invoices = []

            period = input_params.get("period")
            from app.financial_engine.periods import period_bounds
            from datetime import timedelta
            as_of_date = input_params.get("as_of_date") or (
                (period_bounds(period)[1] - timedelta(days=1)).date().isoformat() if period else None)

            return {
                "invoices": invoices,
                "as_of_date": as_of_date,
                "mcp_calls": local_calls,
            }

        raise ValueError(f"Unsupported workflow_type: {workflow_type}")

    async def run_validation(workflow_type: str, financial_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run deterministic financial math inside financial_engine."""
        if workflow_type == "reconciliation":
            accounts_data = financial_data.get("accounts_data", [])
            # Fallback for old single-account format
            if not accounts_data and "gl_transactions" in financial_data:
                accounts_data = [{
                    "account_code": financial_data.get("account_code"),
                    "gl_transactions": financial_data.get("gl_transactions", []),
                    "bank_transactions": financial_data.get("bank_transactions", [])
                }]

            combined_results = {
                "net_variance": 0.0,
                "matches": [],
                "unmatched_gl": [],
                "unmatched_bank": [],
                "metrics": {
                    "matched_count": 0,
                    "matched_amount": 0.0,
                    "unmatched_gl_count": 0,
                    "unmatched_bank_count": 0
                }
            }

            for acct_data in accounts_data:
                gl = acct_data.get("gl_transactions", [])
                bank = acct_data.get("bank_transactions", [])
                res = reconciliation_engine.reconcile(gl_transactions=gl, bank_transactions=bank)
                combined_results["net_variance"] += res.get("net_variance", 0.0)
                combined_results["matches"].extend(res.get("matched", []))
                combined_results["unmatched_gl"].extend(res.get("unmatched_gl", []))
                combined_results["unmatched_bank"].extend(res.get("unmatched_bank", []))

                metrics = {**res, "matched_amount": res.get("reconciled_gl_amount", 0.0)}
                for k in combined_results["metrics"]:
                    combined_results["metrics"][k] += float(metrics.get(k, 0.0))

            combined_results.update(combined_results["metrics"])
            combined_results["matched"] = combined_results["matches"]
            return combined_results

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

        elif workflow_type in ("ap_review", "ap", "ap_invoices"):
            invoices = financial_data.get("invoices", [])
            as_of = financial_data.get("as_of_date")
            return _ap.validate_ap_invoices(invoices=invoices, as_of_date=as_of)

        else:
            raise ValueError(f"Unsupported workflow_type: {workflow_type}")

    async def detect_exceptions(
        workflow_type: str,
        validation_results: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[Dict[str, Any]]:
        """Generate structured exceptions and persist them to exception_records and reconciliation_results."""
        cat_map = {
            "reconciliation": "RECONCILIATION",
            "accrual": "ACCRUAL",
            "depreciation": "DEPRECIATION",
            "ap_review": "AP_REVIEW",
            "ap": "AP_REVIEW",
            "ap_invoices": "AP_REVIEW",
        }
        category = cat_map.get(workflow_type, "GENERAL")
        effective_period = period or "CURRENT"

        raw_exceptions = _exc.generate_exceptions(
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

        # Enrich exceptions with canonical record lineage when available
        if mcp_tools is not None:
            for item in serialized:
                meta = item.get("metadata") or {}
                lineage_info = None
                try:
                    if meta.get("source") == "GL" and meta.get("record", {}).get("id"):
                        lineage_info = await mcp_tools.get_record_lineage("JOURNAL_LINE", meta["record"]["id"])
                    elif meta.get("source") == "BANK" and meta.get("record", {}).get("id"):
                        lineage_info = await mcp_tools.get_record_lineage("BANK_TRANSACTION", meta["record"]["id"])
                    elif category == "DEPRECIATION" and meta.get("asset_id"):
                        lineage_info = await mcp_tools.get_record_lineage("FIXED_ASSET", meta["asset_id"])
                    elif category == "AP_REVIEW" and meta.get("invoice_id"):
                        lineage_info = await mcp_tools.get_record_lineage("AP_INVOICE", meta["invoice_id"])
                    elif meta.get("id"):
                        if meta.get("source") == "GL":
                            lineage_info = await mcp_tools.get_record_lineage("JOURNAL_LINE", meta["id"])
                        elif meta.get("source") == "BANK":
                            lineage_info = await mcp_tools.get_record_lineage("BANK_TRANSACTION", meta["id"])
                except Exception as l_exc:
                    logger.debug("Lineage lookup skipped for exception %s: %s", item.get("id"), l_exc)

                if lineage_info and lineage_info.get("found"):
                    item["lineage"] = lineage_info

        # Persist exceptions idempotently to existing exception_records & reconciliation_results table
        if session_factory is not None:
            db = session_factory()
            committed = False
            try:
                run_type_map = {
                    "RECONCILIATION": "GL_BANK_RECONCILIATION",
                    "ACCRUAL": "ACCRUAL_REVIEW",
                    "DEPRECIATION": "DEPRECIATION_VALIDATION",
                    "AP_REVIEW": "AP_REVIEW",
                }
                rec_run_type = run_type_map.get(category, "GL_BANK_RECONCILIATION")
                run_record_id = f"run_{category.lower()}_{effective_period.replace('-', '_')}"

                current_run = db.get(ReconciliationRun, run_record_id)
                if current_run is None:
                    current_run = ReconciliationRun(
                        id=run_record_id,
                        organization_id="default_org",
                        run_type=rec_run_type,
                        fiscal_period=effective_period,
                        status="IN_PROGRESS",
                    )
                    db.add(current_run)
                    db.flush()

                for item in serialized:
                    exc_id = item.get("id")
                    if not exc_id:
                        continue
                    meta = item.get("metadata") or {}

                    # Extract entity keys from metadata
                    gl_line_id = None
                    bank_tx_id = None
                    asset_id = None
                    inv_id = None

                    if meta.get("source") == "GL":
                        gl_line_id = meta.get("record", {}).get("id")
                    elif meta.get("source") == "BANK":
                        bank_tx_id = meta.get("record", {}).get("id")
                    elif category == "DEPRECIATION":
                        asset_id = meta.get("asset_id")
                    elif category == "AP_REVIEW":
                        inv_id = meta.get("invoice_id")

                    recon_res_id = f"res_{exc_id}"
                    existing_res = db.get(ReconciliationResult, recon_res_id)
                    if existing_res is None:
                        result_type = (
                            "BANK_RECONCILIATION" if category == "RECONCILIATION"
                            else "ACCRUAL_REVIEW" if category == "ACCRUAL"
                            else "DEPRECIATION_VALIDATION" if category == "DEPRECIATION"
                            else "AP_REVIEW"
                        )
                        var_val = Decimal(str(item.get("amount_variance", 0.0)))
                        exp_val = Decimal(str(meta.get("calculated_depreciation") or meta.get("expected_amount") or 0.0))
                        act_val = Decimal(str(meta.get("posted_depreciation") or meta.get("actual_amount") or 0.0))
                        recon_res = ReconciliationResult(
                            id=recon_res_id,
                            run_id=current_run.id,
                            result_type=result_type,
                            journal_line_id=gl_line_id,
                            bank_transaction_id=bank_tx_id,
                            fixed_asset_id=asset_id,
                            ap_invoice_id=inv_id,
                            expected_amount=exp_val,
                            actual_amount=act_val,
                            variance=var_val,
                            amount_difference=var_val,
                            status="UNMATCHED" if category == "RECONCILIATION" else "VARIANCE_DETECTED",
                            result_status="UNMATCHED" if category == "RECONCILIATION" else "VARIANCE_DETECTED",
                            match_method="DETERMINISTIC_RULES",
                            details_json=normalize_json_safe(
                                {**meta, **({"lineage": item["lineage"]} if item.get("lineage") else {})}
                            ),
                        )
                        db.add(recon_res)
                        db.flush()

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
                            reconciliation_result_id=recon_res_id,
                            run_id=current_run.id,
                            journal_line_id=gl_line_id,
                            bank_transaction_id=bank_tx_id,
                            period=item.get("period") or effective_period,
                            category=item.get("category", category),
                            severity=item.get("severity", "MEDIUM"),
                            amount_variance=Decimal(str(item.get("amount_variance", 0.0))),
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
        return await _a1.run_agent_1(exceptions, validation_results)

    async def retrieve_policies(exc: Dict[str, Any], agent_1_review: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve grounded accounting policy context for a single exception."""
        query = exc.get("description") or f"{exc.get('category', '')} exception"
        category = exc.get("category")
        mapped_cat = RAG_CATEGORY_MAP.get(category, category) if category else None

        # Attempt retrieval with mapped category filter
        evidence = await _rag.retrieve_policy_context(
            query=query,
            top_k=3,
            category=mapped_cat,
        )

        # Fallback to unrestricted search if category-specific filter returned no evidence
        if not evidence and mapped_cat:
            evidence = await _rag.retrieve_policy_context(
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
        return await _a2.run_agent_2(exc, agent_1_review, matched_evidence)

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
        ap_engine: Optional[APEngine] = None,
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
            _ap = ap_engine or APEngine()
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
                ap_engine=_ap,
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


    async def get_reconciliation_preview(self, period: str) -> Dict[str, Any]:
        """
        Generate a pre-run preview of eligible bank accounts and their transaction volumes
        for a given financial period.
        """
        if self.session_factory is None:
            raise ObservabilityStorageError("Observability storage unavailable")

        from app.database.models import BankAccount, Account, JournalEntry, JournalLine, BankTransaction, ReconciliationResult
        from sqlalchemy import func

        try:
            db = self.session_factory()
        except Exception as exc:
            logger.error("Failed to open database session: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc

        try:
            # Find eligible bank accounts with linked GL accounts
            bank_accounts = db.query(BankAccount, Account).join(
                Account, BankAccount.linked_gl_account_id == Account.id
            ).filter(
                BankAccount.is_active == True,
                Account.is_active == True
            ).all()

            preview_data = {
                "period": period,
                "detected_accounts": [],
                "total_gl_transactions": 0,
                "total_bank_transactions": 0,
                "total_already_reconciled": 0,
                "missing_account_links": 0,  # Could be calculated by checking BankAccounts without links
            }

            # Count bank accounts without links
            unlinked = db.query(BankAccount).filter(
                BankAccount.linked_gl_account_id == None,
                BankAccount.is_active == True
            ).count()
            preview_data["missing_account_links"] = unlinked

            for bank, gl in bank_accounts:
                account_code = gl.account_code

                from app.financial_engine.periods import period_bounds, ledger_period_filter
                start, end = period_bounds(period)
                gl_count = db.query(JournalLine).join(
                    JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
                ).filter(JournalLine.account_id == gl.id,
                    JournalEntry.organization_id == gl.organization_id,
                    JournalEntry.currency_code == gl.currency_code,
                    ledger_period_filter(JournalEntry.fiscal_period, JournalEntry.entry_date, period)
                ).count()
                bank_count = db.query(BankTransaction).filter(
                    BankTransaction.bank_account_id == bank.id,
                    BankTransaction.currency_code == bank.currency_code,
                    BankTransaction.booking_date >= start, BankTransaction.booking_date < end
                ).count()

                preview_data["detected_accounts"].append({
                    "account_code": account_code,
                    "bank_name": bank.bank_name,
                    "account_name": bank.account_name,
                    "gl_count": gl_count,
                    "bank_count": bank_count,
                    "eligible": (gl_count > 0 or bank_count > 0)
                })

                preview_data["total_gl_transactions"] += gl_count
                preview_data["total_bank_transactions"] += bank_count

            return preview_data
        except Exception as exc:
            logger.error("Failed to generate preview: %s", exc, exc_info=True)
            raise ObservabilityStorageError("Observability storage unavailable") from exc
        finally:
            try:
                db.close()
            except Exception:
                pass

    def get_unresolved_mappings(self) -> Dict[str, Any]:
        try:
            db = self.session_factory()
            from app.database.models import BankAccount, Account
            from sqlalchemy import or_

            unresolved = db.query(BankAccount).filter(
                BankAccount.linked_gl_account_id == None,
                BankAccount.is_active == True,
            ).all()
            results = []

            def serialize_account(account: Account) -> Dict[str, Any]:
                return {
                    "id": account.id,
                    "account_code": account.account_code,
                    "account_name": account.account_name,
                    "account_type": account.account_type,
                    "currency_code": account.currency_code,
                }

            for bank in unresolved:
                all_accounts = db.query(Account).filter(
                    Account.is_active == True,
                    Account.organization_id == bank.organization_id,
                ).order_by(Account.account_type.asc(), Account.account_code.asc(), Account.account_name.asc()).all()

                normalized_bank_name = bank.account_name.upper() if bank.account_name else ""
                suggestions = db.query(Account).filter(
                    Account.is_active == True,
                    Account.organization_id == bank.organization_id,
                    or_(
                        Account.account_code == bank.account_number_masked,
                        Account.account_name == bank.bank_name,
                        Account.account_name == bank.account_name,
                        Account.normalized_name == normalized_bank_name,
                    ),
                ).all()

                if not suggestions:
                    suggestions = [account for account in all_accounts if account.account_type == "ASSET"][:5]

                display_bank_name = bank.bank_name
                display_account_name = bank.account_name
                if (bank.bank_name or "").strip().lower() == "suspense bank":
                    display_bank_name = "Unmatched Bank Account"
                if (bank.account_name or "").strip().lower() == "suspense":
                    display_account_name = "Needs ledger mapping"

                results.append({
                    "bank_account_id": bank.id,
                    "bank_name": bank.bank_name,
                    "account_name": bank.account_name,
                    "display_bank_name": display_bank_name,
                    "display_account_name": display_account_name,
                    "account_number_masked": bank.account_number_masked,
                    "currency_code": bank.currency_code,
                    "suggestions": [serialize_account(account) for account in suggestions],
                    "all_gl_accounts": [serialize_account(account) for account in all_accounts],
                })
            return {"unresolved": results}
        finally:
            try:
                db.close()
            except Exception:
                pass

    def resolve_mapping(self, bank_account_id: str, gl_account_id: str) -> Dict[str, Any]:
        try:
            db = self.session_factory()
            from app.database.models import Account, BankAccount
            bank = db.get(BankAccount, bank_account_id)
            gl_account = db.get(Account, gl_account_id)
            if not bank:
                return {"status": "error", "message": "Bank account not found"}
            if not gl_account or not gl_account.is_active or gl_account.organization_id != bank.organization_id:
                return {"status": "error", "message": "Selected ledger account was not found"}

            bank.linked_gl_account_id = gl_account_id
            db.commit()
            return {"status": "success"}
        finally:
            try:
                db.close()
            except Exception:
                pass

    def get_available_periods(self) -> Dict[str, Any]:
        try:
            db = self.session_factory()
            from app.database.models import JournalEntry, BankTransaction, APInvoice, FixedAsset

            # Get distinct periods from JournalEntry
            je_periods = db.query(JournalEntry.fiscal_period).distinct().all()
            periods = set([p[0] for p in je_periods if p[0]])

            # Get distinct YYYY-MM from BankTransaction booking_date
            bt_dates = db.query(BankTransaction.booking_date).distinct().all()
            for d in bt_dates:
                if d[0]:
                    periods.add(d[0].strftime("%Y-%m"))

            for model, column in ((APInvoice, APInvoice.invoice_date), (FixedAsset, FixedAsset.in_service_date),
                                  (FixedAsset, FixedAsset.acquisition_date)):
                for (value,) in db.query(column).distinct().all():
                    if value:
                        periods.add(value.strftime("%Y-%m"))

            # Extract yearly periods
            yearly = set([p.split("-")[0] for p in periods if "-" in p])
            periods.update(yearly)

            sorted_periods = sorted(list(periods), reverse=True)
            return {"periods": sorted_periods}
        finally:
            try: db.close()
            except: pass

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
