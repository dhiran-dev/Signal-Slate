"""Privacy regressions for browser payloads, tracked source and production bundles."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from signal_slate.api_routes import digest, factory, public
from signal_slate.main import app
from signal_slate.persistence.models import BrowserSessionRecord
from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = (b"signal-slate-private", b"MAIN-IMPLEMENTATION-PLAN", b"/Users/", b"/var/folders/")


def configured_secrets() -> list[bytes]:
    """Read only locally configured secret values; never include values in test output."""
    values: list[bytes] = []
    for path in (
        Path.home() / ".config/signal-slate/app.env",
        Path.home() / ".config/signal-slate/grafana.env",
    ):
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, value = line.split("=", 1)
            if any(key in name.upper() for key in ("TOKEN", "SECRET", "PASSWORD", "DATABASE_URL")):
                value = value.strip().strip("\"'")
                if len(value) >= 12:
                    values.append(value.encode())
    for name, value in os.environ.items():
        if (
            name.startswith(("GRAFANA_", "SIGNAL_SLATE_"))
            and any(key in name for key in ("TOKEN", "SECRET", "PASSWORD"))
            and len(value) >= 12
        ):
            values.append(value.encode())
    return values


def assert_no_configured_secret(blob: bytes, label: str) -> None:
    for secret in configured_secrets():
        if secret in blob:
            raise AssertionError(f"Configured secret detected in {label}; value withheld")


def test_tracked_source_contains_no_configured_secret():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    for raw in paths:
        if not raw:
            continue
        path = ROOT / raw.decode()
        if path.is_file():
            assert_no_configured_secret(path.read_bytes(), "tracked source")


def test_only_application_readme_is_tracked_markdown():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    markdown = {
        raw.decode()
        for raw in paths
        if raw and Path(raw.decode()).suffix.lower() in {".md", ".markdown"}
    }
    assert markdown == {"README.md"}


def test_production_bundle_contains_no_private_paths_or_secrets():
    files = list((ROOT / "apps/web/dist").rglob("*"))
    assert any(path.suffix == ".js" for path in files), "Build frontend before privacy checks"
    for path in files:
        if path.is_file():
            blob = path.read_bytes()
            assert_no_configured_secret(blob, "production bundle")
            if any(marker in blob for marker in FORBIDDEN):
                raise AssertionError("Private development path detected in production bundle")


def test_public_projection_excludes_entire_private_workflow():
    sentinel = "private-sentinel-do-not-expose"
    rec = SimpleNamespace(
        id="public-id",
        revision=1,
        csrf_token="public-csrf",
        operation_token=None,
        snapshot={
            "public": {"state": "READY"},
            "workflow": {
                "fault_family": sentinel,
                "secret_nonce": sentinel,
                "raw_mcp": sentinel,
                "token": sentinel,
            },
        },
    )
    blob = json.dumps(public(rec)).encode()
    assert sentinel.encode() not in blob
    assert b"fault_family" not in blob and b"secret_nonce" not in blob


def test_preview_create_and_get_never_expose_private_configuration():
    with TestClient(app) as client:
        response = client.post("/api/sessions", json={"mode": "preview"})
        assert response.status_code == 201
        sid = response.json()["id"]
        try:
            for result in (response, client.get(f"/api/sessions/{sid}")):
                assert result.status_code in (200, 201)
                blob = result.content
                assert_no_configured_secret(blob, "browser response")
                for marker in (
                    b"secret_nonce",
                    b"fault_family",
                    b"raw_mcp",
                    b"GRAFANA_SERVICE_ACCOUNT_TOKEN",
                    *FORBIDDEN,
                ):
                    assert marker not in blob
                assert result.headers["cache-control"] == "no-store"
        finally:
            with factory()() as db, db.begin():
                db.execute(
                    delete(BrowserSessionRecord).where(
                        BrowserSessionRecord.capability_hash == digest(client.cookies.get("ss_cap"))
                    )
                )
