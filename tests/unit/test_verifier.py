"""Unit tests for deterministic cloud-only verifier."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    EvidenceContext,
    ObservedRun,
    RunConfig,
    ShotContext,
    actions_hash,
    create_evidence_context,
)
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.verification.verifier import DeterministicVerifier


def _create_observed_run(
    engine: SimulatorEngine,
    config: RunConfig,
    run_id: str,
    session_id: str = "sess-test",
    base_config: RunConfig | None = None,
    evidence_context: EvidenceContext | None = None,
    omit_final_sample: bool = False,
    omit_completion_marker: bool = False,
    now: datetime | None = None,
    include_manifest: bool = True,
    fault_commitment_hash: str | None = None,
    start_time_rfc3339: str | None = None,
    end_time_rfc3339: str | None = None,
    override_config_hash: str | None = None,
) -> ObservedRun:
    now_dt = now or datetime.now(UTC)
    if start_time_rfc3339 is None:
        start_dt = now_dt - timedelta(seconds=12)
        start_ts = start_dt.timestamp()
        st_rfc = start_dt.isoformat()
        et_rfc = now_dt.isoformat()
    else:
        st_rfc = start_time_rfc3339
        et_rfc = end_time_rfc3339 or now_dt.isoformat()
        start_ts = datetime.fromisoformat(st_rfc.replace("Z", "+00:00")).timestamp()

    if evidence_context is not None:
        session_id = evidence_context.session_id
    effective_cfg_hash = override_config_hash or config.config_hash
    if evidence_context is None:
        ev_ctx, _ = create_evidence_context(
            session_id=session_id, base_config=base_config or config
        )
    else:
        ev_ctx = evidence_context

    samples, metrics, _ = engine.run_rehearsal(
        config,
        start_time_sec=start_ts,
        session_id=session_id,
        run_id=run_id,
    )
    if override_config_hash:
        samples = [s.model_copy(update={"config_hash": override_config_hash}) for s in samples]
        metrics = [m.model_copy(update={"config_hash": override_config_hash}) for m in metrics]

    if omit_final_sample and samples:
        samples = samples[:-1]

    manifest = None
    if include_manifest:
        manifest = engine.create_prepublication_manifest(
            run_id=run_id,
            session_id=session_id,
            config=config,
            evidence_context=ev_ctx,
            created_at_rfc3339=st_rfc,
        )
        if override_config_hash:
            manifest = manifest.model_copy(update={"config_hash": override_config_hash})
        if fault_commitment_hash is not None:
            manifest = manifest.model_copy(update={"fault_commitment_hash": fault_commitment_hash})

    return ObservedRun(
        run_id=run_id,
        session_id=session_id,
        config_hash=effective_cfg_hash,
        samples=samples,
        metrics=metrics,
        completion_marker_present=not omit_completion_marker,
        retrieved_sample_count=len(samples),
        start_time_rfc3339=st_rfc,
        end_time_rfc3339=et_rfc,
        manifest=manifest,
        fault_commitment_hash=fault_commitment_hash
        or (manifest.fault_commitment_hash if manifest else ""),
        source_audio_hash=manifest.source_audio_hash if manifest else "",
        scenario_path_hash=manifest.scenario_path_hash if manifest else "",
    )


def test_clean_comparison_run_passes_verification():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-clean", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", session_id="sess-clean", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        session_id="sess-clean",
        base_config=base_config,
        evidence_context=ev_ctx,
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="Clean switch to Channel 12",
    )
    constraint = Constraint(
        constraint_id="c1",
        kind="CHANNEL_EXCLUSION",
        parameters={"excluded_channel": 11},
        exact_source_span="exclude 11",
        source_text="exclude 11",
        confirmed=True,
    )

    # Authority lane baseline pre-check passes
    base_res = verifier.verify_baseline_run(base_run, base_config.config_hash, now=now)
    assert base_res.terminal_status == "VERIFIED"

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[constraint],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "VERIFIED"
    assert result.completeness_passed is True
    assert result.crosscheck_passed is True
    assert result.thresholds_passed is True
    assert result.dialogue_coverage_passed is True
    assert result.constraints_passed is True


def test_negative_missing_final_sample_fails_completeness():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        evidence_context=ev_ctx,
        base_config=base_config,
        omit_final_sample=True,
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_run.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("484" in reason for reason in result.failure_reasons)


def test_negative_wrong_run_id_fails_completeness():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-base-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_run.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("distinct runs required" in r for r in result.failure_reasons)


def test_negative_constraint_violation_fails():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 11})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Action uses Channel 11
    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 11}
    )
    plan = CandidatePlan(
        plan_id="plan_a",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_run.config_hash,
        rationale="switch to 11",
    )
    # Constraint explicitly excluded Channel 11
    constraint = Constraint(
        constraint_id="c1",
        kind="CHANNEL_EXCLUSION",
        parameters={"excluded_channel": 11},
        exact_source_span="Channel 11 belongs to the next setup",
        source_text="Channel 11 belongs to the next setup",
        confirmed=True,
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[constraint],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "NOT_VERIFIED"
    assert result.constraints_passed is False
    assert any("violates constraint" in reason for reason in result.failure_reasons)


def test_r2_reproduced_blocker_identical_offsets_no_metrics_year2000_fails_inconclusive():
    """Duplicate offsets, absent metrics and stale dates cannot verify."""
    context = ShotContext()
    verifier = DeterministicVerifier(context)
    engine = SimulatorEngine(context)
    now = datetime.now(UTC)

    from signal_slate.domain.models import MicSample

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    base_run = _create_observed_run(engine, base_config, "run-base-1", now=now)

    bogus_samples = []
    for mic_id in context.mic_ids:
        for _ in range(121):
            bogus_samples.append(
                MicSample(
                    offset_ms=5000,
                    mic_id=mic_id,
                    quality=99.0,
                    link_margin_db=20.0,
                    battery_pct=98.0,
                    is_clipped=False,
                    is_dropout=False,
                    timestamp_rfc3339="2000-01-01T00:00:00Z",
                    run_id="run-comp-adversarial",
                    session_id=base_run.session_id,
                    config_hash="unrelated_config_hash_xyz",
                )
            )

    comp_run = ObservedRun(
        run_id="run-comp-adversarial",
        session_id=base_run.session_id,
        config_hash="unrelated_config_hash_xyz",
        samples=bogus_samples,
        metrics=[],
        completion_marker_present=True,
        retrieved_sample_count=len(bogus_samples),
        start_time_rfc3339="2000-01-01T00:00:00Z",
        end_time_rfc3339="2000-01-01T00:00:12Z",
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_run.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any(
        "manifest" in r.lower()
        or "older than max age" in r.lower()
        or "missing offset" in r.lower()
        for r in result.failure_reasons
    )


def test_r2_nan_values_yield_inconclusive():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)
    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Inject NaN into a sample
    comp_run.samples[10] = comp_run.samples[10].model_copy(update={"quality": float("nan")})

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("non-finite sample value" in r for r in result.failure_reasons)


def test_r3_clipping_in_critical_interval_fails_dialogue():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)
    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Set is_clipped on critical interval sample
    for idx, s in enumerate(comp_run.samples):
        if (
            s.mic_id == "mic_1"
            and context.critical_line_start_ms <= s.offset_ms <= context.critical_line_end_ms
        ):
            comp_run.samples[idx] = s.model_copy(update={"is_clipped": True})
            break

    # Recompute metrics to avoid contradiction
    comp_run = comp_run.model_copy(
        update={"metrics": engine._compute_per_second_metrics(comp_run.samples)}
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "NOT_VERIFIED"
    assert result.dialogue_coverage_passed is False
    assert any(
        "clipping detected" in r or "Lead dialogue line" in r for r in result.failure_reasons
    )


def test_r3_metric_contradiction_yields_inconclusive():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)
    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Contradict metric min_quality (set to 20.0 when samples are ~90.0)
    comp_run.metrics[0] = comp_run.metrics[0].model_copy(update={"min_quality": 20.0})

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.crosscheck_passed is False
    assert any("contradiction" in r for r in result.failure_reasons)


def test_r3_rig_lock_and_antenna_lock_enforced():
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-test", base_config)
    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    # Rig lock on mic_1
    rig_constraint = Constraint(
        constraint_id="c_rig",
        kind="RIG_LOCK",
        target_mic="mic_1",
        parameters={},
        exact_source_span="mic 1 locked",
        source_text="mic 1 locked",
        confirmed=True,
    )

    res_rig = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[rig_constraint],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )
    assert res_rig.terminal_status == "NOT_VERIFIED"
    assert res_rig.constraints_passed is False
    assert any("rig on mic 'mic_1' is locked" in r for r in res_rig.failure_reasons)

    # Unsupported constraint kind fails closed
    unsupported_constraint = Constraint(
        constraint_id="c_custom",
        kind="CUSTOM",
        parameters={"unsupported_key": 999},
        exact_source_span="custom constraint",
        source_text="custom constraint",
        confirmed=True,
    )
    res_unsupported = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[unsupported_constraint],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )
    assert res_unsupported.terminal_status == "NOT_VERIFIED"
    assert res_unsupported.constraints_passed is False
    assert any("Unsupported" in r for r in res_unsupported.failure_reasons)


# ==============================================================================
# Adversarial Tests Addressing Codex Review Findings 1 to 7
# ==============================================================================


def test_adversarial_finding_1_random_uuid4_comparison_config_hash_fails():
    """Finding 1: A random uuid4 config_hash must NOT pass verification as VERIFIED."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-1", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    # Comparison run carries a random uuid4 config_hash
    random_hash = uuid.uuid4().hex
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        evidence_context=ev_ctx,
        base_config=base_config,
        override_config_hash=random_hash,
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    # Verifier is given the true expected config hash, while comparison run has random uuid4
    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any(
        "Comparison config hash" in r and "does not match authoritative" in r
        for r in result.failure_reasons
    )


