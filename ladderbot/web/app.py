"""FastAPI application for LadderBot web dashboard.

Serves the single-page dashboard and REST API for picks, ladder, and performance.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ladderbot.db.database import get_db
from ladderbot.web.routes.picks import router as picks_router
from ladderbot.web.routes.ladder import router as ladder_router
from ladderbot.web.routes.dashboard import router as dashboard_router


_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    db_path = app.state.db_path if hasattr(app.state, "db_path") else None
    conn = get_db(db_path)
    conn.close()
    yield


def create_app(config: dict | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: LadderBot configuration dictionary. If None, uses defaults.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="LadderBot Dashboard",
        description="Parlay ladder tracker and performance dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config on app state for route access
    app.state.config = config or {}
    app.state.db_path = None

    # CORS middleware — allow local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(picks_router)
    app.include_router(ladder_router)
    app.include_router(dashboard_router)

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Serve index.html at root
    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_STATIC_DIR / "index.html"))

    return app
