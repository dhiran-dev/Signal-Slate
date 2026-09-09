"""Serve the compiled workspace alongside the API in the application container."""

import re
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

WORKSPACE_ROUTE = re.compile(r"^(?:\.|rehearsal(?:/[A-Za-z0-9_-]+)?|reports?(?:/[A-Za-z0-9_-]+)?)$")


class WorkspaceFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # Missing assets and unknown API paths must remain real 404 responses.
            if exc.status_code != 404 or not WORKSPACE_ROUTE.fullmatch(path):
                raise
            response = await super().get_response("index.html", scope)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        )
        return response


def mount_workspace(app: FastAPI, directory: str) -> None:
    root = Path(directory).resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError("Compiled frontend is missing from SIGNAL_SLATE_STATIC_DIR")
    # Register last, after all API and health routes.
    app.mount("/", WorkspaceFiles(directory=root, html=True), name="workspace")
