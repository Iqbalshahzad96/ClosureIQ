"""
Reconciliation API Routes (GL-to-Bank and Financial Close Workflows)
"""

import math
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

from app.services.workflow_service import RunConflictError, WorkflowService, get_workflow_service

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


def _sanitize_non_finite_numbers(obj: Any) -> Any:
    """Recursively convert NaN/Infinity floats to strings so Pydantic rejects them with JSON-compliant error detail."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return str(obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_non_finite_numbers(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_non_finite_numbers(i) for i in obj]
    return obj


class AccrualEntryItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    vendor: Optional[str] = None
    account_code: Optional[str] = None
    name: Optional[str] = None
    amount: float = Field(..., allow_inf_nan=False, description="Accrual amount (finite number)")
    description: Optional[str] = None
    period: Optional[str] = None
    id: Optional[str] = None

    @field_validator("vendor", "account_code", "name", "description", "period", "id")
    @classmethod
    def validate_non_blank_optional_str(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Identifier or string field cannot be blank or whitespace.")
        return v

    @model_validator(mode="after")
    def validate_has_identifier(self) -> "AccrualEntryItem":
        if not (self.vendor or self.account_code or self.name or self.id):
            raise ValueError("Accrual entry must provide at least one identifier: vendor, account_code, name, or id.")
        return self


class AccrualBaselineItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    amount: float = Field(..., allow_inf_nan=False, description="Baseline expected amount (finite number)")
    is_recurring: Optional[bool] = None
    vendor_name: Optional[str] = None

    @field_validator("vendor_name")
    @classmethod
    def validate_vendor_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("vendor_name cannot be blank or whitespace.")
        return v


AccrualBaselineValue = Union[AccrualBaselineItem, Annotated[float, Field(allow_inf_nan=False)]]


class AssetRecordItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    asset_id: Optional[str] = None
    id: Optional[str] = None
    asset_name: Optional[str] = None
    cost: float = Field(..., ge=0.0, allow_inf_nan=False, description="Asset purchase cost (finite >= 0)")
    salvage_value: float = Field(default=0.0, ge=0.0, allow_inf_nan=False, description="Estimated salvage value (finite >= 0)")
    useful_life_months: int = Field(..., gt=0, description="Useful life in months (strictly > 0)")
    accumulated_depreciation_prior: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    @field_validator("asset_id", "id", "asset_name")
    @classmethod
    def validate_asset_identifiers(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Asset identifier cannot be blank or whitespace.")
        return v

    @model_validator(mode="after")
    def validate_has_identifier(self) -> "AssetRecordItem":
        if not (self.asset_id or self.id or self.asset_name):
            raise ValueError("Asset record must provide at least one of asset_id, id, or asset_name.")
        return self


class PostedDepreciationItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    amount: float = Field(..., allow_inf_nan=False, ge=0.0, description="Posted depreciation amount (finite >= 0)")
    account_code: Optional[str] = None

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("account_code cannot be blank or whitespace.")
        return v


PostedDepreciationValue = Union[PostedDepreciationItem, Annotated[float, Field(allow_inf_nan=False, ge=0.0)]]


class BaseRunRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    period: str = Field(default="CURRENT", description="Financial close period")
    run_id: Optional[str] = Field(default=None, description="Optional custom run ID")

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("period cannot be blank or whitespace.")
        return v.strip()

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("run_id cannot be blank or whitespace.")
        return v.strip() if v is not None else None

    @model_validator(mode="before")
    @classmethod
    def unpack_input_params(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cleaned = _sanitize_non_finite_numbers(data)
            if "input_params" in cleaned:
                d = dict(cleaned)
                params = d.pop("input_params")
                if isinstance(params, dict):
                    merged = dict(params)
                    merged.update(d)
                    return merged
                elif params is not None:
                    raise ValueError("input_params must be a dictionary")
                return d
            return cleaned
        return data


class ReconciliationRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["reconciliation"] = "reconciliation"
    account_code: Optional[str] = Field(default=None, description="Optional GL account code. If omitted, runs for all eligible accounts.")
    limit: int = Field(default=50, ge=1, le=100, description="Max transactions to query per account (1-100)")

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("account_code cannot be blank or whitespace.")
        return v.strip() if v is not None else None


class AccrualRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["accrual"] = "accrual"
    account_code: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)
    accrual_entries: Optional[List[AccrualEntryItem]] = Field(default=None, description="Optional explicit accrual entries")
    historical_baseline: Optional[Dict[str, AccrualBaselineValue]] = Field(default=None, description="Optional historical baseline metrics")

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("account_code cannot be blank or whitespace.")
        return v.strip() if v is not None else None

    @field_validator("historical_baseline")
    @classmethod
    def validate_baseline_keys(cls, v: Optional[Dict[str, AccrualBaselineValue]]) -> Optional[Dict[str, AccrualBaselineValue]]:
        if v is not None:
            for k in v.keys():
                if not isinstance(k, str) or not k.strip():
                    raise ValueError(f"historical_baseline key cannot be blank or whitespace: {k!r}")
        return v

    @model_validator(mode="after")
    def validate_source(self) -> "AccrualRunRequest":
        if self.accrual_entries == []:
            raise ValueError("Explicit accrual_entries cannot be empty; omit them to detect accounts automatically.")
        if self.accrual_entries is not None and self.historical_baseline is None:
            raise ValueError("Accrual workflow requires historical_baseline when explicit accrual_entries are provided.")
        return self


class DepreciationRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["depreciation"] = "depreciation"
    category: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)
    asset_records: Optional[List[AssetRecordItem]] = Field(default=None, description="Optional explicit asset records")
    period_posted_depreciation: Optional[Dict[str, PostedDepreciationValue]] = Field(default=None, description="Optional posted depreciation per asset")

    @field_validator("category", "status")
    @classmethod
    def validate_filter_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Filter string cannot be blank or whitespace.")
        return v

    @field_validator("period_posted_depreciation")
    @classmethod
    def validate_posted_keys(cls, v: Optional[Dict[str, PostedDepreciationValue]]) -> Optional[Dict[str, PostedDepreciationValue]]:
        if v is not None:
            for k in v.keys():
                if not isinstance(k, str) or not k.strip():
                    raise ValueError(f"period_posted_depreciation key cannot be blank or whitespace: {k!r}")
        return v

    @model_validator(mode="after")
    def validate_source(self) -> "DepreciationRunRequest":
        if self.period == "CURRENT" and not self.asset_records and not self.category and not self.status:
            raise ValueError("Depreciation workflow requires explicit asset_records or a specific period/category filter.")
        return self


class APReviewRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["ap_review"] = "ap_review"
    vendor_name: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("vendor_name", "status")
    @classmethod
    def validate_non_blank_optional_str(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("String field cannot be blank or whitespace.")
        return v


class APShortRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["ap"] = "ap"
    vendor_name: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("vendor_name", "status")
    @classmethod
    def validate_non_blank_optional_str(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("String field cannot be blank or whitespace.")
        return v


APRunRequest = Union[APReviewRunRequest, APShortRunRequest]


def get_workflow_type(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("workflow_type", "reconciliation")
    return getattr(v, "workflow_type", "reconciliation")


WorkflowRunRequest = Annotated[
    Union[
        Annotated[ReconciliationRunRequest, Tag("reconciliation")],
        Annotated[AccrualRunRequest, Tag("accrual")],
        Annotated[DepreciationRunRequest, Tag("depreciation")],
        Annotated[APReviewRunRequest, Tag("ap_review")],
        Annotated[APShortRunRequest, Tag("ap")],
    ],
    Discriminator(get_workflow_type),
]


@router.post("/run", response_model=Dict[str, Any])
async def run_reconciliation(
    payload: WorkflowRunRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Trigger deterministic financial close workflow (reconciliation, accrual, depreciation, or ap_review).
    Returns clean_close, hitl_pending, or error based on actual graph execution state.
    """
    if isinstance(payload, ReconciliationRunRequest):
        input_params = {
            "account_code": payload.account_code,
            "limit": payload.limit,
            "period": payload.period,
        }
    elif isinstance(payload, AccrualRunRequest):
        input_params = {
            "account_code": payload.account_code,
            "limit": payload.limit,
            "period": payload.period,
        }
        if payload.accrual_entries is not None:
            input_params["accrual_entries"] = [e.model_dump() for e in payload.accrual_entries]
        if payload.historical_baseline is not None:
            input_params["historical_baseline"] = {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in payload.historical_baseline.items()
            }
    elif isinstance(payload, DepreciationRunRequest):
        input_params = {
            "category": payload.category,
            "status": payload.status,
            "limit": payload.limit,
            "period": payload.period,
        }
        if payload.asset_records is not None:
            input_params["asset_records"] = [a.model_dump() for a in payload.asset_records]
        if payload.period_posted_depreciation is not None:
            input_params["period_posted_depreciation"] = {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in payload.period_posted_depreciation.items()
            }
    elif isinstance(payload, (APReviewRunRequest, APShortRunRequest)):
        input_params = {
            "vendor_name": payload.vendor_name,
            "status": payload.status,
            "limit": payload.limit,
            "period": payload.period,
        }
    else:
        input_params = {}

    try:
        result = await workflow_service.start_workflow(
            workflow_type=payload.workflow_type,
            period=payload.period,
            input_params=input_params,
            run_id=payload.run_id,
        )
        return result
    except RunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {exc}",
        )