def test_adversarial_finding_1_missing_expected_config_hash_fails_closed():
    """Finding 1: Authoritative expected_config_hash cannot be omitted or fallen back."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-1b", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash="",  # Empty / omitted!
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert any("expected_config_hash is required" in r for r in result.failure_reasons)


def test_adversarial_finding_2_day_old_timestamps_in_current_year_fail():
    """Finding 2: Timestamps 24 hours old (even in current year 2026) must fail age bound."""
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    yesterday = now - timedelta(days=1)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-2", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    # Comparison evidence was collected yesterday
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        evidence_context=ev_ctx,
        base_config=base_config,
        start_time_rfc3339=(yesterday - timedelta(seconds=12)).isoformat(),
        end_time_rfc3339=yesterday.isoformat(),
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
        max_age_seconds=1800.0,  # 30 min max age
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("older than max age" in r for r in result.failure_reasons)


def test_adversarial_finding_2_future_timestamps_fail():
    """Finding 2: Evidence with timestamps ahead of server time must fail."""
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    future = now + timedelta(minutes=5)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-2b", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        evidence_context=ev_ctx,
        base_config=base_config,
        start_time_rfc3339=future.isoformat(),
        end_time_rfc3339=(future + timedelta(seconds=12)).isoformat(),
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("future evidence timestamp" in r for r in result.failure_reasons)


def test_adversarial_finding_3_fault_commitment_equal_to_raw_audio_hash_fails():
    """Finding 3: Using raw audio hash as fault commitment must fail closed."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-3", base_config)

    # Use raw audio hash as fault commitment
    raw_hash = context.source_audio_hash
    base_run = _create_observed_run(
        engine,
        base_config,
        "run-base-1",
        evidence_context=ev_ctx,
        fault_commitment_hash=raw_hash,
        now=now,
    )
    comp_run = _create_observed_run(
        engine,
        comp_config,
        "run-comp-1",
        evidence_context=ev_ctx,
        base_config=base_config,
        fault_commitment_hash=raw_hash,
        now=now,
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert any("fault commitment equals raw audio hash" in r for r in result.failure_reasons)


def test_adversarial_finding_3_missing_manifest_fails():
    """Finding 3: Missing manifest must return INCONCLUSIVE."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", include_manifest=True, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", include_manifest=False, now=now
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert any("missing required pre-publication" in r.lower() for r in result.failure_reasons)


def test_adversarial_finding_4_corrupted_baseline_fails_verification():
    """Finding 4: Incomplete/corrupted baseline must fail baseline and run verification."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-4", base_config)

    # Baseline missing final sample
    corrupted_base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, omit_final_sample=True, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Direct baseline check must fail
    base_res = verifier.verify_baseline_run(corrupted_base_run, base_config.config_hash, now=now)
    assert base_res.terminal_status == "INCONCLUSIVE"
    assert base_res.completeness_passed is False

    # verify_run must fail closed
    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=corrupted_base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.completeness_passed is False
    assert any("Baseline sample grid incomplete" in r for r in result.failure_reasons)


