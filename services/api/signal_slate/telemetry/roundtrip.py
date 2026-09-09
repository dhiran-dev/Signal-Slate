"""Publish an immutable rehearsal outbox and independently collect cloud evidence."""

import asyncio
import time
from datetime import UTC, datetime

from signal_slate.application.checkpoints import publication_store
from signal_slate.domain.models import (
    EvidenceContext,
    EvidenceManifest,
    MicSample,
    ObservedRun,
    PerSecondMetric,
    RunConfig,
    ShotContext,
)
from signal_slate.evidence.mcp_client import GrafanaMcpClient
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.telemetry.publisher import GrafanaTelemetryPublisher


async def publish_and_collect(
    config: RunConfig,
    run_id: str,
    session_id: str,
    evidence_context: EvidenceContext,
    publisher: GrafanaTelemetryPublisher,
    mcp_client: GrafanaMcpClient,
    context: ShotContext,
    seed: int = 42,
    simulate_missing_final_sample: bool = False,
    simulate_publish_failure: bool = False,
    fault_family: str = "channel_interference",
) -> ObservedRun:
    if evidence_context.session_id != session_id:
        raise ValueError("Evidence context belongs to another session.")
    store = publication_store.get()
    existing = store.load(run_id) if store else None
    if existing:
        payload = existing["payload"]
        if payload["session_id"] != session_id or payload["config_hash"] != config.config_hash:
            raise ValueError("Publication identity changed")
    else:
        engine = SimulatorEngine(context, fault_family=fault_family)
        end = time.time()
        start = end - context.duration_ms / 1000
        manifest = engine.create_prepublication_manifest(
            run_id,
            session_id,
            config,
            evidence_context,
            created_at_rfc3339=datetime.fromtimestamp(start, UTC).isoformat(),
        )
        samples, metrics, events = engine.run_rehearsal(
            config,
            seed=seed,
            start_time_sec=start,
            session_id=session_id,
            run_id=run_id,
        )
        events = [e for e in events if e.get("event") != "run_completed"]
        events.append(
            {
                "event": "run_completed",
                "offset_ms": context.duration_ms,
                "samples_count": manifest.sample_count,
                "metrics_count": manifest.metric_count,
                "manifest_hash": manifest.manifest_hash,
            }
        )
        payload = {
            "run_id": run_id,
            "session_id": session_id,
            "config_hash": config.config_hash,
            "start": start,
            "end": end,
            "manifest": manifest.model_dump(mode="json"),
            "samples": [s.model_dump(mode="json") for s in samples],
            "metrics": [m.model_dump(mode="json") for m in metrics],
            "events": events,
        }
        if store:
            store.seal(run_id, session_id, payload)
    manifest = EvidenceManifest.model_validate(payload["manifest"])

    async def collect(timeout: int) -> ObservedRun:
        return await mcp_client.collect_observed_run(
            run_id,
            session_id,
            payload["start"],
            payload["end"],
            expected_manifest=manifest,
            timeout_seconds=timeout,
        )

    if existing and existing["attempts"]:
        # The provider may have accepted a prior push before our process died.
        # Check independently before replay; never generate a new timestamp/payload.
        try:
            observed = await collect(5)
            if (
                observed.retrieved_sample_count == manifest.sample_count
                and len(observed.metrics) == manifest.metric_count
                and observed.completion_marker_present
                and not observed.is_truncated
            ):
                store.mark(run_id, "OBSERVED")
                return observed
        except Exception:
            pass  # Bounded identical replay, not a local-evidence fallback.
    if store:
        store.mark(run_id, "DISPATCHING")
    await asyncio.to_thread(
        publisher.publish_run,
        run_id=run_id,
        session_id=session_id,
        config_hash=config.config_hash,
        samples=[MicSample.model_validate(s) for s in payload["samples"]],
        metrics=[PerSecondMetric.model_validate(m) for m in payload["metrics"]],
        events=payload["events"],
        base_timestamp_sec=payload["end"],
        manifest=manifest,
        simulate_missing_final_sample=simulate_missing_final_sample,
        simulate_publish_failure=simulate_publish_failure,
    )
    if store:
        store.mark(run_id, "PUBLISHED")
    observed = await collect(30)
    if store:
        store.mark(run_id, "OBSERVED")
    return observed
