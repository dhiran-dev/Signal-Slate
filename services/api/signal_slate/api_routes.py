"""Capability-bound local workflow API. GET never dispatches external work."""

import asyncio
import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from signal_slate.application.checkpoints import publication_store, workflow_checkpoint
from signal_slate.config import get_settings
from signal_slate.db import get_engine
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    ConstraintInterpretation,
    EvidenceContext,
    Finding,
    ObservedRun,
    PlanApproval,
    RunConfig,
    ShotContext,
    VerificationResult,
    canonical_hash,
)
from signal_slate.persistence.models import BrowserSessionRecord, OperationRecord, TurnReservation
from signal_slate.persistence.outbox import OutboxStore
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.workflow.orchestrator import (
    AmbiguousConstraintError,
    ContradictoryConstraintError,
    LiveWorkflowOrchestrator,
    UnsupportedConstraintError,
)

router = APIRouter(prefix="/api")


@router.get("/readiness")
def get_readiness() -> dict:
    from signal_slate.application.presentation import readiness

    return readiness()


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview", "live"] = "preview"
    preset: Literal["a", "b", "c", "control"] = "a"


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=2000)
    constraints: list[Constraint] | None = Field(default=None, max_length=10)
    approval: PlanApproval | None = None


@lru_cache
def factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(request: Request) -> None:
    """Exact browser origins; deployment replaces the local allowlist.

    Never infer allowed origins from forwarded host headers.
    """
    origin = request.headers.get("origin")
    configured = os.getenv(
        "SIGNAL_SLATE_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    allowed = {value.strip() for value in configured.split(",") if value.strip()}
    allowed.discard("*")
    if "SIGNAL_SLATE_ALLOWED_ORIGINS" not in os.environ:
        allowed.add(str(request.base_url).rstrip("/"))
    if origin and origin not in allowed:
        raise HTTPException(403, "Origin rejected")


def authorize(rec, request: Request, write: bool = False) -> None:
    cap = request.cookies.get("ss_cap", "")
    if rec is None or not cap or not secrets.compare_digest(rec.capability_hash, digest(cap)):
        raise HTTPException(404, "Session not found")
    if datetime.now(UTC) - rec.created_at > timedelta(days=1):
        raise HTTPException(410, "Session expired; create a new rehearsal")
    if write:
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), rec.csrf_token):
            raise HTTPException(403, "CSRF token required")


def public(rec) -> dict[str, Any]:
    state = dict(rec.snapshot.get("public", {}))
    state.update(
        id=rec.id, revision=rec.revision, csrf_token=rec.csrf_token, busy=bool(rec.operation_token)
    )
    if rec.operation_token:
        # Read-only status exposure, never lease acquisition or external work.
        with factory()() as db:
            op = db.get(OperationRecord, rec.operation_token)
            if op:
                state["operation"] = operation_view(op)
    return state


def operation_view(op) -> dict:
    expired = op.lease_expires_at is None or op.lease_expires_at <= datetime.now(UTC)
    return {
        "id": op.id,
        "kind": op.kind,
        "status": op.status,
        "lease_expires_at": op.lease_expires_at.isoformat() if op.lease_expires_at else None,
        "resumable": op.status in ("PENDING", "RETRYABLE") or (op.status == "RUNNING" and expired),
    }


