"""Live vertical slice workflow orchestrator for Signal Slate.

Implements explicit durable steps:
1. start_workflow: Durable parent creation, baseline simulation, telemetry publication
2. investigate: Single shared reasoning agent investigation, citation validation, Plan A
3. interpret_constraint: Constraint parsing from natural text; pauses on ambiguous/unsupported
4. confirm_constraints: Explicit caller constraint confirmation (app cannot mark confirmed itself)
5. generate_candidate_plans: Shows Plan A (vetoed) and Plan B (feasible alternative)
6. approve_plan: Strict authoritative human approval binding (exact version/hash binding;
   rejects approved=False and tampered actions even if stored hash unchanged)
7. apply_and_verify: Simulator application, fresh comparison rehearsal, MCP verification
"""

import time
import uuid
from typing import Any

from signal_slate.agent.live_adk import (
    SignalSlateAdkAgent,
)
from signal_slate.application.checkpoints import save_workflow
from signal_slate.config import get_settings
from signal_slate.db import get_engine
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    ConstraintInterpretation,
    Finding,
    PlanApproval,
    RunConfig,
    ShotContext,
    actions_hash,
    canonical_hash,
    create_evidence_context,
)
from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper, GrafanaMcpClient
from signal_slate.persistence.models import WorkflowSessionRecord
from signal_slate.persistence.turn_reservations import TurnReservationService
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.telemetry.publisher import GrafanaTelemetryPublisher
from signal_slate.telemetry.roundtrip import publish_and_collect
from signal_slate.verification.verifier import DeterministicVerifier
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


class StaleApprovalError(Exception):
    """Raised when plan approval hashes or versions do not match target plan (HTTP 409)."""


class TamperedActionError(StaleApprovalError):
    """Raised when candidate plan actions or parameters have been tampered with."""


class UnapprovedPlanError(StaleApprovalError):
    """Raised when approval has approved=False."""


class NoFeasiblePlanError(Exception):
    """Raised when confirmed constraints eliminate all candidate plans."""


class WorkflowStateError(Exception):
    """Raised when a workflow step is called out of order or in an invalid state."""


class AmbiguousConstraintError(Exception):
    """Raised when natural language constraint is ambiguous and requires human clarification."""


class ContradictoryConstraintError(Exception):
    """Raised when natural language constraint is contradictory."""


class UnsupportedConstraintError(Exception):
    """Raised when natural language input does not contain a supported actionable constraint."""


