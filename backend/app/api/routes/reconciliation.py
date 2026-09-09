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
    account_code: str = Field(..., description="GL account code for reconciliation")
    limit: int = Field(default=50, ge=1, le=100, description="Max transactions to query (1-100)")

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("account_code cannot be blank or whitespace.")
        return v.strip()


class AccrualRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["accrual"] = "accrual"
    accrual_entries: List[AccrualEntryItem] = Field(..., min_length=1, description="List of accrual entries to validate")
    historical_baseline: Dict[str, AccrualBaselineValue] = Field(..., min_length=1, description="Historical baseline metrics")

    @field_validator("historical_baseline")
    @classmethod
    def validate_baseline_keys(cls, v: Dict[str, AccrualBaselineValue]) -> Dict[str, AccrualBaselineValue]:
        for k in v.keys():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"historical_baseline key cannot be blank or whitespace: {k!r}")
        return v


class DepreciationRunRequest(BaseRunRequest):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: Literal["depreciation"] = "depreciation"
    asset_records: List[AssetRecordItem] = Field(..., min_length=1, description="List of asset records")
    period_posted_depreciation: Dict[str, PostedDepreciationValue] = Field(..., min_length=1, description="Posted depreciation amounts per asset")

    @field_validator("period_posted_depreciation")
    @classmethod
    def validate_posted_keys(cls, v: Dict[str, PostedDepreciationValue]) -> Dict[str, PostedDepreciationValue]:
        for k in v.keys():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"period_posted_depreciation key cannot be blank or whitespace: {k!r}")
        return v


def get_workflow_type(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("workflow_type", "reconciliation")
    return getattr(v, "workflow_type", "reconciliation")


WorkflowRunRequest = Annotated[
    Union[
        Annotated[ReconciliationRunRequest, Tag("reconciliation")],
        Annotated[AccrualRunRequest, Tag("accrual")],
        Annotated[DepreciationRunRequest, Tag("depreciation")],
    ],
    Discriminator(get_workflow_type),
]


@router.post("/run", response_model=Dict[str, Any])
async def run_reconciliation(
    payload: WorkflowRunRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Trigger deterministic financial close workflow (reconciliation, accrual, or depreciation).
    Returns clean_close, hitl_pending, or error based on actual graph execution state.
    """
    if isinstance(payload, ReconciliationRunRequest):
        input_params = {
            "account_code": payload.account_code,
            "limit": payload.limit,
        }
    elif isinstance(payload, AccrualRunRequest):
        input_params = {
            "accrual_entries": [e.model_dump() for e in payload.accrual_entries],
            "historical_baseline": {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in payload.historical_baseline.items()
            },
        }
    elif isinstance(payload, DepreciationRunRequest):
        input_params = {
            "asset_records": [a.model_dump() for a in payload.asset_records],
            "period_posted_depreciation": {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in payload.period_posted_depreciation.items()
            },
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
        return run_state

    # Return latest run or default summary
    if workflow_service._runs:
        latest_run_id = list(workflow_service._runs.keys())[-1]
        latest_state = await workflow_service.get_run_state(latest_run_id)
        if latest_state:
            return latest_state

    return {
        "status": "idle",
        "total_runs": 0,
        "message": "No workflow runs executed yet",
    }