@router.post("/sessions", status_code=201)
def create_session(body: CreateSession, request: Request, response: Response):
    check_origin(request)
    if body.mode == "live" and os.getenv("SIGNAL_SLATE_RUNTIME_ENABLED", "true") != "true":
        raise HTTPException(503, "Live runtime is disabled")
    cap = request.cookies.get("ss_cap") or secrets.token_urlsafe(32)
    with factory()() as db, db.begin():
        # Serialize the account-wide creation budget without external calls in the transaction.
        db.execute(text("SELECT pg_advisory_xact_lock(73719201)"))
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = db.scalar(
            select(func.count())
            .select_from(BrowserSessionRecord)
            .where(
                BrowserSessionRecord.created_at >= midnight,
                BrowserSessionRecord.snapshot["public"]["mode"].astext == "live",
            )
        )
        if body.mode == "live" and (count or 0) >= min(
            20, max(0, get_settings().max_sessions_per_day)
        ):
            raise HTTPException(429, "Daily live session limit reached")
        rec = BrowserSessionRecord(
            id=secrets.token_hex(16),
            capability_hash=digest(cap),
            csrf_token=secrets.token_urlsafe(32),
            revision=0,
            snapshot={
                "public": {
                    "mode": body.mode,
                    "preset": body.preset,
                    "state": "READY",
                    "shot_context": ShotContext().model_dump(),
                    "baseline": None,
                    "comparison": None,
                    "finding": None,
                    "interpretation": None,
                    "candidate_plans": [],
                    "confirmed_constraints": [],
                    "approval": None,
                    "verification": None,
                    "error": None,
                    "disclosure": "Local simulation only; no Gemini or Grafana evidence."
                    if body.mode == "preview"
                    else "Simulated receivers; Gemini reasoning and Grafana cloud evidence.",
                },
                "workflow": {
                    "fault_family": {
                        "a": "channel_interference",
                        "b": "antenna_shadow",
                        "c": "audio_clipping",
                        "control": "healthy",
                    }[body.preset]
                },
            },
        )
        db.add(rec)
        db.flush()
        result = public(rec)
    response.set_cookie(
        "ss_cap",
        cap,
        httponly=True,
        samesite="strict",
        secure=os.getenv("SIGNAL_SLATE_SECURE_COOKIES", "false") == "true"
        or request.url.scheme == "https",
        max_age=86400,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, response: Response):
    with factory()() as db:
        rec = db.get(BrowserSessionRecord, session_id)
        authorize(rec, request)
        response.headers["Cache-Control"] = "no-store"
        return public(rec)


def hydrate(data: dict) -> dict:
    types: dict[str, type[BaseModel]] = {
        "base_config": RunConfig,
        "comparison_config": RunConfig,
        "evidence_context": EvidenceContext,
        "observed_baseline": ObservedRun,
        "observed_comparison": ObservedRun,
        "finding": Finding,
        "interpretation": ConstraintInterpretation,
        "approved_plan": CandidatePlan,
        "approval": PlanApproval,
        "verification": VerificationResult,
    }
    result = dict(data)
    for key, model in types.items():
        if key in result:
            result[key] = model.model_validate(result[key])
    for key, model in (("candidate_plans", CandidatePlan), ("confirmed_constraints", Constraint)):
        if key in result:
            result[key] = [model.model_validate(value) for value in result[key]]
    return result


ALLOWED = {
    "baseline": {"READY"},
    "investigate": {"BASELINE_READY"},
    "constraints": {
        "AWAITING_HUMAN_CONSTRAINT",
        "AWAITING_HUMAN_CONFIRMATION",
        "NO_FEASIBLE_PLAN",
        "AWAITING_HUMAN_APPROVAL",
    },
    "retry": {"COMPLETED"},
    "confirm": {"AWAITING_HUMAN_CONFIRMATION"},
    "approve": {"AWAITING_HUMAN_APPROVAL"},
    "apply": {"PLAN_APPROVED"},
}
NEXT = {
    "retry": "AWAITING_HUMAN_CONSTRAINT",
    "baseline": "BASELINE_READY",
    "investigate": "AWAITING_HUMAN_CONSTRAINT",
    "constraints": "AWAITING_HUMAN_CONFIRMATION",
    "confirm": "AWAITING_HUMAN_APPROVAL",
    "approve": "PLAN_APPROVED",
    "apply": "COMPLETED",
}


