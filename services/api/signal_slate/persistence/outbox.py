"""Immutable, replayable publication without database transactions around I/O."""

from collections.abc import Callable
from typing import Any

from signal_slate.domain.models import canonical_hash
from signal_slate.persistence.models import PublicationOutbox
from sqlalchemy import select


class OutboxStore:
    def __init__(self, factory: Any, guard: Callable[[], None] | None = None):
        self.factory = factory
        self.guard = guard or (lambda: None)

    def load(self, run_id: str) -> dict | None:
        self.guard()
        with self.factory() as db:
            rec = db.get(PublicationOutbox, run_id)
            if not rec:
                return None
            if canonical_hash(rec.payload) != rec.payload_hash:
                raise ValueError("Publication payload integrity failed")
            return {"payload": rec.payload, "status": rec.status, "attempts": rec.attempts}

    def seal(self, run_id: str, session_id: str, payload: dict) -> dict:
        self.guard()
        with self.factory() as db, db.begin():
            # Run identity is fixed in a fenced operation checkpoint before reaching here.
            rec = db.get(PublicationOutbox, run_id)
            if rec:
                if rec.session_id != session_id or rec.payload_hash != canonical_hash(payload):
                    raise ValueError("An immutable run cannot be republished with different data")
                return dict(rec.payload)
            db.add(
                PublicationOutbox(
                    run_id=run_id,
                    session_id=session_id,
                    payload_hash=canonical_hash(payload),
                    payload=payload,
                    status="PENDING",
                    attempts=0,
                )
            )
        return payload

    def mark(self, run_id: str, status: str) -> None:
        self.guard()
        with self.factory() as db, db.begin():
            rec = db.scalar(
                select(PublicationOutbox)
                .where(PublicationOutbox.run_id == run_id)
                .with_for_update()
            )
            if rec is None:
                raise ValueError("Publication was not sealed")
            if status == "DISPATCHING":
                if rec.attempts >= 3:
                    raise ValueError("Publication attempt limit reached")
                rec.attempts += 1
            rec.status = status
