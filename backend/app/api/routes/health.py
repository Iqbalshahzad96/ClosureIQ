"""
Health Check API Route
"""

from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    """
    Service health check endpoint.
    Returns the current status of the service, application name, and version.
    """
    return {
        "status": "healthy",
        "service": "ClosureIQ Backend API",
        "version": "0.1.0",
        "timestamp": "ready"
    }
