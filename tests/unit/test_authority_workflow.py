"""Unit tests for stepwise authoritative workflow orchestrator."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import Client, types
from signal_slate.db import get_engine
from signal_slate.domain.models import (
    Constraint,
)
from signal_slate.persistence.models import TurnReservation, WorkflowSessionRecord
from signal_slate.workflow.orchestrator import (
    AmbiguousConstraintError,
    ContradictoryConstraintError,
    LiveWorkflowOrchestrator,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

TEST_WF_PREFIX = "wf-test-wf-"


@pytest.fixture
def session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture(autouse=True)
def cleanup_test_workflows(session_factory):
    """Clean up only own test-prefixed workflows."""
    created_wf_ids: list[str] = []
    yield created_wf_ids
    with session_factory() as session:
        with session.begin():
            for wf_id in created_wf_ids:
                session.execute(delete(TurnReservation).where(TurnReservation.workflow_id == wf_id))
                session.execute(
                    delete(WorkflowSessionRecord).where(WorkflowSessionRecord.workflow_id == wf_id)
                )


@pytest.mark.asyncio
async def test_ambiguous_constraint_pauses_workflow(session_factory, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}ambig-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    mock_client = MagicMock(spec=Client)
    mock_generate = AsyncMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    resp_ambig = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                '{"status": "AMBIGUOUS", "constraints": [], '
                                '"rationale": "Statement lacks actionable direction."}'
                            )
                        )
                    ],
                ),
                finish_reason="STOP",
            )
        ]
    )
    mock_generate.side_effect = [resp_ambig]

    orchestrator = LiveWorkflowOrchestrator(
        db_session_factory=session_factory, genai_client=mock_client
    )
    # Start workflow durably
    sid = f"sess-{wf_id}"
    orchestrator._get_or_create_durable_workflow(wf_id, sid)
    orchestrator._runs[wf_id] = {
        "session_id": sid,
        "trace_log": [],
    }

    with pytest.raises(AmbiguousConstraintError, match="AMBIGUOUS"):
        await orchestrator.interpret_constraint(wf_id, "Maybe do something about sound")

    # Verify durable state is PAUSED_AMBIGUOUS_CONSTRAINT
    with session_factory() as sess:
        rec = sess.scalar(
            select(WorkflowSessionRecord).where(WorkflowSessionRecord.workflow_id == wf_id)
        )
        assert rec is not None
        assert rec.state == "PAUSED_AMBIGUOUS_CONSTRAINT"


@pytest.mark.asyncio
async def test_contradictory_constraint_pauses_workflow(session_factory, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}contra-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    mock_client = MagicMock(spec=Client)
    mock_generate = AsyncMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    resp_contra = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                '{"status": "CONTRADICTORY", "constraints": [], '
                                '"rationale": "Statement requests disabling all RF while '
                                'demanding wireless coverage."}'
                            )
                        )
                    ],
                ),
                finish_reason="STOP",
            )
        ]
    )
    mock_generate.side_effect = [resp_contra]

    orchestrator = LiveWorkflowOrchestrator(
        db_session_factory=session_factory, genai_client=mock_client
    )
    sid = f"sess-{wf_id}"
    orchestrator._get_or_create_durable_workflow(wf_id, sid)
    orchestrator._runs[wf_id] = {"session_id": sid, "trace_log": []}

    with pytest.raises(ContradictoryConstraintError, match="CONTRADICTORY"):
        await orchestrator.interpret_constraint(
            wf_id, "Turn off all channels but make sure wireless works"
        )

    with session_factory() as sess:
        rec = sess.scalar(
            select(WorkflowSessionRecord).where(WorkflowSessionRecord.workflow_id == wf_id)
        )
        assert rec is not None
        assert rec.state == "PAUSED_CONTRADICTORY_CONSTRAINT"


def test_confirm_constraints_rejects_unconfirmed_constraint(
    session_factory, cleanup_test_workflows
):
    wf_id = f"{TEST_WF_PREFIX}unconfirmed-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    orchestrator = LiveWorkflowOrchestrator(db_session_factory=session_factory)
    sid = f"sess-{wf_id}"
    orchestrator._get_or_create_durable_workflow(wf_id, sid)
    orchestrator._runs[wf_id] = {"session_id": sid, "trace_log": []}

    unconfirmed = [
        Constraint(
            constraint_id="c-1",
            kind="CHANNEL_EXCLUSION",
            target_mic="mic_1",
            parameters={"excluded_channel": 11},
            exact_source_span="Channel 11",
            source_text="Channel 11",
            confirmed=False,  # Unconfirmed!
        )
    ]

    with pytest.raises(ValueError, match="not confirmed"):
        orchestrator.generate_candidate_plans(wf_id, unconfirmed)
