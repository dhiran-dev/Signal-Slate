"""Integration tests for Phase 1 live vertical slice.

Opt-in test suite requiring LIVE_TESTS_ENABLED=true.
Zero mock runtime fallback: executes against real Google ADK/Vertex AI and Grafana Cloud MCP.
"""

import os

import pytest
from signal_slate.workflow.orchestrator import (
    LiveWorkflowOrchestrator,
    NoFeasiblePlanError,
    StaleApprovalError,
)

LIVE_ENABLED = os.environ.get("LIVE_TESTS_ENABLED", "").lower() in ("true", "1", "yes")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_ENABLED, reason="Live integration test requires LIVE_TESTS_ENABLED=true"
)
async def test_live_slice_end_to_end_success():
    """Execute complete live central loop:

    genuine baseline -> fresh Grafana MCP evidence -> ADK investigation ->
    human constraint interpretation -> candidate plan B -> exact version/hash approval ->
    apply simulator -> fresh comparison -> deterministic cloud verification (VERIFIED).
    """
    orchestrator = LiveWorkflowOrchestrator()
    result = await orchestrator.execute_live_slice()

    assert result["status"] == "PASS"
    assert result["verification"]["terminal_status"] == "VERIFIED"
    assert result["verification"]["completeness_passed"] is True
    assert result["verification"]["crosscheck_passed"] is True
    assert result["verification"]["thresholds_passed"] is True
    assert result["verification"]["dialogue_coverage_passed"] is True
    assert result["verification"]["constraints_passed"] is True
    assert len(result["finding"]["evidence_ids"]) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_ENABLED, reason="Live integration test requires LIVE_TESTS_ENABLED=true"
)
async def test_live_negative_stale_approval_returns_409():
    """Negative case: Stale plan approval with corrupted hash is rejected."""
    orchestrator = LiveWorkflowOrchestrator()
    with pytest.raises(StaleApprovalError, match="HTTP 409 Conflict"):
        await orchestrator.execute_live_slice(negative_case="stale_approval")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_ENABLED, reason="Live integration test requires LIVE_TESTS_ENABLED=true"
)
async def test_live_negative_impossible_constraint():
    """Negative case: Conflicting/impossible constraints yield NO_FEASIBLE_PLAN."""
    orchestrator = LiveWorkflowOrchestrator()
    with pytest.raises(NoFeasiblePlanError, match="NO_FEASIBLE_PLAN"):
        await orchestrator.execute_live_slice(negative_case="impossible_constraint")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_ENABLED, reason="Live integration test requires LIVE_TESTS_ENABLED=true"
)
async def test_live_negative_model_unavailable():
    """Negative case: Model unavailable fails cleanly without silent mock fallback."""
    from signal_slate.agent.live_adk import ModelUnavailableError

    orchestrator = LiveWorkflowOrchestrator()
    with pytest.raises(ModelUnavailableError, match="Simulated Vertex AI unavailability"):
        await orchestrator.execute_live_slice(negative_case="model_unavailable")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_ENABLED, reason="Live integration test requires LIVE_TESTS_ENABLED=true"
)
async def test_live_negative_grafana_failure_after_apply():
    """Negative case: Grafana failure after apply fails cleanly without mock fallback."""
    orchestrator = LiveWorkflowOrchestrator()
    with pytest.raises(RuntimeError, match="Grafana Cloud query failure after apply"):
        await orchestrator.execute_live_slice(negative_case="grafana_failure_after_apply")