def confirm_exact(body: Command, state: dict) -> list[Constraint]:
    if state["interpretation"]["status"] != "SUPPORTED":
        raise ValueError("The constraint needs clarification")
    expected = state["interpretation"]["constraints"]
    supplied = body.constraints
    if supplied is None or not all(c.confirmed for c in supplied):
        raise ValueError("Explicit constraint confirmation required")
    actual = [c.model_dump(mode="json") | {"confirmed": False} for c in supplied]
    if actual != expected:
        raise ValueError("Confirmation differs from displayed interpretation")
    return supplied


async def execute_live(operation: str, sid: str, body: Command, snapshot: dict):
    workflow = LiveWorkflowOrchestrator(db_session_factory=factory())
    workflow._runs[sid] = hydrate(snapshot["workflow"])
    state = snapshot["public"]
    if operation == "baseline":
        await workflow.start_workflow(sid, sid)
    elif operation == "investigate":
        if "finding" not in workflow._runs[sid]:
            await workflow.investigate(sid)
    elif operation == "retry":
        data = workflow._runs[sid]
        if (
            data.get("verification") is None
            or data["verification"].terminal_status != "NOT_VERIFIED"
        ):
            raise ValueError("Only a complete failed comparison can be investigated again")
        if not data.get("retry_prepared"):
            history = data.setdefault("history", [])
            history.append(
                {
                    "baseline": data["observed_baseline"],
                    "comparison": data["observed_comparison"],
                    "config": data["comparison_config"],
                    "verification": data["verification"],
                    "approval": data["approval"],
                    "actions": data["approved_plan"].actions,
                }
            )
            data["history"] = jsonable_encoder(history)
            data.setdefault("original_baseline", data["observed_baseline"])
            data["observed_baseline"] = data["observed_comparison"]
            data["base_config"] = data["comparison_config"]
            data["baseline_run_id"] = data["observed_baseline"].run_id
            for key in (
                "comparison_run_id",
                "observed_comparison",
                "comparison_config",
                "finding",
                "approval",
                "approved_plan",
                "candidate_plans",
                "interpretation",
                "confirmed_constraints",
            ):
                data.pop(key, None)
            data["retry_prepared"] = True
            from signal_slate.application.checkpoints import save_workflow

            save_workflow(data)
        if "finding" not in data:
            await workflow.investigate(sid, repair_retry=True)
        data.pop("retry_prepared", None)
        data.pop("verification", None)
    elif operation == "constraints":
        if not body.text or not body.text.strip():
            raise ValueError("Enter a constraint")
        try:
            if (
                workflow._runs[sid].get("human_text") != body.text
                or "interpretation" not in workflow._runs[sid]
            ):
                await workflow.interpret_constraint(sid, body.text)
        except (AmbiguousConstraintError, ContradictoryConstraintError, UnsupportedConstraintError):
            # The parsed result remains reviewable and another explicit text command
            # can refine it. Confirmation still requires SUPPORTED and exact match.
            pass
    elif operation == "confirm":
        from signal_slate.workflow.orchestrator import NoFeasiblePlanError

        try:
            workflow.generate_candidate_plans(sid, confirm_exact(body, state))
        except NoFeasiblePlanError:
            state["state"] = "NO_FEASIBLE_PLAN"
    elif operation == "approve":
        if body.approval is None:
            raise ValueError("Approval required")
        workflow.approve_plan(sid, body.approval)
    elif operation == "apply":
        await workflow.apply_and_verify(sid)
    snapshot["workflow"] = jsonable_encoder(workflow._runs[sid])
    data = snapshot["workflow"]
    for key, source in {
        "baseline": "observed_baseline",
        "comparison": "observed_comparison",
        "finding": "finding",
        "finding_evidence": "finding_evidence",
        "finding_origin": "finding_origin",
        "interpretation": "interpretation",
        "candidate_plans": "candidate_plans",
        "approval": "approval",
        "confirmed_constraints": "confirmed_constraints",
        "verification": "verification",
        "baseline_config": "base_config",
        "comparison_config": "comparison_config",
    }.items():
        state[key] = data.get(
            source, [] if key in ("candidate_plans", "confirmed_constraints") else None
        )
    state["history"] = data.get("history", [])
    state["original_baseline"] = data.get("original_baseline")


