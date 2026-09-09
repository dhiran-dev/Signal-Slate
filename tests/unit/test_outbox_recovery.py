"""Publication success followed by process death must replay stable evidence identity."""

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime

import pytest
from signal_slate.api_routes import factory
from signal_slate.application.checkpoints import publication_store
from signal_slate.domain.models import ObservedRun, RunConfig, ShotContext, create_evidence_context
from signal_slate.persistence.models import PublicationOutbox
from signal_slate.persistence.outbox import OutboxStore
from signal_slate.telemetry.roundtrip import publish_and_collect
from sqlalchemy import delete


@pytest.mark.asyncio
async def test_remote_acceptance_before_process_death_uses_same_outbox(tmp_path):
    run_id = f"recovery-{uuid.uuid4().hex}"
    sid = uuid.uuid4().hex
    config = RunConfig()
    context = ShotContext()
    evidence, _ = create_evidence_context(sid, config)
    store = OutboxStore(factory())
    accepted = tmp_path / "remote-accepted.json"
    calls = []

    class Publisher:
        def publish_run(self, **kwargs):
            calls.append(kwargs)
            # Child process stands in for a worker dying after remote acceptance.
            # The durable outbox already exists before the child is started.
            script = (
                "import os,sys; from pathlib import Path; "
                "Path(sys.argv[1]).write_text(sys.argv[2]); os._exit(17)"
            )
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(accepted),
                    json.dumps(
                        {"run_id": kwargs["run_id"], "timestamp": kwargs["base_timestamp_sec"]}
                    ),
                ],
                check=False,
            )
            assert child.returncode == 17
            raise SystemExit("Worker exited before publication checkpoint")

    class Mcp:
        async def collect_observed_run(self, rid, session, start, end, expected_manifest, **kwargs):
            assert accepted.exists()
            assert json.loads(accepted.read_text()) == {"run_id": rid, "timestamp": end}
            payload = store.load(rid)["payload"]
            return ObservedRun(
                run_id=rid,
                session_id=session,
                config_hash=config.config_hash,
                samples=payload["samples"],
                metrics=payload["metrics"],
                completion_marker_present=True,
                retrieved_sample_count=484,
                start_time_rfc3339=datetime.fromtimestamp(start, UTC).isoformat(),
                end_time_rfc3339=datetime.fromtimestamp(end, UTC).isoformat(),
                manifest=expected_manifest,
                source_audio_hash=expected_manifest.source_audio_hash,
                scenario_path_hash=expected_manifest.scenario_path_hash,
                fault_commitment_hash=expected_manifest.fault_commitment_hash,
            )

    token = publication_store.set(store)
    try:
        with pytest.raises(SystemExit):
            await publish_and_collect(config, run_id, sid, evidence, Publisher(), Mcp(), context)
        old_payload = store.load(run_id)["payload"]
        assert store.load(run_id)["status"] == "DISPATCHING"
        result = await publish_and_collect(
            config, run_id, sid, evidence, Publisher(), Mcp(), context
        )
        assert result.retrieved_sample_count == 484
        assert len(calls) == 1  # No second push after independent completion was observed.
        assert store.load(run_id)["payload"] == old_payload
        assert store.load(run_id)["status"] == "OBSERVED"
        with pytest.raises(ValueError, match="different data"):
            store.seal(run_id, sid, old_payload | {"end": 0})
    finally:
        publication_store.reset(token)
        with factory()() as db, db.begin():
            db.execute(delete(PublicationOutbox).where(PublicationOutbox.run_id == run_id))


def test_outbox_integrity_and_retry_bound():
    run_id = uuid.uuid4().hex
    store = OutboxStore(factory())
    try:
        store.seal(run_id, "test", {"immutable": True})
        for _ in range(3):
            store.mark(run_id, "DISPATCHING")
        with pytest.raises(ValueError, match="attempt limit"):
            store.mark(run_id, "DISPATCHING")
        with factory()() as db, db.begin():
            db.get(PublicationOutbox, run_id).payload = {"tampered": True}
        with pytest.raises(ValueError, match="integrity"):
            store.load(run_id)
    finally:
        with factory()() as db, db.begin():
            db.execute(delete(PublicationOutbox).where(PublicationOutbox.run_id == run_id))
