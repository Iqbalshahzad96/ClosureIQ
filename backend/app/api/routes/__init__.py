"""
API Router Aggregation
"""

from fastapi import APIRouter
from app.api.routes import (
    health,
    reconciliation,
    exceptions,
    insights,
    approvals,
    observability,
)

api_router = APIRouter()

# Include all sub-routers
api_router.include_router(health.router)
api_router.include_router(reconciliation.router)
api_router.include_router(exceptions.router)
api_router.include_router(insights.router)
api_router.include_router(approvals.router)
api_router.include_router(observability.router)