def execute_preview(operation: str, sid: str, body: Command, snapshot: dict):
    state = snapshot["public"]
    context = ShotContext()
    config = RunConfig.model_validate(snapshot["workflow"].get("base_config", {}))
    family = snapshot["workflow"].get("fault_family", "channel_interference")
    if operation == "baseline":
        samples, metrics, _ = SimulatorEngine(context, fault_family=family).run_rehearsal(
            config, seed=42
        )
        state["baseline_config"] = config.model_dump(mode="json")
        state["baseline"] = {
            "run_id": f"preview-{sid}-baseline",
            "samples": jsonable_encoder(samples),
            "metrics": jsonable_encoder(metrics),
            "source": "local_preview",
        }
    elif operation == "investigate":
        state["finding_origin"] = "preview"
        action = {
            "channel_interference": CandidateAction(
                action_type="CHANNEL_SWITCH", mic_id="mic_1", parameters={"channel": 11}
            ),
            "antenna_shadow": CandidateAction(
                action_type="ANTENNA_SWITCH", mic_id="mic_1", parameters={"antenna": "B"}
            ),
            "audio_clipping": CandidateAction(
                action_type="BOOM_COVERAGE", mic_id="mic_1", parameters={"source_mic": "mic_4"}
            ),
            "healthy": CandidateAction(action_type="NO_ACTION", mic_id="mic_1", parameters={}),
        }[family]
        state["finding"] = Finding(
            status="HEALTHY" if family == "healthy" else "RISK_IDENTIFIED",
            affected_mic="mic_1",
            interval_ms=(4900, 6800),
            observations=[
                "Scripted preview: inspect receiver observations. "
                "This finding is not Gemini analysis."
            ],
            evidence_ids=[],
            competing_explanations=["This is a scripted local preview, not Gemini analysis."],
            recommended_action=action,
        ).model_dump(mode="json")
    elif operation == "constraints":
        raw = body.text or ""
        constraints = []
        pieces = [part.strip().rstrip(".") for part in raw.split(";") if part.strip()]
        supported = bool(pieces)
        for index, piece in enumerate(pieces):
            match = re.fullmatch(r"(?:exclude|avoid) channel (11|12)", piece, re.IGNORECASE)
            kind = ""
            parameters: dict[str, Any] = {}
            if match:
                kind, parameters = "CHANNEL_EXCLUSION", {"excluded_channel": int(match[1])}
            elif piece.lower() in ("no boom backup", "exclude boom backup"):
                kind = "BOOM_EXCLUSION"
            elif piece.lower() in ("leave elena's rig alone", "lock elena's rig"):
                kind = "RIG_LOCK"
            elif piece.lower() in ("keep antenna a", "keep antenna b"):
                kind, parameters = "ANTENNA_LOCK", {"locked_antenna": piece[-1].upper()}
            else:
                supported = False
                break
            constraints.append(
                Constraint.model_validate(
                    dict(
                        constraint_id=f"preview-{index}",
                        kind=kind,
                        target_mic="mic_1",
                        parameters=parameters,
                        exact_source_span=piece,
                        source_text=raw,
                    )
                ).model_dump(mode="json")
            )
        state["interpretation"] = {
            "status": "SUPPORTED" if supported else "UNSUPPORTED",
            "constraints": constraints if supported else [],
            "rationale": "Scripted preview accepts: Exclude channel 11/12; No boom backup; "
            "Leave Elena's rig alone; Keep antenna A/B. Separate clauses with semicolons. "
            "Live mode uses Gemini.",
        }
    elif operation == "confirm":
        confirmed = confirm_exact(body, state)
        state["confirmed_constraints"] = jsonable_encoder(confirmed)
        from signal_slate.planning.candidates import generate_candidate_plans

        state["candidate_plans"] = [
            p.model_dump(mode="json")
            for p in generate_candidate_plans(
                Finding.model_validate(state["finding"]),
                confirmed,
                config.config_hash,
                context,
                config,
            )
        ]
    elif operation == "approve":
        from signal_slate.workflow.orchestrator import validate_authoritative_approval

        plan = next(
            (
                p
                for p in state["candidate_plans"]
                if body.approval and p["plan_id"] == body.approval.plan_id
            ),
            None,
        )
        if not plan or not body.approval:
            raise ValueError("Select a displayed plan")
        validate_authoritative_approval(
            body.approval,
            CandidatePlan.model_validate(plan),
            context,
            [Constraint.model_validate(c) for c in state["confirmed_constraints"]],
            config.config_hash,
        )
        state["approval"] = body.approval.model_dump(mode="json")
    elif operation == "apply":
        plan = next(
            p for p in state["candidate_plans"] if p["plan_id"] == state["approval"]["plan_id"]
        )
        for action in plan["actions"]:
            if action["action_type"] == "CHANNEL_SWITCH":
                config.channel_assignments[action["mic_id"]] = action["parameters"]["channel"]
            elif action["action_type"] == "ANTENNA_SWITCH":
                config.antenna_selection = action["parameters"]["antenna"]
            elif action["action_type"] == "BOOM_COVERAGE":
                config.backup_sources[action["mic_id"]] = action["parameters"]["source_mic"]
        state["comparison_config"] = config.model_dump(mode="json")
        samples, metrics, _ = SimulatorEngine(context, fault_family=family).run_rehearsal(
            config, seed=42
        )
        state["comparison"] = {
            "run_id": f"preview-{sid}-comparison",
            "samples": jsonable_encoder(samples),
            "metrics": jsonable_encoder(metrics),
            "source": "local_preview",
        }
        state["verification"] = {
            "terminal_status": "INCONCLUSIVE",
            "failure_reasons": [
                "Local preview only: no Grafana evidence; cloud verification was not run."
            ],
            "completeness_passed": False,
            "crosscheck_passed": False,
            "thresholds_passed": False,
            "dialogue_coverage_passed": False,
            "constraints_passed": True,
            "details": {"preview": True},
        }


