"""Unit and concurrency tests for durable turn reservations and budget enforcement in PostgreSQL.

Exercises:
1. Stable parent row lock before budget count
2. Concurrency test with 8 concurrent claims on empty initial state: exactly max 5 succeed, 3 fail
3. Per-operation budget enforcement (2 investigation, 2 replan, 1 repair)
4. Rejection of unknown workflows (WorkflowNotFoundError)
5. Rejection of reused attempts (AttemptAlreadyUsedError)
6. Terminal uncertain status persistence and budget consumption
7. Clean up only own test-prefixed workflows
"""

import concurrent.futures
import uuid

import pytest
from signal_slate.db import get_engine
from signal_slate.persistence.models import TurnReservation, WorkflowSessionRecord
from signal_slate.persistence.turn_reservations import (
    AttemptAlreadyUsedError,
    TurnBudgetExceededError,
    TurnReservationService,
    WorkflowNotFoundError,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

TEST_WF_PREFIX = "wf-test-suite-"


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


def test_turn_reservation_requires_durable_parent(db_session):
    unknown_wf_id = f"{TEST_WF_PREFIX}unknown-{uuid.uuid4().hex[:8]}"
    att_id = f"att-{uuid.uuid4().hex[:6]}"

    with pytest.raises(WorkflowNotFoundError, match="does not exist"):
        TurnReservationService.reserve_turn(
            session=db_session,
            workflow_id=unknown_wf_id,
            attempt_id=att_id,
            operation_type="investigation",
            max_turns=5,
        )


def test_turn_reservation_rejects_reused_attempt(db_session, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}att-reuse-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)
    TurnReservationService.ensure_workflow_session(db_session, wf_id)

    att_id = f"att-shared-{uuid.uuid4().hex[:6]}"

    t1 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=att_id,
        operation_type="investigation",
        max_turns=5,
    )
    assert t1 == 1

    with pytest.raises(AttemptAlreadyUsedError, match="already been used"):
        TurnReservationService.reserve_turn(
            session=db_session,
            workflow_id=wf_id,
            attempt_id=att_id,
            operation_type="investigation",
            max_turns=5,
        )


def test_per_operation_budgets_enforced(db_session, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}per-op-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)
    TurnReservationService.ensure_workflow_session(db_session, wf_id)

    # 1. Investigation allows max 2
    t1 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=f"att-inv-1-{uuid.uuid4().hex[:6]}",
        operation_type="investigation",
        max_turns=5,
    )
    assert t1 == 1

    t2 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=f"att-inv-2-{uuid.uuid4().hex[:6]}",
        operation_type="investigation",
        max_turns=5,
    )
    assert t2 == 2

    with pytest.raises(
        TurnBudgetExceededError, match="Operation budget exceeded for 'investigation': 2/2"
    ):
        TurnReservationService.reserve_turn(
            session=db_session,
            workflow_id=wf_id,
            attempt_id=f"att-inv-3-{uuid.uuid4().hex[:6]}",
            operation_type="investigation",
            max_turns=5,
        )

    # 2. Replan allows max 2
    t3 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=f"att-rep-1-{uuid.uuid4().hex[:6]}",
        operation_type="replan",
        max_turns=5,
    )
    assert t3 == 3

    t4 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=f"att-rep-2-{uuid.uuid4().hex[:6]}",
        operation_type="constraint_interpretation",
        max_turns=5,
    )
    assert t4 == 4

    with pytest.raises(TurnBudgetExceededError, match="Operation budget exceeded for 'replan'"):
        TurnReservationService.reserve_turn(
            session=db_session,
            workflow_id=wf_id,
            attempt_id=f"att-rep-3-{uuid.uuid4().hex[:6]}",
            operation_type="replan",
            max_turns=5,
        )

    # 3. Repair allows max 1
    t5 = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=f"att-fix-1-{uuid.uuid4().hex[:6]}",
        operation_type="repair",
        max_turns=5,
    )
    assert t5 == 5

    with pytest.raises(TurnBudgetExceededError, match="Turn budget exceeded: 5/5"):
        TurnReservationService.reserve_turn(
            session=db_session,
            workflow_id=wf_id,
            attempt_id=f"att-fix-2-{uuid.uuid4().hex[:6]}",
            operation_type="repair",
            max_turns=5,
        )


def test_concurrent_initial_reservations_race_condition(session_factory, cleanup_test_workflows):
    """Eight concurrent initial reservation transactions synchronized on empty workflow.

    Proves that parent row lock serializes claims and exactly max 5 succeed.
    """
    wf_id = f"{TEST_WF_PREFIX}race-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)

    with session_factory() as session:
        TurnReservationService.ensure_workflow_session(session, wf_id)

    num_threads = 8
    successes: list[int] = []
    failures: list[Exception] = []

    def claim_turn(worker_idx: int) -> int:
        att_id = f"att-race-{worker_idx}-{uuid.uuid4().hex[:6]}"
        with session_factory() as session:
            # Operation alternates between investigation, replan, repair
            op = "investigation" if worker_idx < 2 else ("replan" if worker_idx < 4 else "repair")
            return TurnReservationService.reserve_turn(
                session=session,
                workflow_id=wf_id,
                attempt_id=att_id,
                operation_type=op,
                max_turns=5,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(claim_turn, i): i for i in range(num_threads)}
        for future in concurrent.futures.as_completed(futures):
            try:
                turn = future.result()
                successes.append(turn)
            except Exception as exc:
                failures.append(exc)

    assert len(successes) == 5, (
        f"Expected exactly 5 successful claims, got {len(successes)}: {successes}"
    )
    assert len(failures) == 3, f"Expected exactly 3 failed claims, got {len(failures)}: {failures}"
    assert sorted(successes) == [1, 2, 3, 4, 5], (
        f"Turn numbers must be exactly [1, 2, 3, 4, 5], got {successes}"
    )

    # Verify rows in PostgreSQL
    with session_factory() as session:
        reservations = TurnReservationService.get_reservations(session, wf_id)
        assert len(reservations) == 5
        assert [r.turn_number for r in reservations] == [1, 2, 3, 4, 5]


def test_record_turn_result_uncertain_consumes_budget(db_session, cleanup_test_workflows):
    wf_id = f"{TEST_WF_PREFIX}uncertain-{uuid.uuid4().hex[:8]}"
    cleanup_test_workflows.append(wf_id)
    TurnReservationService.ensure_workflow_session(db_session, wf_id)

    att_id = f"att-unc-{uuid.uuid4().hex[:6]}"
    turn_num = TurnReservationService.reserve_turn(
        session=db_session,
        workflow_id=wf_id,
        attempt_id=att_id,
        operation_type="investigation",
        max_turns=5,
    )
    assert turn_num == 1

    # Record UNCERTAIN status
    TurnReservationService.record_turn_result(
        session=db_session,
        attempt_id=att_id,
        status="UNCERTAIN",
    )

    record = db_session.scalar(select(TurnReservation).where(TurnReservation.attempt_id == att_id))
    assert record is not None
    assert record.status == "UNCERTAIN"

    # Count of reservations is 1; the uncertain turn consumes budget
    assert TurnReservationService.get_turn_count(db_session, wf_id) == 1
