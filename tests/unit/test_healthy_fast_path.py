"""Healthy evidence is deterministic; incomplete or other-mic faults cannot turn green."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import Client
from signal_slate.agent.live_adk import SignalSlateAdkAgent
from signal_slate.domain.models import RunConfig, ShotContext
from signal_slate.verification.verifier import DeterministicVerifier
from signal_slate.workflow.orchestrator import LiveWorkflowOrchestrator

from tests.unit.test_scenario_verification import action, evidence_pair


def workflow_with(run, agent):
    workflow = object.__new__(LiveWorkflowOrchestrator)
    workflow.context = ShotContext()
    workflow.verifier = DeterministicVerifier(workflow.context)
    workflow.agent = agent
    workflow._update_durable_state = MagicMock()
    workflow._runs = {
        "wf": {
            "observed_baseline": run,
            "base_config": RunConfig(),
            "trace_log": [],
            "approved_plan": "old",
            "approval": "old",
        }
    }
    return workflow


@pytest.mark.asyncio
async def test_complete_healthy_run_needs_zero_model_calls():
    baseline, _, _, _ = evidence_pair("healthy", action("NO_ACTION"), RunConfig())
    agent = MagicMock()
    agent.investigate_baseline = AsyncMock(
        side_effect=AssertionError("Healthy must not call model")
    )
    workflow = workflow_with(baseline, agent)
    finding = await workflow.investigate("wf")
    assert finding.status == "HEALTHY"
    assert finding.recommended_action.action_type == "NO_ACTION"
    assert finding.evidence_ids
    assert workflow._runs["wf"]["finding_origin"] == "deterministic"
    assert "approval" not in workflow._runs["wf"] and "approved_plan" not in workflow._runs["wf"]
    agent.investigate_baseline.assert_not_called()


@pytest.mark.asyncio
async def test_four_healthy_samples_cannot_take_healthy_fast_path_or_dispatch():
    baseline, _, _, _ = evidence_pair("healthy", action("NO_ACTION"), RunConfig())
    baseline.samples = baseline.samples[:4]
    baseline.retrieved_sample_count = 4
    factory = MagicMock()
    agent = SignalSlateAdkAgent(factory, genai_client=MagicMock(spec=Client))
    workflow = workflow_with(baseline, agent)
    with pytest.raises(ValueError, match="Incomplete baseline"):
        await workflow.investigate("wf")
    assert "finding" not in workflow._runs["wf"]
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_complete_other_microphone_fault_never_takes_healthy_fast_path():
    baseline, _, _, _ = evidence_pair("channel_interference", action("NO_ACTION"), RunConfig())
    for row in [*baseline.samples, *baseline.metrics]:
        if row.mic_id in ("mic_1", "mic_2"):
            row.mic_id = "mic_2" if row.mic_id == "mic_1" else "mic_1"
    assert (
        DeterministicVerifier().verify_baseline_run(baseline, baseline.config_hash).terminal_status
        == "VERIFIED"
    )
    agent = MagicMock()
    agent.investigate_baseline = AsyncMock(side_effect=RuntimeError("Model boundary reached"))
    workflow = workflow_with(baseline, agent)
    with pytest.raises(RuntimeError, match="Model boundary"):
        await workflow.investigate("wf")
    agent.investigate_baseline.assert_awaited_once()
    assert "finding" not in workflow._runs["wf"]


@pytest.mark.asyncio
async def test_retry_keeps_applied_configuration_history_and_invalidates_approval(monkeypatch):
    import json

    from fastapi.encoders import jsonable_encoder
    from signal_slate import api_routes
    from signal_slate.domain.models import Finding, PlanApproval

    config = RunConfig(channel_assignments={"mic_1": 11, "mic_2": 20, "mic_3": 30, "mic_4": 40})
    baseline, comparison, plan, now = evidence_pair(
        "antenna_shadow", action("CHANNEL_SWITCH", {"channel": 11}), config
    )
    verification = DeterministicVerifier().verify_run(
        baseline, comparison, plan, [], config.config_hash, now
    )
    assert verification.terminal_status == "NOT_VERIFIED"
    approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=1,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Fault persists"],
        evidence_ids=["sample"],
        recommended_action=action("ANTENNA_SWITCH", {"antenna": "B"}),
    )

    class FakeWorkflow:
        def __init__(self, **kwargs):
            self._runs = {}

        async def investigate(self, sid, repair_retry=False):
            assert repair_retry
            data = self._runs[sid]
            assert data["base_config"] == config
            assert data["observed_baseline"].run_id == comparison.run_id
            assert "approval" not in data and "approved_plan" not in data
            assert data["history"][0]["actions"][0]["parameters"] == {"channel": 11}
            data["finding"] = finding

    monkeypatch.setattr(api_routes, "LiveWorkflowOrchestrator", FakeWorkflow)
    snapshot = {
        "public": {},
        "workflow": jsonable_encoder(
            {
                "base_config": RunConfig(),
                "comparison_config": config,
                "observed_baseline": baseline,
                "observed_comparison": comparison,
                "verification": verification,
                "approved_plan": plan,
                "approval": approval,
                "finding": finding,
            }
        ),
    }
    await api_routes.execute_live("retry", "sid", api_routes.Command(revision=0), snapshot)
    json.dumps(snapshot)
    state = snapshot["public"]
    assert state["approval"] is None and state["comparison"] is None
    assert state["baseline_config"] == config.model_dump(mode="json")
    assert state["history"][0]["approval"]["approved"] is True
    assert state["original_baseline"]["run_id"] == baseline.run_id
    assert state["candidate_plans"] == []
