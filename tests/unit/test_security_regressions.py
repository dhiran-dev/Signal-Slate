"""Regression tests for approval tampering and cross-session tool access."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from signal_slate.agent.live_adk import SignalSlateAdkAgent
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    PlanApproval,
    RunConfig,
    ShotContext,
    actions_hash,
    canonical_hash,
)
from signal_slate.workflow.orchestrator import (
    LiveWorkflowOrchestrator,
    StaleApprovalError,
    validate_authoritative_approval,
)


def plan_and_approval():
    actions = [
        CandidateAction(action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}),
        CandidateAction(action_type="CHANNEL_SWITCH", mic_id="mic_2", parameters={"channel": 21}),
    ]
    plan = CandidatePlan(
        plan_id="p",
        actions=actions,
        action_hash=actions_hash(actions),
        constraints_hash=canonical_hash([]),
        base_config_hash=RunConfig().config_hash,
        rationale="Two approved actions",
    )
    approval = PlanApproval(
        plan_id="p",
        plan_version=1,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )
    return plan, approval


@pytest.mark.parametrize("mutation", ["append", "remove", "reorder", "change"])
def test_entire_ordered_action_list_is_bound(mutation):
    plan, approval = plan_and_approval()
    validate_authoritative_approval(approval, plan, ShotContext(), [], plan.base_config_hash)
    if mutation == "append":
        plan.actions.append(CandidateAction(action_type="NO_ACTION", mic_id="mic_3", parameters={}))
    elif mutation == "remove":
        plan.actions.pop()
    elif mutation == "reorder":
        plan.actions.reverse()
    else:
        plan.actions[1].parameters["channel"] = 20
    with pytest.raises(StaleApprovalError):
        validate_authoritative_approval(approval, plan, ShotContext(), [], plan.base_config_hash)


@pytest.mark.parametrize("session_id", [None, "foreign"])
def test_missing_or_foreign_tool_context_never_uses_another_session(session_id):
    agent = object.__new__(SignalSlateAdkAgent)
    agent._session_data = {"a": {"owner": "a"}, "b": {"owner": "b"}}
    context = SimpleNamespace(session=SimpleNamespace(id=session_id)) if session_id else None
    with pytest.raises(ValueError, match="trusted tool session"):
        agent._resolve_session_data(context)
    assert agent._resolve_session_data(SimpleNamespace(session=SimpleNamespace(id="a"))) == {
        "owner": "a"
    }


@pytest.mark.asyncio
async def test_apply_rechecks_approval_before_any_simulation_or_publication():
    plan, approval = plan_and_approval()
    plan.actions[1].parameters["channel"] = 20
    orchestrator = object.__new__(LiveWorkflowOrchestrator)
    orchestrator.context = ShotContext()
    orchestrator.simulator = Mock()
    orchestrator.publisher = Mock()
    orchestrator._runs = {
        "wf": {
            "approved_plan": plan,
            "approval": approval,
            "confirmed_constraints": [],
            "base_config": RunConfig(),
        }
    }
    with pytest.raises(StaleApprovalError):
        await orchestrator.apply_and_verify("wf")
    orchestrator.simulator.run_rehearsal.assert_not_called()
    orchestrator.publisher.publish_run.assert_not_called()


@pytest.mark.asyncio
async def test_new_constraint_invalidates_approval_even_if_interpretation_fails():
    from unittest.mock import AsyncMock

    plan, approval = plan_and_approval()
    orchestrator = object.__new__(LiveWorkflowOrchestrator)
    orchestrator.context = ShotContext()
    orchestrator.agent = Mock()
    orchestrator.agent.interpret_constraint = AsyncMock(side_effect=RuntimeError("offline failure"))
    orchestrator._runs = {"wf": {"approved_plan": plan, "approval": approval}}
    with pytest.raises(RuntimeError, match="offline failure"):
        await orchestrator.interpret_constraint("wf", "Lock the rig")
    assert "approval" not in orchestrator._runs["wf"]
    assert "approved_plan" not in orchestrator._runs["wf"]


@pytest.mark.asyncio
async def test_finding_change_invalidates_application_and_approval_is_snapshot():
    plan, approval = plan_and_approval()
    orchestrator = object.__new__(LiveWorkflowOrchestrator)
    orchestrator.context = ShotContext()
    orchestrator._update_durable_state = Mock()
    finding = Mock()
    finding.model_dump.return_value = {"status": "RISK_IDENTIFIED", "evidence_ids": ["e1"]}
    orchestrator._runs = {
        "wf": {
            "candidate_plans": [plan],
            "confirmed_constraints": [],
            "base_config": RunConfig(),
            "finding": finding,
            "trace_log": [],
        }
    }
    orchestrator.approve_plan("wf", approval)
    assert orchestrator._runs["wf"]["approved_plan"] is not plan
    assert orchestrator._runs["wf"]["approval"] is not approval
    finding.model_dump.return_value = {"status": "HEALTHY", "evidence_ids": ["e2"]}
    with pytest.raises(StaleApprovalError, match="Finding or shot context changed"):
        await orchestrator.apply_and_verify("wf")