def validate_authoritative_approval(
    approval: PlanApproval,
    plan: CandidatePlan,
    context: ShotContext,
    confirmed_constraints: list[Constraint],
    expected_base_config_hash: str,
) -> None:
    """Strict authoritative verification of human plan approval.

    1. Enforces approved is True (explicit rejection of approved=False)
    2. Enforces exact plan_id, plan_version, action_hash, constraints_hash, base_config_hash match
    3. Recomputes action hashes from scratch to catch tampering with unchanged stored hash
    4. Validates all action parameters, options, and microphone ownership
    5. Validates that plan actions satisfy all confirmed constraints
    """
    if not approval.approved:
        raise UnapprovedPlanError(
            f"HTTP 409 Conflict: Plan '{approval.plan_id}' approval denied (approved=False)."
        )

    if not approval.verify_match(plan):
        raise StaleApprovalError(
            f"HTTP 409 Conflict: Plan approval hash or version drift. "
            f"Expected plan_id={plan.plan_id} v{plan.plan_version} "
            f"action_hash={plan.action_hash[:8]}, "
            f"got plan_id={approval.plan_id} v{approval.plan_version} "
            f"action_hash={approval.action_hash[:8]}."
        )

    # Base config hash verification
    if (
        plan.base_config_hash != expected_base_config_hash
        or approval.base_config_hash != expected_base_config_hash
    ):
        raise TamperedActionError(
            f"HTTP 409 Conflict: Base config hash mismatch. Plan={plan.base_config_hash[:8]}, "
            f"Expected={expected_base_config_hash[:8]}."
        )

    # Constraints hash verification
    expected_chash = canonical_hash([c.model_dump(mode="json") for c in confirmed_constraints])
    if plan.constraints_hash != expected_chash or approval.constraints_hash != expected_chash:
        raise TamperedActionError(
            f"HTTP 409 Conflict: Constraints hash mismatch. Plan={plan.constraints_hash[:8]}, "
            f"Expected={expected_chash[:8]}."
        )

    for constraint in confirmed_constraints:
        if not constraint.confirmed:
            raise TamperedActionError("Unconfirmed constraint cannot authorize a plan.")
        if constraint.target_mic is not None and constraint.target_mic not in context.mic_ids:
            raise TamperedActionError("Constraint targets an unknown microphone.")
        if constraint.kind == "CHANNEL_EXCLUSION":
            if (
                set(constraint.parameters) != {"excluded_channel"}
                or type(constraint.parameters["excluded_channel"]) is not int
            ):
                raise TamperedActionError("Malformed channel exclusion constraint.")
        elif constraint.kind == "ANTENNA_LOCK":
            if (
                set(constraint.parameters) != {"locked_antenna"}
                or constraint.parameters["locked_antenna"] not in context.available_antennas
            ):
                raise TamperedActionError("Malformed antenna lock constraint.")
        elif constraint.kind == "RIG_LOCK":
            if constraint.parameters or constraint.target_mic not in context.mic_ids:
                raise TamperedActionError(
                    "Rig lock requires a target microphone and no parameters."
                )
            if any(
                a.mic_id == constraint.target_mic
                and a.action_type not in ("NO_ACTION", "BOOM_COVERAGE")
                for a in plan.actions
            ):
                raise TamperedActionError("Action violates confirmed rig lock.")
        elif constraint.kind == "BOOM_EXCLUSION":
            if constraint.parameters:
                raise TamperedActionError("Boom exclusion does not accept parameters.")
        else:
            raise TamperedActionError("Unsupported constraint cannot authorize a plan.")

    # Action tampering check: recompute canonical hash of each action
    if not plan.actions:
        raise TamperedActionError("Plan contains zero actions.")

    for action in plan.actions:
        # Check mic ownership
        if action.mic_id not in context.mic_ids:
            raise TamperedActionError(
                f"Action targets unknown microphone '{action.mic_id}'. "
                f"Known mics: {context.mic_ids}"
            )

        # Validate action parameters against context options
        if action.action_type == "CHANNEL_SWITCH":
            ch = action.parameters.get("channel")
            if type(ch) is not int or set(action.parameters) != {"channel"}:
                raise TamperedActionError(f"Channel switch parameter must be int, got {type(ch)}")
            avail = context.available_channels.get(action.mic_id, [])
            if ch not in avail:
                raise TamperedActionError(
                    f"Channel {ch} is not available for mic '{action.mic_id}'. Available: {avail}"
                )
            # Enforce confirmed channel exclusions
            for c in confirmed_constraints:
                if c.kind == "CHANNEL_EXCLUSION" and c.target_mic in (action.mic_id, None):
                    if ch == int(c.parameters.get("excluded_channel", -1)):
                        raise TamperedActionError(
                            f"Action violates confirmed exclusion of Channel {ch} "
                            f"for {action.mic_id}."
                        )
        elif action.action_type == "ANTENNA_SWITCH":
            ant = action.parameters.get("antenna")
            if set(action.parameters) != {"antenna"} or ant not in context.available_antennas:
                raise TamperedActionError(
                    f"Antenna '{ant}' not available. Available: {context.available_antennas}"
                )
            for c in confirmed_constraints:
                if c.kind == "ANTENNA_LOCK":
                    locked = c.parameters.get("locked_antenna")
                    if locked and ant != locked:
                        raise TamperedActionError(f"Action violates antenna lock to {locked}.")
        elif action.action_type == "BOOM_COVERAGE":
            source = action.parameters.get("source_mic")
            if set(action.parameters) != {
                "source_mic"
            } or source not in context.available_backup_sources.get(action.mic_id, []):
                raise TamperedActionError("Unavailable backup source")
            if any(
                c.kind == "BOOM_EXCLUSION" and c.target_mic in (None, action.mic_id)
                for c in confirmed_constraints
            ):
                raise TamperedActionError("Backup violates boom exclusion")
        elif action.action_type != "NO_ACTION" or action.parameters:
            raise TamperedActionError(f"Unsupported action type: {action.action_type}")

    expected_plan_action_hash = actions_hash(plan.actions)
    if (
        plan.action_hash != expected_plan_action_hash
        or approval.action_hash != expected_plan_action_hash
    ):
        raise TamperedActionError(
            f"Plan action hash {plan.action_hash[:8]} does not match "
            f"recomputed {expected_plan_action_hash[:8]}."
        )


