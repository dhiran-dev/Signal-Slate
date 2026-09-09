"""FastAPI application entrypoint for Signal Slate."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from signal_slate.api_routes import router
from signal_slate.config import get_settings
from signal_slate.readiness_health import database_available
from signal_slate.static_web import mount_workspace

app = FastAPI(
    title="Signal Slate API",
    version="0.1.0",
    description="Production sound rehearsal workflow sandbox",
)


@app.middleware("http")
async def private_api_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/health")
def get_health() -> dict[str, str]:
    """Health check endpoint returning system status and project identifier."""
    settings = get_settings()
    return {
        "status": "ok",
        "project": settings.google_cloud_project,
    }


@app.get("/ready", include_in_schema=False)
def get_ready():
    available = database_available()
    return JSONResponse(
        {"status": "ok" if available else "unavailable"},
        status_code=200 if available else 503,
        headers={"Cache-Control": "no-store"},
    )


app.include_router(router)

if static_directory := os.getenv("SIGNAL_SLATE_STATIC_DIR"):
    mount_workspace(app, static_directory)
