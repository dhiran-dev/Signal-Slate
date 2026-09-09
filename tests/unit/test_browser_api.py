"""Real PostgreSQL browser capability and full preview tests (no network models)."""

import pytest
from fastapi.testclient import TestClient
from signal_slate.api_routes import factory
from signal_slate.main import app
from signal_slate.persistence.models import BrowserSessionRecord
from sqlalchemy import delete


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
        cap = c.cookies.get("ss_cap")
        if cap:
            from signal_slate.api_routes import digest

            with factory()() as db, db.begin():
                db.execute(
                    delete(BrowserSessionRecord).where(
                        BrowserSessionRecord.capability_hash == digest(cap)
                    )
                )


def test_preview_complete_is_not_cloud_verification(client):
    result = client.post("/api/sessions", json={"mode": "preview"})
    assert result.status_code == 201
    assert "HttpOnly" in result.headers["set-cookie"]
    state = result.json()
    sid = state["id"]
    headers = {"X-CSRF-Token": state["csrf_token"]}

    def step(name, extra=None):
        nonlocal state
        response = client.post(
            f"/api/sessions/{sid}/{name}",
            headers=headers,
            json={"revision": state["revision"], **(extra or {})},
        )
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["error"] is None, state["error"]

    step("baseline")
    assert len(state["baseline"]["samples"]) == 484
    step("investigate")
    assert not state["finding"]["evidence_ids"]
    step("constraints", {"text": "Exclude channel 11"})
    constraints = [c | {"confirmed": True} for c in state["interpretation"]["constraints"]]
    step("confirm", {"constraints": constraints})
    plan = state["candidate_plans"][0]
    approval = {
        k: plan[k]
        for k in ("plan_id", "plan_version", "action_hash", "constraints_hash", "base_config_hash")
    }
    step("approve", {"approval": approval | {"approved": True}})
    step("apply")
    assert state["state"] == "PREVIEW_COMPLETE"
    assert state["verification"]["terminal_status"] == "INCONCLUSIVE"
    assert len(state["comparison"]["samples"]) == 484
    # GET uses durable snapshot after the request's orchestrator is gone.
    assert client.get(f"/api/sessions/{sid}").json() == state


