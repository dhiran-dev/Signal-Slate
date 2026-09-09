"""Deployment boundaries: static routing, database readiness and HTTPS configuration."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from signal_slate.container_startup import validate_environment
from signal_slate.main import app
from signal_slate.readiness_health import database_available
from signal_slate.static_web import mount_workspace


@pytest.fixture
def web_client(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    (root / "index.html").write_text("<html>Signal Slate</html>")
    (root / "assets").mkdir()
    (root / "assets/app-hash.js").write_text("console.log('app')")
    (root / "assets/sample-hash.wav").write_bytes(b"RIFF" + bytes(range(64)))
    (tmp_path / "private.txt").write_text("not public")
    application = FastAPI()

    @application.get("/api/known")
    def known():
        return {"api": True}

    mount_workspace(application, str(root))
    with TestClient(application) as client:
        yield client


@pytest.mark.parametrize(
    "path", ["/", "/rehearsal", "/rehearsal/abc123", "/report", "/reports/abc123"]
)
def test_workspace_deep_links_serve_uncached_html(web_client, path):
    response = web_client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>Signal Slate</html>"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path", ["/api/missing", "/assets/missing.js", "/.env", "/%2e%2e/private.txt"]
)
def test_missing_or_private_paths_never_return_workspace(web_client, path):
    response = web_client.get(path)
    assert response.status_code == 404
    assert "Signal Slate" not in response.text
    assert "not public" not in response.text


def test_static_mount_preserves_api_and_audio_range_requests(web_client):
    assert web_client.get("/api/known").json() == {"api": True}
    script = web_client.get("/assets/app-hash.js")
    assert script.status_code == 200
    assert "immutable" in script.headers["cache-control"]
    audio = web_client.get("/assets/sample-hash.wav", headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206
    assert audio.content == b"RIFF"
    assert audio.headers["content-range"] == "bytes 0-3/68"
    assert web_client.post("/rehearsal").status_code == 405


def test_readiness_returns_safe_failure_when_database_is_down(monkeypatch):
    monkeypatch.setattr("signal_slate.main.database_available", lambda: False)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_database_probe_bounds_timeouts_and_hides_driver_errors(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:private-value@host/db")
    connect = MagicMock(side_effect=RuntimeError("connection secret private-value"))
    monkeypatch.setattr("signal_slate.readiness_health.psycopg.connect", connect)
    assert database_available() is False
    assert connect.call_args.kwargs["connect_timeout"] == 2
    assert "statement_timeout=2000" in connect.call_args.kwargs["options"]


@pytest.fixture
def container_env(monkeypatch):
    monkeypatch.setenv("SIGNAL_SLATE_ENV_FILE", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@host/db?sslmode=require")
    monkeypatch.setenv("SIGNAL_SLATE_ALLOWED_ORIGINS", "https://sound.example.com")
    monkeypatch.setenv("SIGNAL_SLATE_SECURE_COOKIES", "true")


def test_valid_container_environment(container_env):
    validate_environment()


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "*",
        "https://sound.example.com/",
        "https://user:pass@host",
        "http://sound.example.com",
        "https://host:bad",
    ],
)
def test_container_rejects_invalid_production_origins(container_env, monkeypatch, origin):
    monkeypatch.setenv("SIGNAL_SLATE_ALLOWED_ORIGINS", origin)
    with pytest.raises(ValueError):
        validate_environment()


def test_local_http_requires_explicit_cookie_override(container_env, monkeypatch):
    monkeypatch.setenv("SIGNAL_SLATE_ALLOWED_ORIGINS", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SLATE_SECURE_COOKIES", "false")
    validate_environment()


def test_bad_database_url_does_not_expose_credentials(container_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:private-value@host:bad/db")
    with pytest.raises(ValueError) as error:
        validate_environment()
    assert "private-value" not in str(error.value)