def locked_session(db, sid):
    return db.scalar(
        select(BrowserSessionRecord).where(BrowserSessionRecord.id == sid).with_for_update()
    )


def assert_lease(db, operation_id, owner, fence):
    op = db.scalar(
        select(OperationRecord).where(OperationRecord.id == operation_id).with_for_update()
    )
    if (
        op is None
        or op.lease_owner != owner
        or op.fence != fence
        or op.status != "RUNNING"
        or op.lease_expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(409, "Operation lease changed; stale worker cannot commit")
    return op


async def run_operation(operation_id: str, request: Request, expected_revision: int):
    owner = secrets.token_hex(16)
    with factory()() as db, db.begin():
        initial = db.get(OperationRecord, operation_id)
        if initial is None:
            raise HTTPException(404, "Operation not found")
        rec = locked_session(db, initial.session_id)
        authorize(rec, request, write=True)
        op = db.scalar(
            select(OperationRecord).where(OperationRecord.id == operation_id).with_for_update()
        )
        if op.status in ("COMPLETED", "FAILED"):
            return completed_result(op)
        if expected_revision != rec.revision or rec.operation_token != op.id:
            raise HTTPException(409, "Operation revision changed")
        if op.status == "RUNNING" and op.lease_expires_at > datetime.now(UTC):
            raise HTTPException(409, "Operation lease is still held; refresh status")
        if op.fence >= 5:
            raise HTTPException(409, "Operation resume limit reached; start a new rehearsal")
        if op.fence:
            for turn in db.scalars(
                select(TurnReservation).where(
                    TurnReservation.workflow_id == rec.id, TurnReservation.status == "RESERVED"
                )
            ):
                turn.status = "UNCERTAIN"
        op.fence += 1
        fence = op.fence
        op.lease_owner = owner
        op.lease_expires_at = datetime.now(UTC) + timedelta(seconds=180)
        op.status = "RUNNING"
        snapshot = jsonable_encoder(op.checkpoint)
        sid, kind, body = rec.id, op.kind, Command.model_validate(op.command)

    def guard():
        with factory()() as db, db.begin():
            assert_lease(db, operation_id, owner, fence)

    def checkpoint(data):
        snapshot["workflow"] = jsonable_encoder(data)
        with factory()() as db, db.begin():
            current = assert_lease(db, operation_id, owner, fence)
            current.checkpoint = jsonable_encoder(snapshot)

    hook = workflow_checkpoint.set(checkpoint)
    outbox = publication_store.set(OutboxStore(factory(), guard))
    error = None
    retryable = False
    conflict = False
    try:
        if snapshot["public"]["mode"] == "preview":
            execute_preview(kind, sid, body, snapshot)
        else:
            await asyncio.wait_for(execute_live(kind, sid, body, snapshot), timeout=150)
        state = snapshot["public"]
        state["state"] = NEXT[kind]
        if kind in ("investigate", "retry") and state.get("finding", {}).get("status") == "HEALTHY":
            state["state"] = "NO_RISK"
        if kind == "confirm" and not state.get("candidate_plans"):
            state["state"] = "NO_FEASIBLE_PLAN"
        if kind == "apply" and state["mode"] == "preview":
            state["state"] = "PREVIEW_COMPLETE"
        state["error"] = None
        if (
            kind == "apply"
            and state["mode"] == "live"
            and state.get("verification", {}).get("terminal_status") == "INCONCLUSIVE"
        ):
            raise RuntimeError("Independent evidence remains incomplete; resume its collection")
    except HTTPException:
        raise
    except Exception as exc:
        from signal_slate.persistence.turn_reservations import TurnBudgetExceededError
        from signal_slate.workflow.orchestrator import StaleApprovalError, WorkflowStateError

        error = type(exc).__name__
        conflict = isinstance(exc, (StaleApprovalError, WorkflowStateError))
        retryable = not isinstance(
            exc, (ValueError, StaleApprovalError, WorkflowStateError, TurnBudgetExceededError)
        )
        snapshot["public"]["error"] = {
            "code": error,
            "message": "This step stopped safely. Resume explicitly after checking prerequisites."
            if retryable
            else "This command was rejected. Review its input or start a new rehearsal.",
        }
    finally:
        workflow_checkpoint.reset(hook)
        publication_store.reset(outbox)
    with factory()() as db, db.begin():
        rec = locked_session(db, sid)
        op = assert_lease(db, operation_id, owner, fence)
        op.checkpoint = jsonable_encoder(snapshot)
        op.status = "RETRYABLE" if retryable else ("FAILED" if error else "COMPLETED")
        op.lease_owner = None
        op.lease_expires_at = None
        rec.snapshot = jsonable_encoder(snapshot)
        rec.revision += 1
        if not retryable:
            rec.operation_token = None
        result = dict(
            snapshot["public"],
            id=sid,
            revision=rec.revision,
            csrf_token=rec.csrf_token,
            busy=retryable,
        )
        if retryable:
            result["operation"] = operation_view(op)
        op.result = result
    if conflict:
        raise HTTPException(409, "Approval or workflow state changed; refresh before deciding")
    return result


def completed_result(op: OperationRecord):
    error = (op.result or {}).get("error") or {}
    if error.get("code") in ("StaleApprovalError", "WorkflowStateError"):
        raise HTTPException(409, "Approval or workflow state changed; refresh before deciding")
    return op.result


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str, request: Request, response: Response):
    with factory()() as db:
        op = db.get(OperationRecord, operation_id)
        if op is None:
            raise HTTPException(404, "Operation not found")
        authorize(db.get(BrowserSessionRecord, op.session_id), request)
        response.headers["Cache-Control"] = "no-store"
        return operation_view(op)