def test_ownership_csrf_revision_and_get_no_effects(client):
    state = client.post("/api/sessions", json={}).json()
    sid = state["id"]
    url = f"/api/sessions/{sid}/baseline"
    assert client.post(url, json={"revision": 0}).status_code == 403
    headers = {"X-CSRF-Token": state["csrf_token"]}
    assert (
        client.post(
            url, json={"revision": 0}, headers=headers | {"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert client.post(url, json={"revision": 7}, headers=headers).status_code == 409
    with TestClient(app) as foreign:
        assert foreign.get(f"/api/sessions/{sid}").status_code == 404
        assert foreign.post(url, json={"revision": 0}, headers=headers).status_code == 404
    assert client.get(f"/api/sessions/{sid}").json()["revision"] == 0
    assert client.post(url, json={"revision": 0}, headers=headers).status_code == 200
    assert client.post(url, json={"revision": 0}, headers=headers).status_code == 409


def test_confirmation_cannot_inject_other_constraint(client):
    state = client.post("/api/sessions", json={}).json()
    sid = state["id"]
    headers = {"X-CSRF-Token": state["csrf_token"]}
    for operation, extra in (
        ("baseline", {}),
        ("investigate", {}),
        ("constraints", {"text": "Exclude channel 11"}),
    ):
        state = client.post(
            f"/api/sessions/{sid}/{operation}",
            headers=headers,
            json={"revision": state["revision"], **extra},
        ).json()
    constraint = state["interpretation"]["constraints"][0] | {
        "confirmed": True,
        "parameters": {"excluded_channel": 12},
    }
    state = client.post(
        f"/api/sessions/{sid}/confirm",
        headers=headers,
        json={"revision": state["revision"], "constraints": [constraint]},
    ).json()
    assert state["error"]["code"] == "ValueError"
    assert not state["candidate_plans"]


def test_vite_proxy_origin_is_exactly_allowlisted(client):
    response = client.post("/api/sessions", json={}, headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 201
    state = response.json()
    url = f"/api/sessions/{state['id']}/baseline"
    headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": state["csrf_token"]}
    assert client.post(url, json={"revision": 0}, headers=headers).status_code == 200
    for origin in ("http://localhost:5173.evil.invalid", "https://evil.invalid", "null"):
        assert (
            client.post(
                "/api/sessions", json={}, headers={"Origin": origin, "X-Forwarded-Host": origin}
            ).status_code
            == 403
        )


def test_configured_origins_replace_local_defaults(client, monkeypatch):
    monkeypatch.setenv("SIGNAL_SLATE_ALLOWED_ORIGINS", "https://rehearsal.example")
    assert (
        client.post(
            "/api/sessions", json={}, headers={"Origin": "http://127.0.0.1:5173"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sessions", json={}, headers={"Origin": "https://rehearsal.example"}
        ).status_code
        == 201
    )
    assert (
        client.post("/api/sessions", json={}, headers={"Origin": "http://testserver"}).status_code
        == 403
    )


def test_secure_cookie_when_tls_ends_at_reverse_proxy(client, monkeypatch):
    monkeypatch.setenv("SIGNAL_SLATE_SECURE_COOKIES", "true")
    response = client.post("/api/sessions", json={"mode": "preview"})
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["AMBIGUOUS", "UNSUPPORTED", "CONTRADICTORY"])
async def test_paused_live_constraint_retains_interpretation(monkeypatch, kind):
    from signal_slate.api_routes import Command, execute_live
    from signal_slate.domain.models import ConstraintInterpretation
    from signal_slate.workflow.orchestrator import (
        AmbiguousConstraintError,
        ContradictoryConstraintError,
        UnsupportedConstraintError,
    )

    errors = {
        "AMBIGUOUS": AmbiguousConstraintError,
        "UNSUPPORTED": UnsupportedConstraintError,
        "CONTRADICTORY": ContradictoryConstraintError,
    }

    class FakeWorkflow:
        def __init__(self, **kwargs):
            self._runs = {}

        async def interpret_constraint(self, sid, text):
            self._runs[sid]["interpretation"] = ConstraintInterpretation(
                status=kind, constraints=[], rationale="Clarify the channel constraint."
            )
            raise errors[kind]("Pause")

    monkeypatch.setattr("signal_slate.api_routes.LiveWorkflowOrchestrator", FakeWorkflow)
    snapshot = {"workflow": {}, "public": {}}
    await execute_live(
        "constraints", "test", Command(revision=0, text="change something"), snapshot
    )
    assert snapshot["public"]["interpretation"]["status"] == kind
    assert snapshot["workflow"]["interpretation"]["status"] == kind


def test_run_and_report_reads_are_owned_and_do_not_export_credentials(client):
    state = client.post("/api/sessions", json={}).json()
    sid = state["id"]
    state = client.post(
        f"/api/sessions/{sid}/baseline",
        json={"revision": 0},
        headers={"X-CSRF-Token": state["csrf_token"]},
    ).json()
    run = state["baseline"]["run_id"]
    assert client.get(f"/api/sessions/{sid}/evidence/{run}").json() == state["baseline"]
    assert client.get(f"/api/sessions/{sid}/evidence/foreign-run").status_code == 404
    report = client.get(f"/api/sessions/{sid}/report")
    assert report.headers["Cache-Control"] == "no-store"
    assert report.json()["baseline"] == state["baseline"]
    assert not {"csrf_token", "workflow", "fault_nonce", "fault_family"} & report.json().keys()
    with TestClient(app) as foreign:
        assert foreign.get(f"/api/sessions/{sid}/report").status_code == 404
        assert foreign.get(f"/api/sessions/{sid}/evidence/{run}").status_code == 404
