"""Complete manifest-bound fixtures exercise independent evidence verification.

These are unit fixtures, not a claim of cloud execution. Live evidence is checked
separately. No selected family is passed to the verifier.
"""

from datetime import UTC, datetime, timedelta

import pytest
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    ObservedRun,
    RunConfig,
    ShotContext,
    actions_hash,
    create_evidence_context,
)
from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.verification.verifier import DeterministicVerifier


def evidence_pair(family, action, config):
    now = datetime.now(UTC)
    start = now - timedelta(seconds=12)
    base = RunConfig()
    context, _ = create_evidence_context("verification-case", base, fault_family=family)
    engine = SimulatorEngine(fault_family=family)
    runs = []
    for run_id, run_config in [("baseline", base), ("comparison", config)]:
        samples, metrics, _ = engine.run_rehearsal(
            run_config,
            start_time_sec=start.timestamp(),
            session_id=context.session_id,
            run_id=run_id,
        )
        manifest = context.create_manifest(
            run_id, run_config.config_hash, created_at_rfc3339=start.isoformat()
        )
        runs.append(
            ObservedRun(
                run_id=run_id,
                session_id=context.session_id,
                config_hash=run_config.config_hash,
                samples=samples,
                metrics=metrics,
                completion_marker_present=True,
                retrieved_sample_count=len(samples),
                start_time_rfc3339=start.isoformat(),
                end_time_rfc3339=now.isoformat(),
                manifest=manifest,
                source_audio_hash=manifest.source_audio_hash,
                scenario_path_hash=manifest.scenario_path_hash,
                fault_commitment_hash=manifest.fault_commitment_hash,
            )
        )
    plan = CandidatePlan(
        plan_id="approved",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="empty",
        base_config_hash=base.config_hash,
        rationale="Test a hypothesis",
    )
    return runs[0], runs[1], plan, now


def verify(family, action, config, constraints=None):
    baseline, comparison, plan, now = evidence_pair(family, action, config)
    return DeterministicVerifier().verify_run(
        baseline, comparison, plan, constraints or [], config.config_hash, now
    )


def action(kind, parameters=None):
    return CandidateAction(action_type=kind, mic_id="mic_1", parameters=parameters or {})


@pytest.mark.parametrize("family", ["channel_interference", "antenna_shadow", "audio_clipping"])
def test_no_action_control_is_complete_but_not_repaired(family):
    result = verify(family, action("NO_ACTION"), RunConfig())
    assert result.completeness_passed and result.crosscheck_passed
    assert result.terminal_status == "NOT_VERIFIED"
    assert not result.thresholds_passed and not result.dialogue_coverage_passed


@pytest.mark.parametrize("family", ["channel_interference", "antenna_shadow", "audio_clipping"])
def test_backup_covers_dialogue_but_never_claims_rf_fixed(family):
    result = verify(
        family,
        action("BOOM_COVERAGE", {"source_mic": "mic_4"}),
        RunConfig(backup_sources={"mic_1": "mic_4"}),
    )
    assert result.terminal_status == "NOT_VERIFIED"
    assert result.completeness_passed and result.crosscheck_passed
    assert not result.thresholds_passed and result.dialogue_coverage_passed
    assert result.details["coverage_summary"] == "Dialogue covered; receiver issue remains"
    assert result.details["selected_dialogue_sources"]["mic_1"] == "mic_4"


@pytest.mark.parametrize(
    "family,kind,params,config",
    [
        (
            "channel_interference",
            "CHANNEL_SWITCH",
            {"channel": 12},
            RunConfig(channel_assignments={"mic_1": 12}),
        ),
        ("antenna_shadow", "ANTENNA_SWITCH", {"antenna": "B"}, RunConfig(antenna_selection="B")),
    ],
)
def test_only_correct_mechanism_receives_verified(family, kind, params, config):
    assert verify(family, action(kind, params), config).terminal_status == "VERIFIED"