@router.post("/operations/{operation_id}/resume")
async def resume_operation(operation_id: str, body: Command, request: Request):
    return await run_operation(operation_id, request, body.revision)


@router.post("/sessions/{session_id}/{operation}")
async def command(
    session_id: str, operation: str, body: Command, request: Request, response: Response
):
    if operation not in ALLOWED:
        raise HTTPException(404, "Unknown operation")
    key = request.headers.get("idempotency-key") or secrets.token_hex(16)
    if not 1 <= len(key) <= 128:
        raise HTTPException(400, "Idempotency key length must be 1–128")
    command_hash = canonical_hash({"operation": operation, "body": body.model_dump(mode="json")})
    with factory()() as db, db.begin():
        rec = locked_session(db, session_id)
        authorize(rec, request, write=True)
        previous = db.scalar(
            select(OperationRecord).where(
                OperationRecord.session_id == session_id, OperationRecord.idempotency_key == key
            )
        )
        if previous:
            if previous.command_hash != command_hash:
                raise HTTPException(409, "Idempotency key was reused for different input")
            if previous.status in ("COMPLETED", "FAILED"):
                return completed_result(previous)
            response.status_code = 202
            return {"operation": operation_view(previous), "session": public(rec)}
        if rec.operation_token or body.revision != rec.revision:
            raise HTTPException(409, "Session is busy or revision is stale; refresh the session")
        if rec.snapshot["public"]["state"] not in ALLOWED[operation]:
            raise HTTPException(409, "Operation is not available in the current state")
        op = OperationRecord(
            id=secrets.token_hex(16),
            session_id=session_id,
            idempotency_key=key,
            command_hash=command_hash,
            kind=operation,
            command=body.model_dump(mode="json"),
            checkpoint=jsonable_encoder(rec.snapshot),
            status="PENDING",
            fence=0,
        )
        db.add(op)
        rec.operation_token = op.id
        operation_id = op.id
        pending = {"operation": operation_view(op), "session": dict(public(rec), busy=True)}
    if request.headers.get("prefer") == "respond-async":
        response.status_code = 202
        return pending
    return await run_operation(operation_id, request, body.revision)