@router.get("/preview", response_model=Dict[str, Any])
async def get_reconciliation_preview(
    period: str = Query(..., description="Financial close period (e.g., YYYY-MM)"),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Retrieve a pre-run preview of eligible bank accounts and their transaction volumes.
    """
    try:
        return await workflow_service.get_reconciliation_preview(period)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview generation failed: {exc}",
        )


def _enrich_reconciliation_summary(run_state: Dict[str, Any]) -> Dict[str, Any]:
    if run_state.get("workflow_type") == "reconciliation":
        val_res = run_state.get("validation_results") or {}
        metrics = val_res.get("metrics") or {}
        
        matched_count = metrics.get("matched_count", 0)
        unmatched_gl = metrics.get("unmatched_gl_count", 0)
        unmatched_bank = metrics.get("unmatched_bank_count", 0)
        
        total_transactions = matched_count * 2 + unmatched_gl + unmatched_bank
        matched_percentage = (matched_count * 2 / total_transactions * 100) if total_transactions > 0 else 0
        
        exceptions = run_state.get("exceptions", [])
        hitl_pending = sum(1 for e in exceptions if e.get("status") == "OPEN")
        approved = sum(1 for e in exceptions if e.get("status") == "APPROVED")
        rejected = sum(1 for e in exceptions if e.get("status") == "REJECTED")
        
        final_matched_count = matched_count + approved
        final_percentage = (final_matched_count * 2 / total_transactions * 100) if total_transactions > 0 else 0
        
        run_state["summary_metrics"] = {
            "matched_count": matched_count,
            "matched_percentage": round(matched_percentage, 2),
            "unmatched_gl_count": unmatched_gl,
            "unmatched_bank_count": unmatched_bank,
            "exceptions_count": len(exceptions),
            "hitl_pending_count": hitl_pending,
            "approved_count": approved,
            "rejected_count": rejected,
            "final_reconciled_percentage": round(final_percentage, 2)
        }
    return run_state

class ResolveMappingRequest(BaseModel):
    bank_account_id: str
    gl_account_id: str

@router.get("/unresolved-mappings")
async def get_unresolved_mappings(workflow_service: WorkflowService = Depends(get_workflow_service)):
    return workflow_service.get_unresolved_mappings()

@router.post("/resolve-mapping")
async def resolve_mapping(req: ResolveMappingRequest, workflow_service: WorkflowService = Depends(get_workflow_service)):
    return workflow_service.resolve_mapping(req.bank_account_id, req.gl_account_id)

@router.get("/periods")
async def get_available_periods(workflow_service: WorkflowService = Depends(get_workflow_service)):
    return workflow_service.get_available_periods()

@router.get("/summary", response_model=Dict[str, Any])
async def get_reconciliation_summary(
    run_id: Optional[str] = Query(default=None, description="Optional run ID to query state for"),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Retrieve financial close workflow summary and latest metrics.
    """
    if run_id:
        run_state = await workflow_service.get_run_state(run_id)
        if not run_state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found",
            )
        return _enrich_reconciliation_summary(run_state)

    # Return latest run or default summary
    if workflow_service._runs:
        latest_run_id = list(workflow_service._runs.keys())[-1]
        latest_state = await workflow_service.get_run_state(latest_run_id)
        if latest_state:
            return _enrich_reconciliation_summary(latest_state)

    return {
        "status": "idle",
        "total_runs": 0,
        "message": "No workflow runs executed yet",
    }