@pytest.mark.parametrize(
    "family,kind,params,config",
    [
        (
            "antenna_shadow",
            "CHANNEL_SWITCH",
            {"channel": 12},
            RunConfig(channel_assignments={"mic_1": 12}),
        ),
        (
            "channel_interference",
            "ANTENNA_SWITCH",
            {"antenna": "B"},
            RunConfig(antenna_selection="B"),
        ),
        ("audio_clipping", "ANTENNA_SWITCH", {"antenna": "B"}, RunConfig(antenna_selection="B")),
        (
            "audio_clipping",
            "CHANNEL_SWITCH",
            {"channel": 12},
            RunConfig(channel_assignments={"mic_1": 12}),
        ),
        (
            "healthy",
            "CHANNEL_SWITCH",
            {"channel": 999},
            RunConfig(channel_assignments={"mic_1": 999}),
        ),
    ],
)
def test_wrong_or_harmful_action_is_not_verified(family, kind, params, config):
    result = verify(family, action(kind, params), config)
    assert result.terminal_status == "NOT_VERIFIED"
    assert not result.thresholds_passed


def test_healthy_no_action_does_not_require_invented_config_change():
    assert verify("healthy", action("NO_ACTION"), RunConfig()).terminal_status == "VERIFIED"


def test_backup_without_approved_routing_cannot_cover_dialogue():
    result = verify(
        "audio_clipping", action("NO_ACTION"), RunConfig(backup_sources={"mic_1": "mic_4"})
    )
    assert not result.dialogue_coverage_passed


def test_missing_backup_sample_makes_coverage_inconclusive():
    config = RunConfig(backup_sources={"mic_1": "mic_4"})
    baseline, comparison, plan, now = evidence_pair(
        "audio_clipping", action("BOOM_COVERAGE", {"source_mic": "mic_4"}), config
    )
    comparison.samples = [
        s for s in comparison.samples if not (s.mic_id == "mic_4" and s.offset_ms == 4900)
    ]
    result = DeterministicVerifier().verify_run(
        baseline, comparison, plan, [], config.config_hash, now
    )
    assert result.terminal_status == "INCONCLUSIVE"
    assert not result.dialogue_coverage_passed


def test_unavailable_backup_does_not_cover_dialogue_even_with_complete_evidence():
    config = RunConfig(
        backup_sources={"mic_1": "mic_4"}, channel_assignments={"mic_1": 10, "mic_4": 999}
    )
    result = verify("audio_clipping", action("BOOM_COVERAGE", {"source_mic": "mic_4"}), config)
    assert result.terminal_status == "NOT_VERIFIED" and not result.dialogue_coverage_passed


def test_tampered_backup_action_hash_is_inconclusive():
    config = RunConfig(backup_sources={"mic_1": "mic_4"})
    baseline, comparison, plan, now = evidence_pair(
        "audio_clipping", action("BOOM_COVERAGE", {"source_mic": "mic_4"}), config
    )
    plan.action_hash = "tampered"
    assert (
        DeterministicVerifier()
        .verify_run(baseline, comparison, plan, [], config.config_hash, now)
        .terminal_status
        == "INCONCLUSIVE"
    )


def constraint(kind, params=None):
    return Constraint(
        constraint_id="c",
        kind=kind,
        target_mic="mic_1",
        parameters=params or {},
        source_text="Keep this setup",
        exact_source_span="Keep this setup",
        confirmed=True,
    )


def test_boom_exclusion_and_rig_lock_have_distinct_meanings():
    config = RunConfig(backup_sources={"mic_1": "mic_4"})
    backup = action("BOOM_COVERAGE", {"source_mic": "mic_4"})
    assert verify("audio_clipping", backup, config, [constraint("RIG_LOCK")]).constraints_passed
    assert not verify(
        "audio_clipping", backup, config, [constraint("BOOM_EXCLUSION")]
    ).constraints_passed


