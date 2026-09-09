"""Presentation helpers expose factual setup and owned evidence without dispatching work."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from signal_slate.api_routes import digest, factory
from signal_slate.application import presentation
from signal_slate.main import app
from signal_slate.persistence.models import BrowserSessionRecord
from sqlalchemy import delete


@pytest.fixture
def reader(monkeypatch):
    value = SimpleNamespace(
        read_token="PRIVATE_READ_TOKEN",
        grafana_url="https://example.grafana.net",
        prom_uid="metrics-uid",
        loki_uid="logs-uid",
    )
    monkeypatch.setattr(presentation, "GrafanaMcpClient", lambda: value)
    return value


def test_readiness_is_configuration_only_and_contains_no_secrets(monkeypatch, tmp_path, reader):
    monkeypatch.setattr(
        presentation,
        "get_settings",
        lambda: SimpleNamespace(google_cloud_project="project", gemini_model="model"),
    )
    monkeypatch.setattr(
        presentation,
        "GrafanaTelemetryPublisher",
        lambda: SimpleNamespace(
            write_token="PRIVATE_WRITE_TOKEN",
            otlp_endpoint="https://metrics",
            loki_push_url="https://logs",
        ),
    )
    adc = tmp_path / "adc.json"
    adc.write_text("NOT EVEN A VALID TOKEN; THE ENDPOINT ONLY CHECKS FILE PRESENCE")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc))
    monkeypatch.setenv("SIGNAL_SLATE_RUNTIME_ENABLED", "true")
    result = presentation.readiness()
    assert result == {
        "live_available": True,
        "runtime_enabled": True,
        "gemini": {"configured": True},
        "grafana": {"configured": True},
        "missing": [],
    }
    assert "PRIVATE" not in json.dumps(result)
    assert "connected" not in json.dumps(result)
    adc.unlink()
    reader.read_token = ""
    monkeypatch.setenv("SIGNAL_SLATE_RUNTIME_ENABLED", "false")
    result = presentation.readiness()
    assert not result["live_available"]
    assert not result["gemini"]["configured"]
    assert not result["grafana"]["configured"]
    assert len(result["missing"]) == 3


def test_grafana_links_pin_both_sources_to_the_owned_run_and_time(reader):
    run = {
        "run_id": "run-123",
        "start_time_rfc3339": "2026-09-09T10:00:00+00:00",
        "end_time_rfc3339": "2026-09-09T10:00:12+00:00",
    }
    result = presentation.evidence_links({"mode": "live", "baseline": run}, "session-123")
    assert result["source"] == "grafana"
    assert [link["label"] for link in result["links"]] == ["Before"]
    parsed = urlsplit(result["links"][0]["url"])
    assert parsed.netloc == "example.grafana.net"
    query = parse_qs(parsed.query)
    assert query["schemaVersion"] == ["1"]
    panes = json.loads(query["panes"][0])
    for pane in panes.values():
        assert 'run_id="run-123"' in pane["queries"][0]["expr"]
        assert 'session_id="session-123"' in pane["queries"][0]["expr"]
        assert int(pane["range"]["to"]) - int(pane["range"]["from"]) == 72000
    assert {p["datasource"] for p in panes.values()} == {"metrics-uid", "logs-uid"}
    assert "PRIVATE_READ_TOKEN" not in result["links"][0]["url"]
    assert presentation.evidence_links({"mode": "preview", "baseline": run}, "session-123") == {
        "source": "preview",
        "links": [],
    }
    assert (
        presentation.evidence_links(
            {"mode": "live", "baseline": {"run_id": "untimed"}}, "session-123"
        )["links"]
        == []
    )
    reader.grafana_url = "https://secret:password@example.grafana.net"
    assert (
        presentation.evidence_links({"mode": "live", "baseline": run}, "session-123")["links"] == []
    )


def test_evidence_links_endpoint_enforces_ownership_and_is_read_only():
    with TestClient(app) as owner, TestClient(app) as other:
        state = owner.post("/api/sessions", json={"mode": "preview", "preset": "b"}).json()
        try:
            assert state["preset"] == "b"
            url = f"/api/sessions/{state['id']}/evidence-links"
            response = owner.get(url)
            assert response.json() == {"source": "preview", "links": []}
            assert response.headers["cache-control"] == "no-store"
            assert other.get(url).status_code == 404
            assert owner.get(f"/api/sessions/{state['id']}").json() == state
        finally:
            with factory()() as db, db.begin():
                db.execute(
                    delete(BrowserSessionRecord).where(
                        BrowserSessionRecord.capability_hash == digest(owner.cookies["ss_cap"])
                    )
                )
