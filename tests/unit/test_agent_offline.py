"""Unit tests for SignalSlateAdkAgent exercising ADK 2.8 offline with mocked provider boundary.

Tests:
1. Shared reasoning agent definition with bounded tools
2. Real session creation before runner dispatch
3. before_model_callback turn reservation in PostgreSQL
4. Tool invocation (get_run_events, get_run_metrics, get_shot_context)
5. Strict citation validation:
   - Valid returned citations pass
   - Invented / unreturned citations raise CitationValidationError
   - Omitted citations trigger bounded repair or raise CitationValidationError
   - Missing evidence (0 samples) prevents dispatch
6. Constraint interpretation parses mixer statement
7. Candidate plan generation: Plan A exists before veto, Plan B is feasible and different
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import Client, types
from signal_slate.agent.live_adk import (
    CitationValidationError,
    SignalSlateAdkAgent,
)
from signal_slate.db import get_engine
from signal_slate.domain.models import Constraint, Finding, ObservedRun, ShotContext
from signal_slate.persistence.models import TurnReservation, WorkflowSessionRecord
from signal_slate.persistence.turn_reservations import TurnReservationService
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

TEST_WF_PREFIX = "wf-test-agent-"


@pytest.fixture
def session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture
def db_session(session_factory):
    with session_factory() as session:
        yield session


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


@pytest.fixture
def sample_observed_run():
    from datetime import UTC, datetime, timedelta

    from signal_slate.domain.models import RunConfig, create_evidence_context
    from signal_slate.simulator.engine import SimulatorEngine

    now = datetime.now(UTC)
    start = now - timedelta(seconds=12)
    config = RunConfig()
    sid, rid = "sess-test-1", "run-base-test-1"
    ev, _ = create_evidence_context(sid, config)
    engine = SimulatorEngine()
    samples, metrics, _ = engine.run_rehearsal(
        config,
        start_time_sec=start.timestamp(),
        session_id=sid,
        run_id=rid,
    )
    manifest = engine.create_prepublication_manifest(rid, sid, config, ev, start.isoformat())
    return ObservedRun(
        run_id=rid,
        session_id=sid,
        config_hash=config.config_hash,
        samples=samples,
        metrics=metrics,
        completion_marker_present=True,
        retrieved_sample_count=484,
        start_time_rfc3339=start.isoformat(),
        end_time_rfc3339=now.isoformat(),
        manifest=manifest,
        source_audio_hash=ev.source_audio_hash,
        scenario_path_hash=ev.scenario_path_hash,
        fault_commitment_hash=ev.fault_commitment_hash,
    )


@pytest.mark.asyncio
async def test_agent_investigation_with_valid_citations(
    session_factory, sample_observed_run, cleanup_test_workflows
):
    wf_id = f"{TEST_WF_PREFIX}valid-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    with session_factory() as sess:
        TurnReservationService.ensure_workflow_session(sess, wf_id)

    mock_client = MagicMock(spec=Client)
    mock_generate = AsyncMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    resp_tool = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(
                            name="get_run_events",
                            args={
                                "run_id": sample_observed_run.run_id,
                                "start_ms": 4200,
                                "end_ms": 6800,
                            },
                        )
                    ],
                )
            )
        ]
    )
    resp_final = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="""{
  "status": "RISK_IDENTIFIED",
  "affected_mic": "mic_1",
  "interval_ms": [4200, 6800],
  "observations": ["Observed RF dropout during critical dialogue line"],
  "evidence_ids": ["ev-dropout-mic_1-off4900"],
  "competing_explanations": ["Physical obstruction", "Antenna reflection"],
  "recommended_action": {
    "action_type": "CHANNEL_SWITCH",
    "mic_id": "mic_1",
    "parameters": {"channel": 11}
  }
}"""
                        )
                    ],
                ),
                finish_reason="STOP",
            )
        ]
    )
    mock_generate.side_effect = [resp_tool, resp_final]

    agent = SignalSlateAdkAgent(db_session_factory=session_factory, genai_client=mock_client)
    finding = await agent.investigate_baseline(wf_id, sample_observed_run, ShotContext())

    assert finding.status == "RISK_IDENTIFIED"
    assert finding.affected_mic == "mic_1"
    assert finding.evidence_ids == ["ev-dropout-mic_1-off4900"]
    assert finding.recommended_action.parameters["channel"] == 11

    with session_factory() as sess:
        # 2 turns were reserved for this investigation
        count = TurnReservationService.get_turn_count(sess, wf_id)
        assert count == 2


@pytest.mark.asyncio
async def test_agent_rejects_unreturned_citations(
    session_factory, sample_observed_run, cleanup_test_workflows
):
    wf_id = f"{TEST_WF_PREFIX}bad-cite-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    with session_factory() as sess:
        TurnReservationService.ensure_workflow_session(sess, wf_id)

    mock_client = MagicMock(spec=Client)
    mock_generate = AsyncMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    resp_tool = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(
                            name="get_run_events",
                            args={
                                "run_id": sample_observed_run.run_id,
                                "start_ms": 4200,
                                "end_ms": 6800,
                            },
                        )
                    ],
                )
            )
        ]
    )
    # Model cites an invented / hallucinated evidence ID
    resp_final = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="""{
  "status": "RISK_IDENTIFIED",
  "affected_mic": "mic_1",
  "interval_ms": [4200, 6800],
  "observations": ["Observed RF dropout"],
  "evidence_ids": ["ev-invented-hallucinated-id-999"],
  "competing_explanations": [],
  "recommended_action": {
    "action_type": "CHANNEL_SWITCH",
    "mic_id": "mic_1",
    "parameters": {"channel": 11}
  }
}"""
                        )
                    ],
                ),
                finish_reason="STOP",
            )
        ]
    )
    mock_generate.side_effect = [resp_tool, resp_final]

    agent = SignalSlateAdkAgent(db_session_factory=session_factory, genai_client=mock_client)
    with pytest.raises(CitationValidationError, match="unreturned evidence ID"):
        await agent.investigate_baseline(wf_id, sample_observed_run, ShotContext())


@pytest.mark.asyncio
async def test_missing_evidence_prevents_dispatch(session_factory, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}empty-ev-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    with session_factory() as sess:
        TurnReservationService.ensure_workflow_session(sess, wf_id)

    empty_run = ObservedRun(
        run_id="run-empty",
        session_id="sess-empty",
        config_hash="cfg-empty",
        samples=[],
        metrics=[],
        completion_marker_present=False,
        retrieved_sample_count=0,
        start_time_rfc3339="2026-09-08T00:00:00Z",
        end_time_rfc3339="2026-09-08T00:00:12Z",
    )

    mock_client = MagicMock(spec=Client)
    agent = SignalSlateAdkAgent(db_session_factory=session_factory, genai_client=mock_client)

    with pytest.raises(ValueError, match="Missing evidence"):
        await agent.investigate_baseline(wf_id, empty_run, ShotContext())

    with session_factory() as sess:
        # Zero turns should have been reserved
        assert TurnReservationService.get_turn_count(sess, wf_id) == 0


@pytest.mark.asyncio
async def test_constraint_interpretation_parsing(session_factory, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}const-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    with session_factory() as sess:
        TurnReservationService.ensure_workflow_session(sess, wf_id)

    mock_client = MagicMock(spec=Client)
    mock_generate = AsyncMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    resp_const = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="""{
  "status": "SUPPORTED",
  "constraints": [
    {
      "constraint_id": "c-001",
      "kind": "CHANNEL_EXCLUSION",
      "target_mic": "mic_1",
      "parameters": {"excluded_channel": 11},
      "exact_source_span": "Channel 11 belongs to the next setup",
      "source_text": "Channel 11 belongs to the next setup; leave the costume rig alone.",
      "confirmed": false
    },
    {
      "constraint_id": "c-002",
      "kind": "RIG_LOCK",
      "target_mic": "mic_1",
      "parameters": {},
      "exact_source_span": "leave the costume rig alone",
      "source_text": "Channel 11 belongs to the next setup; leave the costume rig alone.",
      "confirmed": false
    }
  ],
  "rationale": "Sound mixer reserves Channel 11 for next setup and prohibits altering costume rig."
}"""
                        )
                    ],
                ),
                finish_reason="STOP",
            )
        ]
    )
    mock_generate.side_effect = [resp_const]

    agent = SignalSlateAdkAgent(db_session_factory=session_factory, genai_client=mock_client)
    interpretation = await agent.interpret_constraint(
        workflow_id=wf_id,
        human_text="Channel 11 belongs to the next setup; leave the costume rig alone.",
        context=ShotContext(),
    )

    assert interpretation.status == "SUPPORTED"
    assert len(interpretation.constraints) == 2
    assert interpretation.constraints[0].kind == "CHANNEL_EXCLUSION"
    assert interpretation.constraints[0].parameters["excluded_channel"] == 11
    assert interpretation.constraints[1].kind == "RIG_LOCK"


def test_candidate_plan_generation_plan_a_and_plan_b():
    agent = SignalSlateAdkAgent(db_session_factory=MagicMock(), genai_client=MagicMock(spec=Client))
    context = ShotContext()

    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4200, 6800),
        observations=["Dropout"],
        evidence_ids=["ev-dropout-mic_1-off4900"],
        recommended_action={
            "action_type": "CHANNEL_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"channel": 11},
        },
    )

    # 1. Without constraints excluding channel 11: Plan A is generated
    plans_no_constraint = agent.generate_candidate_plans(
        finding=finding,
        confirmed_constraints=[],
        base_config_hash="base-hash",
        context=context,
    )
    assert any(p.plan_id == "plan_a" for p in plans_no_constraint)

    # 2. With constraint excluding channel 11: Plan A is vetoed, Plan B selects Channel 12
    confirmed_constraints = [
        Constraint(
            constraint_id="c-001",
            kind="CHANNEL_EXCLUSION",
            target_mic="mic_1",
            parameters={"excluded_channel": 11},
            exact_source_span="Channel 11 belongs to the next setup",
            source_text="Channel 11 belongs to the next setup",
            confirmed=True,
        )
    ]
    plans_with_constraint = agent.generate_candidate_plans(
        finding=finding,
        confirmed_constraints=confirmed_constraints,
        base_config_hash="base-hash",
        context=context,
    )
    # Plan A is not in feasible plans
    assert not any(p.plan_id == "plan_a" for p in plans_with_constraint)
    plan_b = next((p for p in plans_with_constraint if p.plan_id == "plan_b"), None)
    assert plan_b is not None
    assert plan_b.actions[0].parameters["channel"] == 12
    # No real coordination claims
    assert "simulated" in plan_b.rationale.lower()
    assert any("simulation" in t.lower() for t in plan_b.tradeoffs)


@pytest.mark.parametrize("mutation", ["mic", "interval", "healthy", "run", "config"])
def test_valid_citation_id_cannot_support_wrong_claim(sample_observed_run, mutation):
    from signal_slate.agent.safety import validate_finding_evidence
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    wrapper = BoundedModelEvidenceWrapper(sample_observed_run, ShotContext())
    cid = "ev-dropout-mic_1-off4900"
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Dropout"],
        evidence_ids=[cid],
        recommended_action={
            "action_type": "CHANNEL_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"channel": 11},
        },
    )
    validate_finding_evidence(finding, wrapper, {cid}, ShotContext())
    if mutation == "mic":
        finding.affected_mic = "mic_2"
    elif mutation == "interval":
        finding.interval_ms = (0, 1000)
    elif mutation == "healthy":
        finding.status = "HEALTHY"
    elif mutation == "run":
        wrapper._envelopes[cid].run_id = "another-run"
    else:
        wrapper._envelopes[cid].config_hash = "another-config"
    with pytest.raises(ValueError):
        validate_finding_evidence(finding, wrapper, {cid}, ShotContext())


def test_healthy_metric_id_does_not_establish_risk(sample_observed_run):
    from signal_slate.agent.safety import validate_finding_evidence
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    wrapper = BoundedModelEvidenceWrapper(sample_observed_run, ShotContext())
    cid = "ev-metric-mic_2-sec5"
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_2",
        interval_ms=(4900, 6800),
        observations=["Invented problem"],
        evidence_ids=[cid],
        recommended_action={
            "action_type": "CHANNEL_SWITCH",
            "mic_id": "mic_2",
            "parameters": {"channel": 21},
        },
    )
    with pytest.raises(ValueError, match="Healthy citations"):
        validate_finding_evidence(finding, wrapper, {cid}, ShotContext())


def test_healthy_finding_is_grounded_and_produces_no_action_plan(sample_observed_run):
    from signal_slate.agent.safety import validate_finding_evidence
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    context = ShotContext()
    wrapper = BoundedModelEvidenceWrapper(sample_observed_run, context)
    cid = "ev-metric-mic_2-sec5"
    finding = Finding(
        status="HEALTHY",
        affected_mic="mic_2",
        interval_ms=(4900, 6800),
        observations=["No measured degradation in this microphone interval"],
        evidence_ids=[cid],
        recommended_action={"action_type": "NO_ACTION", "mic_id": "mic_2", "parameters": {}},
    )
    validate_finding_evidence(finding, wrapper, {cid}, context)
    factory = MagicMock()
    agent = SignalSlateAdkAgent(factory, genai_client=MagicMock(spec=Client))
    plans = agent.generate_candidate_plans(finding, [], sample_observed_run.config_hash, context)
    assert all(a.action_type == "NO_ACTION" for p in plans for a in p.actions)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_failed_run_retry_uses_one_shared_repair_turn(
    session_factory, sample_observed_run, cleanup_test_workflows
):
    wf_id = f"{TEST_WF_PREFIX}repair-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)
    with session_factory() as db:
        TurnReservationService.ensure_workflow_session(db, wf_id)
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Observed dropout persists"],
        evidence_ids=["ev-dropout-mic_1-off4900"],
        recommended_action={
            "action_type": "ANTENNA_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"antenna": "B"},
        },
    )
    client = MagicMock(spec=Client)
    client.aio = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text=finding.model_dump_json())]
                    ),
                    finish_reason="STOP",
                )
            ]
        )
    )
    agent = SignalSlateAdkAgent(session_factory, genai_client=client)
    result = await agent.investigate_baseline(
        wf_id, sample_observed_run, ShotContext(), repair_retry=True
    )
    assert result == finding
    assert client.aio.models.generate_content.await_count == 1
    with session_factory() as db:
        from sqlalchemy import select

        turns = list(
            db.scalars(select(TurnReservation).where(TurnReservation.workflow_id == wf_id))
        )
        assert len(turns) == 1
        assert turns[0].operation_type == "repair" and turns[0].status == "COMPLETED"
    with pytest.raises(Exception, match="budget|Budget"):
        await agent.investigate_baseline(
            wf_id, sample_observed_run, ShotContext(), repair_retry=True
        )
    assert client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_kind", ["schema", "citation"])
async def test_invalid_finding_gets_only_one_validated_shared_repair(
    session_factory, sample_observed_run, cleanup_test_workflows, bad_kind
):
    import json

    wf_id = f"{TEST_WF_PREFIX}schema-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)
    with session_factory() as db:
        TurnReservationService.ensure_workflow_session(db, wf_id)
    good = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Observed dropout"],
        evidence_ids=["ev-dropout-mic_1-off4900"],
        recommended_action={
            "action_type": "ANTENNA_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"antenna": "B"},
        },
    ).model_dump(mode="json")
    bad = good | ({"affected_mic": None} if bad_kind == "schema" else {"interval_ms": [0, 1000]})

    def response(parts):
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(role="model", parts=parts), finish_reason="STOP"
                )
            ]
        )

    client = MagicMock(spec=Client)
    client.aio = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        side_effect=[
            response(
                [
                    types.Part.from_function_call(
                        name="get_run_events", args={"run_id": sample_observed_run.run_id}
                    )
                ]
            ),
            response([types.Part.from_text(text=json.dumps(bad))]),
            response([types.Part.from_text(text=json.dumps(good))]),
        ]
    )
    agent = SignalSlateAdkAgent(session_factory, genai_client=client)
    result = await agent.investigate_baseline(wf_id, sample_observed_run, ShotContext())
    assert result.affected_mic == "mic_1" and result.interval_ms == (4900, 6800)
    assert client.aio.models.generate_content.await_count == 3
    with session_factory() as db:
        from sqlalchemy import select

        turns = list(
            db.scalars(select(TurnReservation).where(TurnReservation.workflow_id == wf_id))
        )
        assert sorted(t.operation_type for t in turns) == [
            "investigation",
            "investigation",
            "repair",
        ]


def test_isolated_clipping_rejects_frequency_fix(sample_observed_run):
    from signal_slate.agent.safety import validate_finding_evidence
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    run = sample_observed_run.model_copy(deep=True)
    for sample in run.samples:
        if sample.mic_id == "mic_1":
            sample.is_dropout = False
            sample.quality = 90
            sample.link_margin_db = 25
            sample.is_clipped = 4900 <= sample.offset_ms < 6800
    wrapper = BoundedModelEvidenceWrapper(run, ShotContext())
    cid = next(
        cid
        for cid, env in wrapper._envelopes.items()
        if env.mic_id == "mic_1" and env.offset_ms == 4900
    )
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4900, 6800),
        observations=["Clipping with healthy RF"],
        evidence_ids=[cid],
        recommended_action={
            "action_type": "CHANNEL_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"channel": 11},
        },
    )
    with pytest.raises(ValueError, match="isolated clipping"):
        validate_finding_evidence(finding, wrapper, {cid}, ShotContext())
    finding.recommended_action.action_type = "BOOM_COVERAGE"
    finding.recommended_action.parameters = {"source_mic": "mic_4"}
    validate_finding_evidence(finding, wrapper, {cid}, ShotContext())


def test_citation_at_exclusive_end_is_rejected_but_enclosed_sample_passes(sample_observed_run):
    from signal_slate.agent.safety import validate_finding_evidence
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    wrapper = BoundedModelEvidenceWrapper(sample_observed_run, ShotContext())
    cid = "ev-dropout-mic_1-off4900"
    finding = Finding(
        status="RISK_IDENTIFIED",
        affected_mic="mic_1",
        interval_ms=(4800, 4900),
        observations=["Dropout"],
        evidence_ids=[cid],
        recommended_action={
            "action_type": "CHANNEL_SWITCH",
            "mic_id": "mic_1",
            "parameters": {"channel": 11},
        },
    )
    with pytest.raises(ValueError, match="End is exclusive"):
        validate_finding_evidence(finding, wrapper, {cid}, ShotContext())
    finding.interval_ms = (4800, 5000)
    validate_finding_evidence(finding, wrapper, {cid}, ShotContext())


def test_wrapper_query_windows_match_exclusive_citation_intervals(sample_observed_run):
    from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper

    # A degrading sample begins exactly at the excluded endpoint.
    run = sample_observed_run.model_copy(deep=True)
    for sample in run.samples:
        if sample.mic_id == "mic_1" and sample.offset_ms in (6700, 6800):
            sample.quality = 30
            sample.is_dropout = True
    wrapper = BoundedModelEvidenceWrapper(run, ShotContext())
    events = wrapper.get_run_events(run.run_id, ["mic_1"], 4900, 6800)
    assert any(row["offset_ms"] == 6700 for row in events)
    assert all(4900 <= row["offset_ms"] < 6800 for row in events)
    # Include the bucket that overlaps the start, not just bucket start times.
    metrics = wrapper.get_run_metrics(run.run_id, ["mic_1"], 4900, 6000)
    assert [row["offset_ms"] for row in metrics] == [4000, 5000]
    # A sub-sample interval still retrieves its overlapping observation.
    assert [
        row["offset_ms"] for row in wrapper.get_run_events(run.run_id, ["mic_1"], 6750, 6770)
    ] == [6700]
    for start, end in ((6800, 6800), (6900, 6800)):
        assert wrapper.get_run_metrics(run.run_id, ["mic_1"], start, end) == []
        assert wrapper.get_run_events(run.run_id, ["mic_1"], start, end) == []