@router.get("/sessions/{session_id}/evidence/{run_id}")
def get_evidence(session_id: str, run_id: str, request: Request):
    with factory()() as db:
        rec = db.get(BrowserSessionRecord, session_id)
        authorize(rec, request)
        state = rec.snapshot["public"]
        runs = [state.get(key) for key in ("baseline", "comparison", "original_baseline")]
        for attempt in state.get("history", []):
            runs.extend([attempt.get("baseline"), attempt.get("comparison")])
        for run in runs:
            if run and run.get("run_id") == run_id:
                return run
    raise HTTPException(404, "Run is not part of this owned rehearsal")


@router.get("/sessions/{session_id}/report")
def get_report(session_id: str, request: Request):
    with factory()() as db:
        rec = db.get(BrowserSessionRecord, session_id)
        authorize(rec, request)
        state = rec.snapshot["public"]
        keys = (
            "mode",
            "state",
            "shot_context",
            "baseline",
            "comparison",
            "baseline_config",
            "comparison_config",
            "finding",
            "finding_origin",
            "finding_evidence",
            "confirmed_constraints",
            "candidate_plans",
            "approval",
            "verification",
            "original_baseline",
            "history",
            "disclosure",
        )
        return {"schema_version": 1, **{key: state.get(key) for key in keys}}


@router.get("/sessions/{session_id}/evidence-links")
def get_evidence_links(session_id: str, request: Request) -> dict:
    from signal_slate.application.presentation import evidence_links

    with factory()() as db:
        rec = db.get(BrowserSessionRecord, session_id)
        authorize(rec, request)
        return evidence_links(rec.snapshot["public"], session_id)
