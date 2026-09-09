"""Real PostgreSQL idempotency, process interruption and fenced recovery checks."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from signal_slate.api_routes import assert_lease, digest, factory
from signal_slate.main import app
from signal_slate.persistence.models import BrowserSessionRecord, OperationRecord
from sqlalchemy import delete


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
        cap = client.cookies.get("ss_cap")
        if cap:
            with factory()() as db, db.begin():
                db.execute(
                    delete(BrowserSessionRecord).where(
                        BrowserSessionRecord.capability_hash == digest(cap)
                    )
                )


def start(client):
    state = client.post("/api/sessions", json={}).json()
    return state, {"X-CSRF-Token": state["csrf_token"], "Idempotency-Key": "test-intent"}


def test_identical_idempotency_returns_original_result_and_conflict_rejects(client):
    state, headers = start(client)
    path = f"/api/sessions/{state['id']}/baseline"
    first = client.post(path, json={"revision": 0}, headers=headers)
    replay = client.post(path, json={"revision": 0}, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert client.post(path, json={"revision": 1}, headers=headers).status_code == 409
    with factory()() as db:
        assert len(list(db.query(OperationRecord).filter_by(session_id=state["id"]))) == 1


def test_async_command_is_durable_and_get_has_no_side_effect(client, monkeypatch):
    import signal_slate.api_routes as routes

    state, headers = start(client)
    original = routes.execute_preview
    calls = []

    def checked(*args):
        # Claim/checkpoint transactions have ended before application execution.
        assert routes.factory().kw["bind"].pool.checkedout() == 0
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(routes, "execute_preview", checked)
    response = client.post(
        f"/api/sessions/{state['id']}/baseline",
        json={"revision": 0},
        headers=headers | {"Prefer": "respond-async"},
    )
    assert response.status_code == 202
    operation_id = response.json()["operation"]["id"]
    for _ in range(3):
        assert client.get(f"/api/operations/{operation_id}").json()["status"] == "PENDING"
        assert client.get(f"/api/sessions/{state['id']}").json()["busy"]
    assert calls == []
    resumed = client.post(
        f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
    )
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "BASELINE_READY"
    assert calls == ["baseline"]
    assert (
        client.post(
            f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
        ).json()
        == resumed.json()
    )
    assert calls == ["baseline"]


def test_expired_lease_resumes_and_fences_old_holder(client):
    state, headers = start(client)
    response = client.post(
        f"/api/sessions/{state['id']}/baseline",
        json={"revision": 0},
        headers=headers | {"Prefer": "respond-async"},
    )
    operation_id = response.json()["operation"]["id"]
    with factory()() as db, db.begin():
        op = db.get(OperationRecord, operation_id)
        op.status, op.fence, op.lease_owner = "RUNNING", 1, "dead-process"
        op.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get(f"/api/operations/{operation_id}").json()["resumable"]
    result = client.post(
        f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
    )
    assert result.status_code == 200
    with factory()() as db, db.begin():
        assert db.get(OperationRecord, operation_id).fence == 2
        with pytest.raises(HTTPException) as error:
            assert_lease(db, operation_id, "dead-process", 1)
        assert error.value.status_code == 409


def test_unexpired_lease_and_foreign_resume_rejected(client):
    state, headers = start(client)
    response = client.post(
        f"/api/sessions/{state['id']}/baseline",
        json={"revision": 0},
        headers=headers | {"Prefer": "respond-async"},
    )
    operation_id = response.json()["operation"]["id"]
    with factory()() as db, db.begin():
        op = db.get(OperationRecord, operation_id)
        op.status, op.fence, op.lease_owner = "RUNNING", 1, "live-process"
        op.lease_expires_at = datetime.now(UTC) + timedelta(seconds=180)
    assert (
        client.post(
            f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
        ).status_code
        == 409
    )
    with TestClient(app) as stranger:
        assert stranger.get(f"/api/operations/{operation_id}").status_code == 404
        assert (
            stranger.post(
                f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
            ).status_code
            == 404
        )
    assert (
        client.post(f"/api/operations/{operation_id}/resume", json={"revision": 0}).status_code
        == 403
    )


def test_process_death_keeps_durable_operation_for_explicit_restart(client):
    import subprocess
    import sys

    state, headers = start(client)
    pending = client.post(
        f"/api/sessions/{state['id']}/baseline",
        json={"revision": 0},
        headers=headers | {"Prefer": "respond-async"},
    ).json()
    operation_id = pending["operation"]["id"]
    script = """
import os, sys
from datetime import UTC, datetime, timedelta
from signal_slate.api_routes import factory
from signal_slate.persistence.models import OperationRecord
with factory()() as db, db.begin():
    op = db.get(OperationRecord, sys.argv[1])
    op.status, op.fence, op.lease_owner = 'RUNNING', 1, 'terminated-process'
    op.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
os._exit(17)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, operation_id], capture_output=True, check=False
    )
    assert child.returncode == 17
    with TestClient(app) as restarted:
        restarted.cookies.update(client.cookies)
        result = restarted.post(
            f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
        )
        assert result.json()["state"] == "BASELINE_READY"
        assert len(result.json()["baseline"]["samples"]) == 484


def test_concurrent_stale_worker_cannot_commit_after_takeover(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    import signal_slate.api_routes as routes

    state, headers = start(client)
    entered, release = Event(), Event()
    mutex = Lock()
    call_count = 0
    original = routes.execute_preview

    def stalled(*args):
        nonlocal call_count
        with mutex:
            call_count += 1
            call = call_count
        if call == 1:
            entered.set()
            assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(routes, "execute_preview", stalled)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            client.post,
            f"/api/sessions/{state['id']}/baseline",
            json={"revision": 0},
            headers=headers,
        )
        assert entered.wait(10)
        with factory()() as db, db.begin():
            rec = db.get(BrowserSessionRecord, state["id"])
            operation_id = rec.operation_token
            op = db.get(OperationRecord, operation_id)
            op.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with TestClient(app) as replacement:
            replacement.cookies.update(client.cookies)
            resumed = replacement.post(
                f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
            )
            assert resumed.status_code == 200
        release.set()
        assert first.result(timeout=10).status_code == 409
    final = client.get(f"/api/sessions/{state['id']}").json()
    assert final["revision"] == 1
    assert final["state"] == "BASELINE_READY"
    assert final["baseline"] == resumed.json()["baseline"]


def test_failed_conflict_replay_preserves_status_without_reexecution(client, monkeypatch):
    import signal_slate.api_routes as routes
    from signal_slate.workflow.orchestrator import WorkflowStateError

    calls = []

    def conflict(*args):
        calls.append(args[0])
        raise WorkflowStateError("stale state")

    monkeypatch.setattr(routes, "execute_preview", conflict)
    state, headers = start(client)
    path = f"/api/sessions/{state['id']}/baseline"
    first = client.post(path, json={"revision": 0}, headers=headers)
    replay = client.post(path, json={"revision": 0}, headers=headers)
    assert first.status_code == replay.status_code == 409
    assert first.json() == replay.json()
    with factory()() as db:
        op = db.query(OperationRecord).filter_by(session_id=state["id"]).one()
        operation_id = op.id
    resumed = client.post(
        f"/api/operations/{operation_id}/resume", json={"revision": 0}, headers=headers
    )
    assert resumed.status_code == 409
    assert resumed.json() == first.json()
    assert calls == ["baseline"]
