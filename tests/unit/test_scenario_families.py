"""Mechanism-specific controls: an intervention must be capable of failing."""

import json

import pytest
from signal_slate.domain.models import (
    CandidateAction,
    Constraint,
    Finding,
    RunConfig,
    ShotContext,
    actions_hash,
)
from signal_slate.planning.candidates import generate_candidate_plans
from signal_slate.simulator.engine import SimulatorEngine

FAMILIES = ("channel_interference", "antenna_shadow", "audio_clipping", "healthy")


def measure(family, config=None, context=None, seed=42):
    samples, metrics, events = SimulatorEngine(context, fault_family=family).run_rehearsal(
        config or RunConfig(), seed=seed
    )
    lead = [s for s in samples if s.mic_id == "mic_1" and s.offset_ms < 12000]
    return (
        samples,
        metrics,
        events,
        sum(s.is_dropout * 100 for s in lead),
        sum(s.is_clipped * 100 for s in lead),
    )


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("seed", [1, 42, 987654])
def test_exact_grid_and_determinism_for_every_family(family, seed):
    first = measure(family, seed=seed)
    second = measure(family, seed=seed)
    assert first == second
    samples, metrics, events, _, _ = first
    assert len({(s.mic_id, s.offset_ms) for s in samples}) == 484
    assert len(metrics) == 48
    assert events[-1]["samples_count"] == 484
    assert sum(m.dropout_duration_ms for m in metrics if m.mic_id == "mic_1") == first[3]
    assert sum(m.clipping_duration_ms for m in metrics if m.mic_id == "mic_1") == first[4]


@pytest.mark.parametrize("family", FAMILIES)
def test_no_hidden_family_in_observations_or_config(family):
    samples, metrics, events, _, _ = measure(family)
    public = json.dumps(
        [
            *[s.model_dump() for s in samples],
            *[m.model_dump() for m in metrics],
            events,
            RunConfig().model_dump(),
        ]
    )
    assert family not in public
    assert "fault_family" not in public


def test_channel_correction_only_repairs_channel_mechanism():
    changed = RunConfig(channel_assignments={"mic_1": 12})
    assert measure("channel_interference")[3] == 1900
    assert measure("channel_interference", changed)[3] == 0
    assert measure("antenna_shadow", changed)[3] == 1900
    assert measure("audio_clipping", changed)[4] == 1900


def test_antenna_correction_only_repairs_path_mechanism():
    changed = RunConfig(antenna_selection="B")
    assert measure("antenna_shadow")[3] == 1900
    assert measure("antenna_shadow", changed)[3] == 0
    assert measure("channel_interference", changed)[3] == 1900
    assert measure("audio_clipping", changed)[4] == 1900


@pytest.mark.parametrize("family", FAMILIES)
def test_backup_route_never_changes_receiver_telemetry(family):
    routed = RunConfig(backup_sources={"mic_1": "mic_4"})
    before, _, _, gaps_before, clips_before = measure(family)
    after, _, _, gaps_after, clips_after = measure(family, routed)
    # Provenance config hashes must change, the physical measurements must not.
    assert before[0].config_hash != after[0].config_hash
    for a, b in zip(before, after, strict=True):
        assert a.model_dump(exclude={"config_hash"}) == b.model_dump(exclude={"config_hash"})
    assert (gaps_before, clips_before) == (gaps_after, clips_after)


@pytest.mark.parametrize("family", FAMILIES)
def test_unknown_hardware_options_fail_even_healthy_control(family):
    for config in (
        RunConfig(antenna_selection="invalid"),
        RunConfig(channel_assignments={"mic_1": 999}),
    ):
        assert measure(family, config)[3] == 12000


def test_healthy_control_has_no_fault_and_clipping_has_healthy_rf():
    samples, _, _, gaps, clips = measure("healthy")
    assert gaps == clips == 0
    assert all(s.quality >= 70 and not s.is_clipped and not s.is_dropout for s in samples)
    samples, _, _, gaps, clips = measure("audio_clipping")
    assert gaps == 0 and clips == 1900
    assert min(s.quality for s in samples) >= 70


@pytest.mark.parametrize("family", FAMILIES)
def test_shifted_heldout_interval_has_no_hardcoded_timing(family):
    context = ShotContext(critical_line_start_ms=3100, critical_line_end_ms=5500)
    samples, _, _, gaps, clips = measure(family, context=context, seed=739)
    assert gaps == (2400 if family in ("channel_interference", "antenna_shadow") else 0)
    assert clips == (2400 if family == "audio_clipping" else 0)
    faulty = [s for s in samples if s.is_clipped or s.is_dropout]
    assert all(3100 <= s.offset_ms < 5500 for s in faulty)