class LiveWorkflowOrchestrator:
    def __init__(
        self,
        db_session_factory: Any | None = None,
        context: ShotContext | None = None,
        genai_client: Any | None = None,
    ) -> None:
        self.context = context or ShotContext()
        self.settings = get_settings()

        if db_session_factory is None:
            engine = get_engine()
            self.db_session_factory = sessionmaker(bind=engine, autoflush=False)
        else:
            self.db_session_factory = db_session_factory

        self.simulator = SimulatorEngine(self.context)
        self.publisher = GrafanaTelemetryPublisher()
        self.mcp_client = GrafanaMcpClient()
        self.agent = SignalSlateAdkAgent(
            db_session_factory=self.db_session_factory,
            settings=self.settings,
            genai_client=genai_client,
        )
        self.verifier = DeterministicVerifier(self.context)

        # Transient workflow memory caches
        self._runs: dict[str, dict[str, Any]] = {}

    def _get_or_create_durable_workflow(
        self, workflow_id: str, session_id: str
    ) -> WorkflowSessionRecord:
        """Ensure WorkflowSessionRecord exists durably before any operations."""
        with self.db_session_factory() as session:
            return TurnReservationService.ensure_workflow_session(
                session=session,
                workflow_id=workflow_id,
                session_id=session_id,
                state="READY",
            )

    def _update_durable_state(
        self,
        workflow_id: str,
        state: str,
        baseline_run_id: str | None = None,
        comparison_run_id: str | None = None,
        config_hash: str | None = None,
        plan_binding_hash: str | None = None,
        plan_version: int | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> None:
        """Update durable workflow session state in PostgreSQL."""
        with self.db_session_factory() as session:
            with session.begin():
                rec = session.scalar(
                    select(WorkflowSessionRecord)
                    .where(WorkflowSessionRecord.workflow_id == workflow_id)
                    .with_for_update()
                )
                if rec:
                    rec.state = state
                    if baseline_run_id:
                        rec.baseline_run_id = baseline_run_id
                    if comparison_run_id:
                        rec.comparison_run_id = comparison_run_id
                    if config_hash:
                        rec.config_hash = config_hash
                    if plan_binding_hash:
                        rec.plan_binding_hash = plan_binding_hash
                    if plan_version is not None:
                        rec.plan_version = plan_version
                    if metadata_update:
                        current_meta = dict(rec.metadata_json or {})
                        current_meta.update(metadata_update)
                        rec.metadata_json = current_meta

    async def start_workflow(
        self,
        workflow_id: str,
        session_id: str | None = None,
        base_config: RunConfig | None = None,
    ) -> dict[str, Any]:
        """Step 1: Durable initialization, baseline simulation, and Grafana MCP collection."""
        sid = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self._get_or_create_durable_workflow(workflow_id, sid)

        t_start = time.time()
        config = base_config or RunConfig(
            channel_assignments={"mic_1": 10, "mic_2": 20, "mic_3": 30, "mic_4": 40}
        )

        data = self._runs.setdefault(workflow_id, {})
        if "baseline_run_id" not in data:
            evidence_context, nonce = create_evidence_context(
                sid, config, fault_family=data.get("fault_family", "channel_interference")
            )
            data.update(
                {
                    "session_id": sid,
                    "evidence_context": evidence_context,
                    "fault_nonce": nonce,
                    "base_config": config,
                    "baseline_run_id": f"run-base-{uuid.uuid4().hex[:16]}",
                    "t_start": t_start,
                    "trace_log": [],
                }
            )
            save_workflow(data)
        config = data["base_config"]
        baseline_run_id = data["baseline_run_id"]
        if "observed_baseline" not in data:
            data["observed_baseline"] = await publish_and_collect(
                config=config,
                run_id=baseline_run_id,
                session_id=sid,
                evidence_context=data["evidence_context"],
                seed=42,
                publisher=self.publisher,
                mcp_client=self.mcp_client,
                context=self.context,
                fault_family=data.get("fault_family", "channel_interference"),
            )
            data["trace_log"].append(f"Published and collected baseline {baseline_run_id}")
            save_workflow(data)

        self._update_durable_state(
            workflow_id=workflow_id,
            state="INVESTIGATING",
            baseline_run_id=baseline_run_id,
            config_hash=config.config_hash,
        )

        return self._runs[workflow_id]

    async def investigate(
        self,
        workflow_id: str,
        simulate_model_failure: bool = False,
        repair_retry: bool = False,
    ) -> Finding:
        """Step 2: Google ADK investigation citing real evidence IDs."""
        wf_data = self._runs.get(workflow_id)
        if not wf_data:
            raise WorkflowStateError(f"Workflow '{workflow_id}' not started.")

        wf_data.pop("approved_plan", None)
        wf_data.pop("approval", None)

        observed_baseline = wf_data["observed_baseline"]
        baseline_check = self.verifier.verify_baseline_run(
            observed_baseline, wf_data["base_config"].config_hash
        )
        healthy = baseline_check.terminal_status == "VERIFIED" and all(
            not sample.is_dropout and not sample.is_clipped and sample.quality >= 70
            for sample in observed_baseline.samples
        )
        if healthy and not simulate_model_failure:
            wrapper = BoundedModelEvidenceWrapper(observed_baseline, self.context)
            ids = [
                row["evidence_id"]
                for row in wrapper.get_run_metrics(
                    observed_baseline.run_id,
                    ["mic_1"],
                    self.context.critical_line_start_ms,
                    self.context.critical_line_end_ms,
                )
            ]
            finding = Finding(
                status="HEALTHY",
                affected_mic="mic_1",
                interval_ms=(
                    self.context.critical_line_start_ms,
                    self.context.critical_line_end_ms,
                ),
                observations=[
                    "Complete cloud evidence meets the rehearsal receiver thresholds; "
                    "no intervention is needed."
                ],
                evidence_ids=ids,
                competing_explanations=[],
                recommended_action=CandidateAction(
                    action_type="NO_ACTION", mic_id="mic_1", parameters={}
                ),
            )
            wf_data["finding_origin"] = "deterministic"
            wf_data["finding_evidence"] = [
                wrapper._envelopes[cid].model_dump(mode="json") for cid in ids
            ]
        else:
            finding = await self.agent.investigate_baseline(
                workflow_id=workflow_id,
                observed_run=observed_baseline,
                context=self.context,
                simulate_model_failure=simulate_model_failure,
                repair_retry=repair_retry,
                retry_context={
                    "current_config": wf_data["base_config"].model_dump(mode="json"),
                    "previous_attempts": [
                        {
                            "actions": entry.get("actions", []),
                            "previous_metrics": entry["baseline"].get("metrics", [])
                            if isinstance(entry["baseline"], dict)
                            else [m.model_dump(mode="json") for m in entry["baseline"].metrics],
                            "verdict": entry["verification"],
                        }
                        for entry in wf_data.get("history", [])[-1:]
                    ],
                }
                if repair_retry
                else None,
            )
            wf_data["finding_origin"] = "gemini"
        wf_data["finding"] = finding
        evidence_data = getattr(self.agent, "_session_data", {}).get(f"sess-{workflow_id}-inv", {})
        wrapper = evidence_data.get("wrapper")
        if wf_data.get("finding_origin") == "gemini":
            wf_data["finding_evidence"] = [
                wrapper._envelopes[cid].model_dump(mode="json")
                for cid in finding.evidence_ids
                if wrapper and cid in wrapper._envelopes
            ]
        save_workflow(wf_data)
        wf_data["trace_log"].append(
            f"Investigation ({wf_data.get('finding_origin')}): status={finding.status}, "
            f"affected={finding.affected_mic}, cited={len(finding.evidence_ids)} citations"
        )

        self._update_durable_state(
            workflow_id=workflow_id,
            state="AWAITING_HUMAN_CONSTRAINT",
            metadata_update={"finding": finding.model_dump(mode="json")},
        )
        return finding

    async def interpret_constraint(
        self,
        workflow_id: str,
        human_text: str,
        simulate_model_failure: bool = False,
    ) -> ConstraintInterpretation:
        """Step 3: Parse natural language sound mixer input into typed constraints.

        Pauses workflow if interpretation is AMBIGUOUS, CONTRADICTORY, or UNSUPPORTED.
        Application code DOES NOT mark confirmed=True.
        """
        wf_data = self._runs.get(workflow_id)
        if not wf_data:
            raise WorkflowStateError(f"Workflow '{workflow_id}' not started.")

        wf_data.pop("approved_plan", None)
        wf_data.pop("approval", None)

        interpretation = await self.agent.interpret_constraint(
            workflow_id=workflow_id,
            human_text=human_text,
            context=self.context,
            simulate_model_failure=simulate_model_failure,
        )

        wf_data["interpretation"] = interpretation
        wf_data["human_text"] = human_text
        save_workflow(wf_data)
        wf_data["trace_log"].append(
            f"ADK Constraint Interpretation: status={interpretation.status}, "
            f"parsed={len(interpretation.constraints)} constraints"
        )

        if interpretation.status == "AMBIGUOUS":
            self._update_durable_state(workflow_id=workflow_id, state="PAUSED_AMBIGUOUS_CONSTRAINT")
            raise AmbiguousConstraintError(
                f"Mixer constraint '{human_text}' is AMBIGUOUS: {interpretation.rationale}. "
                f"Workflow paused awaiting human clarification."
            )
        elif interpretation.status == "CONTRADICTORY":
            self._update_durable_state(
                workflow_id=workflow_id, state="PAUSED_CONTRADICTORY_CONSTRAINT"
            )
            raise ContradictoryConstraintError(
                f"Mixer constraint '{human_text}' is CONTRADICTORY: {interpretation.rationale}."
            )
        elif interpretation.status == "UNSUPPORTED":
            self._update_durable_state(
                workflow_id=workflow_id, state="PAUSED_UNSUPPORTED_CONSTRAINT"
            )
            raise UnsupportedConstraintError(
                f"Mixer input '{human_text}' is UNSUPPORTED: {interpretation.rationale}."
            )

        self._update_durable_state(
            workflow_id=workflow_id,
            state="AWAITING_HUMAN_CONFIRMATION",
            metadata_update={"interpretation": interpretation.model_dump(mode="json")},
        )
        return interpretation

    def generate_candidate_plans(
        self,
        workflow_id: str,
        confirmed_constraints: list[Constraint],
    ) -> list[CandidatePlan]:
        """Step 4: Generate candidate plans respecting confirmed creative constraints.

        Requires explicit caller-confirmed constraints (each confirmed=True).
        Shows Plan A (initial recommendation before veto) and Plan B (feasible alternative).
        """
        wf_data = self._runs.get(workflow_id)
        if not wf_data:
            raise WorkflowStateError(f"Workflow '{workflow_id}' not started.")

        wf_data.pop("approved_plan", None)
        wf_data.pop("approval", None)

        for c in confirmed_constraints:
            if not c.confirmed:
                raise ValueError(
                    f"Constraint '{c.constraint_id}' is not confirmed. "
                    f"Application requires explicit caller confirmation."
                )

        finding = wf_data["finding"]
        base_config = wf_data["base_config"]

        candidate_plans = self.agent.generate_candidate_plans(
            finding=finding,
            confirmed_constraints=confirmed_constraints,
            base_config_hash=base_config.config_hash,
            context=self.context,
            base_config=base_config,
        )

        generation = wf_data.get("plan_generation", 0) + 1
        for candidate in candidate_plans:
            candidate.plan_version = generation
        wf_data["plan_generation"] = generation
        wf_data["confirmed_constraints"] = confirmed_constraints
        wf_data["candidate_plans"] = candidate_plans
        if not candidate_plans:
            self._update_durable_state(workflow_id=workflow_id, state="NO_FEASIBLE_PLAN")
            raise NoFeasiblePlanError(
                "NO_FEASIBLE_PLAN: Confirmed constraints eliminated all available candidates."
            )

        wf_data["confirmed_constraints"] = confirmed_constraints
        wf_data["candidate_plans"] = candidate_plans
        wf_data["trace_log"].append(
            f"Generated {len(candidate_plans)} feasible candidates respecting "
            "confirmed constraints."
        )

        self._update_durable_state(
            workflow_id=workflow_id,
            state="AWAITING_HUMAN_APPROVAL",
            metadata_update={
                "candidate_plans": [p.model_dump(mode="json") for p in candidate_plans],
                "confirmed_constraints": [c.model_dump(mode="json") for c in confirmed_constraints],
            },
        )

        return candidate_plans

    def approve_plan(
        self,
        workflow_id: str,
        approval: PlanApproval,
    ) -> CandidatePlan:
        """Step 5: Authoritative human approval binding."""
        wf_data = self._runs.get(workflow_id)
        if not wf_data:
            raise WorkflowStateError(f"Workflow '{workflow_id}' not started.")

        candidate_plans: list[CandidatePlan] = wf_data.get("candidate_plans", [])
        selected = next((p for p in candidate_plans if p.plan_id == approval.plan_id), None)
        if not selected:
            raise WorkflowStateError(
                f"Plan '{approval.plan_id}' not found in candidate plans "
                f"for workflow '{workflow_id}'."
            )

        # Enforce strict authoritative validation
        validate_authoritative_approval(
            approval=approval,
            plan=selected,
            context=self.context,
            confirmed_constraints=wf_data.get("confirmed_constraints", []),
            expected_base_config_hash=wf_data["base_config"].config_hash,
        )

        wf_data["approved_plan"] = selected.model_copy(deep=True)
        wf_data["approval"] = approval.model_copy(deep=True)
        wf_data["approval_context_hash"] = canonical_hash(
            {
                "finding": wf_data["finding"].model_dump(mode="json"),
                "context": self.context.model_dump(mode="json"),
            }
        )
        wf_data["trace_log"].append(
            f"Plan '{approval.plan_id}' approved with matching plan and configuration hashes."
        )

        self._update_durable_state(
            workflow_id=workflow_id,
            state="PLAN_APPROVED",
            metadata_update={
                "approved_plan_id": approval.plan_id,
                "approval": approval.model_dump(mode="json"),
            },
        )

        return selected

    async def apply_and_verify(
        self,
        workflow_id: str,
        negative_case: str | None = None,
    ) -> dict[str, Any]:
        """Step 6: Apply approved plan to simulator, publish telemetry,
        collect MCP evidence, and verify.
        """
        wf_data = self._runs.get(workflow_id)
        if not wf_data:
            raise WorkflowStateError(f"Workflow '{workflow_id}' not started.")

        approved_plan = wf_data.get("approved_plan")
        if not approved_plan:
            raise WorkflowStateError(f"Workflow '{workflow_id}' does not have an approved plan.")

        approval = wf_data.get("approval")
        if approval is None:
            raise UnapprovedPlanError("Missing explicit approval record.")
        validate_authoritative_approval(
            approval,
            approved_plan,
            self.context,
            wf_data.get("confirmed_constraints", []),
            wf_data["base_config"].config_hash,
        )

        current_context_hash = canonical_hash(
            {
                "finding": wf_data["finding"].model_dump(mode="json"),
                "context": self.context.model_dump(mode="json"),
            }
        )
        if wf_data.get("approval_context_hash") != current_context_hash:
            raise StaleApprovalError("Finding or shot context changed after approval.")

        base_config = wf_data["base_config"]
        sid = wf_data["session_id"]
        observed_baseline = wf_data["observed_baseline"]
        confirmed_constraints = wf_data["confirmed_constraints"]

        # Apply plan actions to create comparison configuration
        comp_channel_assignments = dict(base_config.channel_assignments)
        comp_antenna = base_config.antenna_selection
        comp_backups = dict(base_config.backup_sources)
        for action in approved_plan.actions:
            if action.action_type == "CHANNEL_SWITCH":
                comp_channel_assignments[action.mic_id] = int(action.parameters["channel"])
            elif action.action_type == "ANTENNA_SWITCH":
                comp_antenna = action.parameters["antenna"]
            elif action.action_type == "BOOM_COVERAGE":
                comp_backups[action.mic_id] = action.parameters["source_mic"]

        comp_config = RunConfig(
            scenario_id=base_config.scenario_id,
            channel_assignments=comp_channel_assignments,
            antenna_selection=comp_antenna,
            backup_sources=comp_backups,
        )

        # Comparison simulation
        comparison_run_id = wf_data.setdefault(
            "comparison_run_id", f"run-comp-{uuid.uuid4().hex[:16]}"
        )
        wf_data["comparison_config"] = comp_config
        save_workflow(wf_data)
        if negative_case == "wrong_run":
            comparison_run_id = wf_data["baseline_run_id"]  # Wrong foreign run ID

        if negative_case == "grafana_failure_after_apply":
            raise RuntimeError("Grafana query failure after apply")
        observed_comparison = await publish_and_collect(
            config=comp_config,
            run_id=comparison_run_id,
            session_id=sid,
            evidence_context=wf_data["evidence_context"],
            seed=42,
            publisher=self.publisher,
            mcp_client=self.mcp_client,
            context=self.context,
            simulate_missing_final_sample=negative_case == "missing_final_sample",
            fault_family=wf_data.get("fault_family", "channel_interference"),
        )
        wf_data["observed_comparison"] = observed_comparison
        save_workflow(wf_data)

        verification_result = self.verifier.verify_run(
            baseline_run=observed_baseline,
            comparison_run=observed_comparison,
            approved_plan=approved_plan,
            confirmed_constraints=confirmed_constraints,
            expected_config_hash=comp_config.config_hash,
        )

        wf_data["verification"] = verification_result
        t_elapsed = time.time() - wf_data["t_start"]
        wf_data["trace_log"].append(
            f"Verification complete: status={verification_result.terminal_status}"
        )

        self._update_durable_state(
            workflow_id=workflow_id,
            state="COMPLETED" if verification_result.terminal_status == "VERIFIED" else "FAILED",
            comparison_run_id=comparison_run_id,
            metadata_update={"verification": verification_result.model_dump(mode="json")},
        )

        return {
            "status": "PASS" if verification_result.terminal_status == "VERIFIED" else "FAIL",
            "workflow_id": workflow_id,
            "session_id": sid,
            "baseline_run_id": wf_data["baseline_run_id"],
            "comparison_run_id": comparison_run_id,
            "finding": wf_data["finding"].model_dump(mode="json"),
            "interpreted_constraints": [c.model_dump(mode="json") for c in confirmed_constraints],
            "approved_plan": approved_plan.model_dump(mode="json"),
            "approval": wf_data["approval"].model_dump(mode="json"),
            "verification": verification_result.model_dump(mode="json"),
            "trace_log": wf_data["trace_log"],
            "elapsed_seconds": round(t_elapsed, 2),
        }

    async def execute_live_slice(
        self,
        workflow_id: str | None = None,
        sound_mixer_constraint_text: str = (
            "Channel 11 belongs to the next setup; leave the costume rig alone."
        ),
        negative_case: str | None = None,
        simulated_human: bool = True,
    ) -> dict[str, Any]:
        """High-level test driver method executing the complete central loop.

        Only test drivers may set simulated_human=True to simulate mixer commands.
        """
        wf_id = workflow_id or f"wf-{uuid.uuid4().hex[:8]}"

        # Step 1: Start workflow
        await self.start_workflow(workflow_id=wf_id)

        # Step 2: Investigation
        simulate_model_fail = negative_case == "model_unavailable"
        await self.investigate(workflow_id=wf_id, simulate_model_failure=simulate_model_fail)

        # Step 3: Interpret constraint
        interpretation = await self.interpret_constraint(
            workflow_id=wf_id,
            human_text=sound_mixer_constraint_text,
            simulate_model_failure=simulate_model_fail,
        )

        # Step 4: Confirm constraints
        # Explicit test driver simulation notification
        if simulated_human:
            self._runs[wf_id]["trace_log"].append(
                "[TEST DRIVER SIMULATION] Simulating human mixer confirmation of parsed constraints"
            )

        confirmed_constraints = [
            Constraint(
                constraint_id=c.constraint_id,
                kind=c.kind,
                target_mic=c.target_mic,
                parameters=c.parameters,
                exact_source_span=c.exact_source_span,
                source_text=sound_mixer_constraint_text,
                confirmed=True,
            )
            for c in interpretation.constraints
        ]

        if negative_case == "impossible_constraint":
            # Force impossible constraint excluding channel 12 as well
            confirmed_constraints.append(
                Constraint(
                    constraint_id="c-imp",
                    kind="CHANNEL_EXCLUSION",
                    target_mic="mic_1",
                    parameters={"excluded_channel": 12},
                    exact_source_span="Exclude channel 12",
                    source_text="Exclude channel 12",
                    confirmed=True,
                )
            )

        candidate_plans = self.generate_candidate_plans(
            workflow_id=wf_id,
            confirmed_constraints=confirmed_constraints,
        )

        # Select Plan B (the constraint-compliant feasible alternative)
        selected_plan = next(
            (p for p in candidate_plans if p.plan_id == "plan_b"), candidate_plans[0]
        )

        # Step 5: Human approval
        if simulated_human:
            self._runs[wf_id]["trace_log"].append(
                f"[TEST DRIVER SIMULATION] Simulating human mixer approval for "
                f"{selected_plan.plan_id}"
            )

        approval_action_hash = selected_plan.action_hash
        approved_flag = True

        if negative_case == "stale_approval":
            approval_action_hash = "corrupted_stale_hash_00000000"
        elif negative_case == "unapproved_plan":
            approved_flag = False

        approval = PlanApproval(
            plan_id=selected_plan.plan_id,
            plan_version=selected_plan.plan_version,
            action_hash=approval_action_hash,
            constraints_hash=selected_plan.constraints_hash,
            base_config_hash=selected_plan.base_config_hash,
            approved=approved_flag,
            approved_by="lead_sound_mixer",
        )

        self.approve_plan(workflow_id=wf_id, approval=approval)

        # Step 6: Apply & verify
        return await self.apply_and_verify(workflow_id=wf_id, negative_case=negative_case)