def test_antenna_lock_matches_authoritative_schema_and_value():
    config = RunConfig(antenna_selection="B")
    switch = action("ANTENNA_SWITCH", {"antenna": "B"})
    assert (
        verify(
            "antenna_shadow", switch, config, [constraint("ANTENNA_LOCK", {"locked_antenna": "B"})]
        ).terminal_status
        == "VERIFIED"
    )
    assert not verify(
        "antenna_shadow", switch, config, [constraint("ANTENNA_LOCK", {"locked_antenna": "A"})]
    ).constraints_passed
    assert not verify(
        "antenna_shadow", switch, config, [constraint("ANTENNA_LOCK")]
    ).constraints_passed


def test_model_receives_clipping_measurements_not_hidden_fault_family():
    baseline, _, _, _ = evidence_pair("audio_clipping", action("NO_ACTION"), RunConfig())
    wrapper = BoundedModelEvidenceWrapper(baseline, ShotContext())
    rows = wrapper.get_run_metrics(baseline.run_id, ["mic_1"], 4000, 7000)
    assert any(r["value"]["clipping_duration_ms"] > 0 for r in rows)
    assert all(r["value"]["dropout_duration_ms"] == 0 for r in rows)
    events = wrapper.get_run_events(baseline.run_id, ["mic_1"], 4900, 6800)
    assert events and all(e["value"]["is_clipped"] for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_kind", ["identical", "timestamp_conflict"])
async def test_collector_audits_duplicate_samples(duplicate_kind):
    from unittest.mock import AsyncMock

    from signal_slate.evidence.mcp_client import GrafanaMcpClient

    baseline, _, _, now = evidence_pair("healthy", action("NO_ACTION"), RunConfig())
    entries = [{"event": "sample", **s.model_dump()} for s in baseline.samples]
    duplicate = dict(entries[0])
    if duplicate_kind == "timestamp_conflict":
        duplicate["timestamp_rfc3339"] = now.isoformat()
    entries.append(duplicate)
    client = GrafanaMcpClient()
    client.poll_ingestion_ready = AsyncMock(return_value=(entries, False, False))
    client.query_prometheus_run_metrics = AsyncMock(return_value=(baseline.metrics, [], False))
    observed = await client.collect_observed_run(
        baseline.run_id,
        baseline.session_id,
        datetime.fromisoformat(baseline.start_time_rfc3339).timestamp(),
        now.timestamp(),
        expected_manifest=baseline.manifest,
    )
    assert len(observed.samples) == 484
    assert observed.identical_duplicate_count == (1 if duplicate_kind == "identical" else 0)
    assert observed.has_conflicting_duplicates == (duplicate_kind == "timestamp_conflict")


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["false", 0, None])
async def test_collector_rejects_missing_or_coerced_boolean_flags(flag):
    from unittest.mock import AsyncMock

    from signal_slate.evidence.mcp_client import GrafanaMcpClient, McpResponseError

    baseline, _, _, now = evidence_pair("healthy", action("NO_ACTION"), RunConfig())
    entry = {"event": "sample", **baseline.samples[0].model_dump(), "is_clipped": flag}
    client = GrafanaMcpClient()
    client.poll_ingestion_ready = AsyncMock(return_value=([entry], False, False))
    with pytest.raises(McpResponseError, match="explicit JSON booleans"):
        await client.collect_observed_run(
            baseline.run_id,
            baseline.session_id,
            datetime.fromisoformat(baseline.start_time_rfc3339).timestamp(),
            now.timestamp(),
            expected_manifest=baseline.manifest,
        )


def test_wrapper_filters_measured_clipping_events():
    baseline, _, _, _ = evidence_pair("audio_clipping", action("NO_ACTION"), RunConfig())
    wrapper = BoundedModelEvidenceWrapper(baseline, ShotContext())
    assert wrapper.get_run_events(baseline.run_id, event_types=["sample_clipping"])
    assert not wrapper.get_run_events(baseline.run_id, event_types=["sample_dropout"])
