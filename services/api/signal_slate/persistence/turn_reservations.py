"""Turn reservation service with durable row-level locking in PostgreSQL.

Ensures strict enforcement of turn budgets:
- Max 5 model turns total per rehearsal workflow
- Per-operation budgets: 2 investigation, 2 replan/constraint interpretation, 1 shared repair
- Parent row lock (WorkflowSessionRecord) before budget count prevents concurrency races
- Unique attempt before dispatch; reused attempts rejected
- Terminal uncertain budget consumed
- CRITICAL ARCHITECTURAL BOUNDARY: Network and model dispatches happen strictly outside
  SQL transactions.
"""

from typing import Any

from signal_slate.persistence.models import TurnReservation, WorkflowSessionRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class TurnBudgetExceededError(Exception):
    """Raised when the workflow or operation model turn budget is exceeded."""


class WorkflowNotFoundError(Exception):
    """Raised when turn reservation is requested for a nonexistent workflow parent."""


class AttemptAlreadyUsedError(Exception):
    """Raised when an attempt ID is reused for multiple dispatches."""


class InvalidOperationTypeError(Exception):
    """Raised when an unsupported operation type is provided."""


OPERATION_BUDGETS: dict[str, int] = {
    "investigation": 2,
    "replan": 2,
    "constraint_interpretation": 2,
    "repair": 1,
}

VALID_STATUSES = {"RESERVED", "COMPLETED", "FAILED", "UNCERTAIN"}


def _normalize_op(op: str) -> str:
    if op in ("replan", "constraint_interpretation"):
        return "replan"
    return op


class TurnReservationService:
    @staticmethod
    def ensure_workflow_session(
        session: Session,
        workflow_id: str,
        session_id: str | None = None,
        state: str = "READY",
        metadata_json: dict[str, Any] | None = None,
    ) -> WorkflowSessionRecord:
        """Create parent WorkflowSessionRecord durably if it does not exist."""
        with session.begin():
            rec = session.scalar(
                select(WorkflowSessionRecord).where(
                    WorkflowSessionRecord.workflow_id == workflow_id
                )
            )
            if rec is None:
                rec = WorkflowSessionRecord(
                    session_id=session_id or f"sess-{workflow_id}",
                    workflow_id=workflow_id,
                    state=state,
                    metadata_json=metadata_json,
                )
                session.add(rec)
                session.flush()
            return rec

    @staticmethod
    def reserve_turn(
        session: Session,
        workflow_id: str,
        attempt_id: str,
        operation_type: str,
        max_turns: int = 5,
    ) -> int:
        """Reserve a model turn in PostgreSQL before remote dispatch.

        1. Locks parent WorkflowSessionRecord row (SELECT ... FOR UPDATE) to serialize claims.
        2. Rejects unknown workflows.
        3. Enforces unique attempt identity (reused attempt rejected).
        4. Enforces workflow total turn budget (max 5) and per-operation limits
           (2 inv, 2 replan, 1 repair).
        5. Inserts reservation with unique turn_number.
        Commit commits immediately so model dispatch executes STRICTLY OUTSIDE SQL txn.
        """
        norm_op = _normalize_op(operation_type)
        if norm_op not in ("investigation", "replan", "repair"):
            raise InvalidOperationTypeError(
                f"Unsupported operation type '{operation_type}'. "
                f"Must be one of: investigation, replan, constraint_interpretation, repair."
            )

        with session.begin():
            # Step 1: Stable parent row lock before budget count
            parent = session.scalar(
                select(WorkflowSessionRecord)
                .where(WorkflowSessionRecord.workflow_id == workflow_id)
                .with_for_update()
            )
            if parent is None:
                raise WorkflowNotFoundError(
                    f"Workflow '{workflow_id}' does not exist. Workflow parent must be created "
                    f"durably before reserving turns."
                )

            # Step 2: Attempt uniqueness check
            existing_att = session.scalar(
                select(TurnReservation).where(TurnReservation.attempt_id == attempt_id)
            )
            if existing_att is not None:
                raise AttemptAlreadyUsedError(
                    f"Attempt ID '{attempt_id}' has already been used. "
                    f"Each dispatch requires a fresh unique attempt ID."
                )

            # Step 3: Count existing reservations for this workflow
            reservations = list(
                session.scalars(
                    select(TurnReservation)
                    .where(TurnReservation.workflow_id == workflow_id)
                    .order_by(TurnReservation.turn_number)
                ).all()
            )
            current_total = len(reservations)

            if current_total >= max_turns:
                raise TurnBudgetExceededError(
                    f"Turn budget exceeded: {current_total}/{max_turns} turns already reserved "
                    f"for workflow {workflow_id}."
                )

            # Step 4: Check per-operation budget
            op_limit = OPERATION_BUDGETS.get(norm_op, 2)
            op_count = sum(1 for r in reservations if _normalize_op(r.operation_type) == norm_op)
            if op_count >= op_limit:
                raise TurnBudgetExceededError(
                    f"Operation budget exceeded for '{operation_type}': "
                    f"{op_count}/{op_limit} turns already reserved."
                )

            # Step 5: Reserve unique turn number
            turn_number = current_total + 1
            reservation = TurnReservation(
                workflow_id=workflow_id,
                attempt_id=attempt_id,
                turn_number=turn_number,
                operation_type=operation_type,
                status="RESERVED",
            )
            session.add(reservation)

        # Committed. Out-of-transaction network execution can proceed.
        return turn_number

    @staticmethod
    def record_turn_result(
        session: Session,
        attempt_id: str,
        status: str,  # COMPLETED, FAILED, UNCERTAIN
    ) -> None:
        """Record the terminal status of a reserved turn after external execution completes."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid turn status: {status}. Must be one of {VALID_STATUSES}")

        with session.begin():
            res = session.scalar(
                select(TurnReservation)
                .where(TurnReservation.attempt_id == attempt_id)
                .with_for_update()
            )
            if res:
                res.status = status

    @staticmethod
    def get_turn_count(session: Session, workflow_id: str) -> int:
        """Get the count of reserved turns for a workflow."""
        return (
            session.scalar(
                select(func.count(TurnReservation.id)).where(
                    TurnReservation.workflow_id == workflow_id
                )
            )
            or 0
        )

    @staticmethod
    def get_reservations(session: Session, workflow_id: str) -> list[TurnReservation]:
        """Get all reservations for a workflow ordered by turn number."""
        return list(
            session.scalars(
                select(TurnReservation)
                .where(TurnReservation.workflow_id == workflow_id)
                .order_by(TurnReservation.turn_number)
            ).all()
        )
