"""FastAPI app: JSON API under /api, the built UI (frontend/dist) at /, background jobs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tamadesk.api import jobs
from tamadesk.api.modules import router as modules_router
from tamadesk.api.routes import router
from tamadesk.core import db
from tamadesk.core.config import get_settings

DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(scheduler: bool = True) -> FastAPI:
    s = get_settings()
    conn = db.connect(s.db_path)
    db.migrate(conn)
    conn.close()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if scheduler:
            jobs.start(s)
        yield
        jobs.stop()

    app = FastAPI(title="tamadesk", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    app.include_router(router)
    app.include_router(modules_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
    return app