def test_adversarial_finding_4_battery_pct_mismatch_fails_crosscheck():
    """Finding 4: Metric battery_pct mismatch with samples must fail crosscheck."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-4b", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Tamper metric battery_pct to 50.0 (samples have 98.0)
    comp_run.metrics[0] = comp_run.metrics[0].model_copy(update={"min_battery_pct": 50.0})

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "INCONCLUSIVE"
    assert result.crosscheck_passed is False
    assert any(
        "metric crosscheck contradiction" in r and "Batt=" in r for r in result.failure_reasons
    )


def test_adversarial_finding_5_non_lead_mic_clipping_during_critical_dialogue_fails():
    """Finding 5: Clipping on ANY mic (e.g. mic_2) during critical dialogue must fail."""
    now = datetime.now(UTC)
    context = ShotContext()
    engine = SimulatorEngine(context)
    verifier = DeterministicVerifier(context)

    base_config = RunConfig(channel_assignments={"mic_1": 10})
    comp_config = RunConfig(channel_assignments={"mic_1": 12})
    ev_ctx, _ = create_evidence_context("sess-adv-5", base_config)

    base_run = _create_observed_run(
        engine, base_config, "run-base-1", evidence_context=ev_ctx, now=now
    )
    comp_run = _create_observed_run(
        engine, comp_config, "run-comp-1", evidence_context=ev_ctx, base_config=base_config, now=now
    )

    # Clip mic_2 during critical line
    for idx, s in enumerate(comp_run.samples):
        if (
            s.mic_id == "mic_2"
            and context.critical_line_start_ms <= s.offset_ms <= context.critical_line_end_ms
        ):
            comp_run.samples[idx] = s.model_copy(update={"is_clipped": True})
            break

    # Recompute metrics to avoid contradiction
    comp_run = comp_run.model_copy(
        update={"metrics": engine._compute_per_second_metrics(comp_run.samples)}
    )

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="plan_b",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="c_hash",
        base_config_hash=base_config.config_hash,
        rationale="switch",
    )

    result = verifier.verify_run(
        baseline_run=base_run,
        comparison_run=comp_run,
        approved_plan=plan,
        confirmed_constraints=[],
        expected_config_hash=comp_config.config_hash,
        now=now,
    )

    assert result.terminal_status == "NOT_VERIFIED"
    assert result.dialogue_coverage_passed is False
    assert any(
        "Mic 'mic_2' exhibited dropout or clipping during critical dialogue" in r
        for r in result.failure_reasons
    )


def test_adversarial_finding_5_boundary_duration_weights_sum_to_at_most_1000ms():
    """Finding 5: Sample 12000 is boundary only. Per-second durations sum to <= 1000ms."""
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig(channel_assignments={"mic_1": 10})
    samples, metrics, _ = engine.run_rehearsal(config, seed=42)

    for m in metrics:
        assert m.clipping_duration_ms <= 1000
        assert m.dropout_duration_ms <= 1000
        assert m.clipping_duration_ms + m.dropout_duration_ms <= 1000


@pytest.fixture
def valid_evidence_pair():
    """Every mutation starts from an independently verified complete positive control."""
    now = datetime.now(UTC)
    engine = SimulatorEngine(ShotContext())
    base = RunConfig(channel_assignments={"mic_1": 10})
    comp = RunConfig(channel_assignments={"mic_1": 12})
    ctx, _ = create_evidence_context("positive-control", base)
    baseline = _create_observed_run(engine, base, "baseline", evidence_context=ctx, now=now)
    comparison = _create_observed_run(engine, comp, "comparison", evidence_context=ctx, now=now)
    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    plan = CandidatePlan(
        plan_id="approved",
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash="none",
        base_config_hash=base.config_hash,
        rationale="switch",
    )
    verifier = DeterministicVerifier()
    assert (
        verifier.verify_run(baseline, comparison, plan, [], comp.config_hash, now).terminal_status
        == "VERIFIED"
    )
    return verifier, baseline, comparison, plan, comp.config_hash, now, engine


@pytest.mark.parametrize("side", ["baseline", "comparison"])
@pytest.mark.parametrize(
    "corruption",
    [
        "missing_sample_time",
        "naive_sample_time",
        "misaligned_sample_time",
        "missing_metric_time",
        "naive_metric_time",
        "misaligned_metric_time",
        "missing_manifest_time",
        "naive_window",
        "wrong_window",
        "missing_source",
        "missing_path",
        "missing_fault",
        "wrong_count",
        "wrong_metric_count",
        "wrong_retrieved_count",
        "nan_metric",
        "battery_mismatch",
        "duplicate_sample",
        "duplicate_metric",
        "stale_row",
        "future_row",
    ],
)
def test_single_corruption_cannot_verify(valid_evidence_pair, side, corruption):
    verifier, baseline, comparison, plan, expected, now, _ = valid_evidence_pair
    run = baseline if side == "baseline" else comparison
    if corruption.endswith("sample_time"):
        value = {
            "missing_sample_time": "",
            "naive_sample_time": now.replace(tzinfo=None).isoformat(),
            "misaligned_sample_time": now.isoformat(),
        }[corruption]
        run.samples[0] = run.samples[0].model_copy(update={"timestamp_rfc3339": value})
    elif corruption.endswith("metric_time"):
        value = {
            "missing_metric_time": "",
            "naive_metric_time": now.replace(tzinfo=None).isoformat(),
            "misaligned_metric_time": now.isoformat(),
        }[corruption]
        run.metrics[0] = run.metrics[0].model_copy(update={"timestamp_rfc3339": value})
    elif corruption == "missing_manifest_time":
        run.manifest = run.manifest.model_copy(update={"created_at_rfc3339": ""})
    elif corruption == "naive_window":
        run.start_time_rfc3339 = now.replace(tzinfo=None).isoformat()
    elif corruption == "wrong_window":
        run.end_time_rfc3339 = (now - timedelta(seconds=1)).isoformat()
    elif corruption.startswith("missing_"):
        setattr(
            run,
            {
                "missing_source": "source_audio_hash",
                "missing_path": "scenario_path_hash",
                "missing_fault": "fault_commitment_hash",
            }[corruption],
            "",
        )
    elif corruption == "wrong_count":
        run.manifest = run.manifest.model_copy(update={"sample_count": 483})
    elif corruption == "wrong_metric_count":
        run.manifest = run.manifest.model_copy(update={"metric_count": 47})
    elif corruption == "wrong_retrieved_count":
        run.retrieved_sample_count = 1
    elif corruption == "nan_metric":
        run.metrics[0] = run.metrics[0].model_copy(update={"min_link_margin_db": float("nan")})
    elif corruption == "battery_mismatch":
        run.metrics[0] = run.metrics[0].model_copy(update={"min_battery_pct": 1})
    elif corruption == "duplicate_sample":
        run.samples[-1] = run.samples[0].model_copy()
    elif corruption == "duplicate_metric":
        run.metrics[-1] = run.metrics[0].model_copy()
    else:
        delta = timedelta(days=-1 if corruption == "stale_row" else 1)
        run.samples[0] = run.samples[0].model_copy(
            update={"timestamp_rfc3339": (now + delta).isoformat()}
        )
    result = verifier.verify_run(baseline, comparison, plan, [], expected, now)
    assert result.terminal_status == "INCONCLUSIVE", result.failure_reasons


@pytest.mark.parametrize("field", ["is_dropout", "is_clipped"])
def test_nonlead_critical_fault_is_not_verified(valid_evidence_pair, field):
    verifier, baseline, comparison, plan, expected, now, engine = valid_evidence_pair
    idx = next(
        i
        for i, sample in enumerate(comparison.samples)
        if sample.mic_id == "mic_2" and sample.offset_ms == 5000
    )
    comparison.samples[idx] = comparison.samples[idx].model_copy(update={field: True})
    comparison.metrics = engine._compute_per_second_metrics(comparison.samples)
    result = verifier.verify_run(baseline, comparison, plan, [], expected, now)
    assert result.completeness_passed and result.crosscheck_passed
    assert result.terminal_status == "NOT_VERIFIED"
    assert not result.dialogue_coverage_passed


@pytest.mark.parametrize(
    "parameters,confirmed,target,should_pass",
    [
        ({"excluded_channel": 12}, True, "mic_2", True),
        ({"excluded_channel": 12}, True, "mic_1", False),
        ({"excluded_channel": 11}, False, None, False),
        ({"excluded_channel": True}, True, None, False),
        ({"excluded_channel": 11, "invented": 1}, True, None, False),
    ],
)
def test_constraint_scope_and_confirmation(
    valid_evidence_pair, parameters, confirmed, target, should_pass
):
    verifier, baseline, comparison, plan, expected, now, _ = valid_evidence_pair
    constraint = Constraint(
        constraint_id="constraint",
        kind="CHANNEL_EXCLUSION",
        target_mic=target,
        parameters=parameters,
        confirmed=confirmed,
        exact_source_span="exclude",
        source_text="exclude",
    )
    result = verifier.verify_run(baseline, comparison, plan, [constraint], expected, now)
    assert result.constraints_passed is should_pass
    assert result.terminal_status == ("VERIFIED" if should_pass else "NOT_VERIFIED")


@pytest.mark.parametrize("offset", [6800, 12000])
def test_half_open_critical_and_rehearsal_endpoints(valid_evidence_pair, offset):
    verifier, baseline, comparison, plan, expected, now, engine = valid_evidence_pair
    idx = next(
        i
        for i, sample in enumerate(comparison.samples)
        if sample.mic_id == "mic_2" and sample.offset_ms == offset
    )
    comparison.samples[idx] = comparison.samples[idx].model_copy(update={"is_dropout": True})
    comparison.metrics = engine._compute_per_second_metrics(comparison.samples)
    result = verifier.verify_run(baseline, comparison, plan, [], expected, now)
    assert result.terminal_status == "VERIFIED", result.failure_reasons


def test_identical_applied_config_cannot_verify(valid_evidence_pair):
    verifier, baseline, comparison, plan, _, now, _ = valid_evidence_pair
    comparison.config_hash = baseline.config_hash
    comparison.manifest = comparison.manifest.model_copy(
        update={"config_hash": baseline.config_hash}
    )
    comparison.samples = [
        sample.model_copy(update={"config_hash": baseline.config_hash})
        for sample in comparison.samples
    ]
    comparison.metrics = [
        metric.model_copy(update={"config_hash": baseline.config_hash})
        for metric in comparison.metrics
    ]
    result = verifier.verify_run(baseline, comparison, plan, [], baseline.config_hash, now)
    assert result.terminal_status == "INCONCLUSIVE"
    assert any("different applied configuration" in reason for reason in result.failure_reasons)


@pytest.mark.parametrize("field", ["source_audio_hash", "scenario_path_hash"])
def test_consistently_forged_source_binding_rejected(valid_evidence_pair, field):
    verifier, baseline, comparison, plan, expected, now, _ = valid_evidence_pair
    forged_hash = uuid.uuid4().hex + uuid.uuid4().hex
    for run in (baseline, comparison):
        setattr(run, field, forged_hash)
        run.manifest = run.manifest.model_copy(update={field: forged_hash})
    result = verifier.verify_run(baseline, comparison, plan, [], expected, now)
    assert result.terminal_status == "INCONCLUSIVE"
    assert any("trusted shot context" in reason for reason in result.failure_reasons)
