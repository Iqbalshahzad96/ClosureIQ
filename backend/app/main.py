"""
ClosureIQ FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import api_router
from app.observability.logger import setup_logging
from app.services.workflow_service import WorkflowService

# Initialize structured logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Initializes application-lifetime singleton services.
    ClosureIQ uses an in-memory MemorySaver checkpointer for the MVP,
    requiring single-process, single-worker execution (uvicorn --workers 1).
    """
    app.state.workflow_service = WorkflowService()
    logger.info("Application-lifetime WorkflowService initialized on app.state.")
    yield


def create_application() -> FastAPI:
    """Create and configure FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="ClosureIQ — AI-Powered Financial Close Assistant API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Configure CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes under prefix
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    # Also register health check at root /health for convenience
    from app.api.routes.health import router as health_router
    app.include_router(health_router)

    logger.info("ClosureIQ application initialized successfully.")
    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