def finding(action_type="CHANNEL_SWITCH", parameters=None, status="RISK_IDENTIFIED"):
    return Finding(
        status=status,
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Measured anomaly"],
        evidence_ids=["returned-1"],
        recommended_action=CandidateAction(
            action_type=action_type,
            mic_id="mic_1",
            parameters={"channel": 11} if parameters is None else parameters,
        ),
    )


def constraint(kind, parameters=None, target="mic_1", confirmed=True):
    return Constraint(
        constraint_id="c",
        kind=kind,
        parameters=parameters or {},
        target_mic=target,
        confirmed=confirmed,
        exact_source_span="Keep this setup",
        source_text="Keep this setup",
    )


def plans(f, constraints=None, base=None):
    return generate_candidate_plans(f, constraints or [], "base", ShotContext(), base_config=base)


def test_plan_preserves_antenna_hypothesis_instead_of_magic_channel_switch():
    result = plans(finding("ANTENNA_SWITCH", {"antenna": "B"}))
    assert len(result) == 1
    assert result[0].actions[0].action_type == "ANTENNA_SWITCH"
    assert result[0].actions[0].parameters == {"antenna": "B"}


def test_exclusion_is_scoped_to_target_and_alternative_deduplicated():
    scoped = constraint("CHANNEL_EXCLUSION", {"excluded_channel": 11}, target="mic_2")
    assert any(p.plan_id == "plan_a" for p in plans(finding(), [scoped]))
    relevant = scoped.model_copy(update={"target_mic": "mic_1"})
    result = plans(finding(), [relevant])
    assert len(result) == 1
    assert result[0].actions[0].parameters == {"channel": 12}
    assert len({p.action_hash for p in plans(finding("CHANNEL_SWITCH", {"channel": 12}))}) == 2


def test_antenna_lock_yields_backup_without_claiming_receiver_repair():
    result = plans(
        finding("ANTENNA_SWITCH", {"antenna": "B"}),
        [constraint("ANTENNA_LOCK", {"locked_antenna": "A"})],
    )
    assert result[0].actions[0].action_type == "BOOM_COVERAGE"
    assert "remains unresolved" in result[0].rationale


def test_clipping_no_action_can_offer_explicit_dialogue_backup():
    result = plans(finding("NO_ACTION", {}))
    assert [p.actions[0].action_type for p in result] == ["NO_ACTION", "BOOM_COVERAGE"]
    for p in result:
        assert p.action_hash == actions_hash(p.actions)


def test_rig_lock_allows_backup_but_boom_exclusion_can_remove_last_candidate():
    locks = [constraint("RIG_LOCK")]
    assert plans(finding(), locks)[0].actions[0].action_type == "BOOM_COVERAGE"
    assert plans(finding(), locks + [constraint("BOOM_EXCLUSION")]) == []


def test_healthy_no_action_does_not_invent_an_intervention():
    result = plans(finding("NO_ACTION", {}, status="HEALTHY"))
    assert len(result) == 1 and result[0].actions[0].action_type == "NO_ACTION"


def test_alternative_uses_actual_base_configuration():
    result = plans(
        finding("CHANNEL_SWITCH", {"channel": 11}),
        base=RunConfig(channel_assignments={"mic_1": 12}),
    )
    assert {p.actions[0].parameters["channel"] for p in result} == {10, 11}


@pytest.mark.parametrize(
    "bad",
    [
        constraint("CUSTOM"),
        constraint("RIG_LOCK", confirmed=False),
        constraint("CHANNEL_EXCLUSION", {"excluded_channel": True}),
    ],
)
def test_invalid_constraints_fail_closed(bad):
    with pytest.raises(ValueError):
        plans(finding(), [bad])


@pytest.mark.parametrize(
    "kind,parameters,config",
    [
        ("CHANNEL_SWITCH", {"channel": 12}, RunConfig(channel_assignments={"mic_1": 12})),
        ("ANTENNA_SWITCH", {"antenna": "B"}, RunConfig(antenna_selection="B")),
        ("BOOM_COVERAGE", {"source_mic": "mic_4"}, RunConfig(backup_sources={"mic_1": "mic_4"})),
    ],
)
def test_retry_never_offers_already_applied_configuration(kind, parameters, config):
    result = plans(finding(kind, parameters), base=config)
    assert all(
        not (a.action_type == kind and a.parameters == parameters)
        for p in result
        for a in p.actions
    )
    if kind == "BOOM_COVERAGE":
        assert result == []
