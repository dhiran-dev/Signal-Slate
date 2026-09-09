"""Unit tests for plan approval exact hash, version binding, and authoritative validation."""

import pytest
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    PlanApproval,
    ShotContext,
    actions_hash,
    canonical_hash,
)
from signal_slate.workflow.orchestrator import (
    StaleApprovalError,
    TamperedActionError,
    UnapprovedPlanError,
    validate_authoritative_approval,
)


@pytest.fixture
def sample_context():
    return ShotContext()


@pytest.fixture
def sample_plan_b():
    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 12}
    )
    constraints = [
        Constraint(
            constraint_id="c-001",
            kind="CHANNEL_EXCLUSION",
            target_mic="mic_1",
            parameters={"excluded_channel": 11},
            exact_source_span="Channel 11 belongs to next setup",
            source_text="Channel 11 belongs to next setup",
            confirmed=True,
        )
    ]
    chash = canonical_hash([c.model_dump(mode="json") for c in constraints])
    base_cfg_hash = "base_cfg_test_hash"

    plan = CandidatePlan(
        plan_id="plan_b",
        plan_version=1,
        actions=[action],
        action_hash=actions_hash([action]),
        constraints_hash=chash,
        base_config_hash=base_cfg_hash,
        rationale="Switch mic_1 to Channel 12 (simulated alternative)",
        tradeoffs=["Declared simulation fixture alternative"],
    )
    return plan, constraints, base_cfg_hash


def test_matching_approval_verifies_successfully(sample_context, sample_plan_b):
    plan, constraints, base_cfg_hash = sample_plan_b

    approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    # Basic model verify_match
    assert approval.verify_match(plan) is True

    # Authoritative verification passes without error
    validate_authoritative_approval(
        approval=approval,
        plan=plan,
        context=sample_context,
        confirmed_constraints=constraints,
        expected_base_config_hash=base_cfg_hash,
    )


def test_approval_hash_mismatch_fails_verification(sample_context, sample_plan_b):
    plan, constraints, base_cfg_hash = sample_plan_b

    stale_approval = PlanApproval(
        plan_id="plan_b",
        plan_version=1,
        action_hash="stale_altered_action_hash",
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    assert stale_approval.verify_match(plan) is False
    with pytest.raises(StaleApprovalError, match="drift"):
        validate_authoritative_approval(
            approval=stale_approval,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )


def test_approval_version_mismatch_fails(sample_context, sample_plan_b):
    plan, constraints, base_cfg_hash = sample_plan_b

    approval_v2 = PlanApproval(
        plan_id="plan_b",
        plan_version=2,  # Stale version 2 vs plan version 1
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    assert approval_v2.verify_match(plan) is False
    with pytest.raises(StaleApprovalError):
        validate_authoritative_approval(
            approval=approval_v2,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )


def test_authoritative_approval_rejects_approved_false(sample_context, sample_plan_b):
    plan, constraints, base_cfg_hash = sample_plan_b

    denied_approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=False,  # Human explicitly denied approval
    )

    with pytest.raises(UnapprovedPlanError, match="approved=False"):
        validate_authoritative_approval(
            approval=denied_approval,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )


def test_authoritative_approval_rejects_tampered_action_even_with_unchanged_stored_hash(
    sample_context, sample_plan_b
):
    plan, constraints, base_cfg_hash = sample_plan_b

    # Tamper with action parameter (mutating channel to 999) without updating stored action_hash
    plan.actions[0].parameters["channel"] = 999

    approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        action_hash=plan.action_hash,  # Matches stored (stale) action_hash
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    # Note: domain verify_match might pass because stored hashes match
    assert approval.verify_match(plan) is True

    # BUT authoritative validation MUST catch the tampering!
    with pytest.raises(TamperedActionError, match="not available"):
        validate_authoritative_approval(
            approval=approval,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )


def test_authoritative_approval_rejects_unknown_mic_target(sample_context, sample_plan_b):
    plan, constraints, base_cfg_hash = sample_plan_b

    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_unknown_99", parameters={"channel": 12}
    )
    plan.actions = [action]
    plan.action_hash = actions_hash([action])

    approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    with pytest.raises(TamperedActionError, match="unknown microphone"):
        validate_authoritative_approval(
            approval=approval,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )


def test_authoritative_approval_rejects_action_violating_confirmed_constraint(
    sample_context, sample_plan_b
):
    plan, constraints, base_cfg_hash = sample_plan_b

    # Action proposes Channel 11, but constraints exclude Channel 11
    action = CandidateAction(
        action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 11}
    )
    plan.actions = [action]
    plan.action_hash = actions_hash([action])

    approval = PlanApproval(
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        action_hash=plan.action_hash,
        constraints_hash=plan.constraints_hash,
        base_config_hash=plan.base_config_hash,
        approved=True,
    )

    with pytest.raises(TamperedActionError, match="violates confirmed exclusion"):
        validate_authoritative_approval(
            approval=approval,
            plan=plan,
            context=sample_context,
            confirmed_constraints=constraints,
            expected_base_config_hash=base_cfg_hash,
        )
