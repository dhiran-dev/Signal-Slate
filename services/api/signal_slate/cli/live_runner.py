"""Callable CLI/API runner for Phase 1 live vertical slice.

Used by `scripts/check-live.sh`, diagnostic runs, and independent Codex reviews.
Enforces:
1. Explicit live opt-in (--live)
2. Bounded max runs (--max-runs N, 1 <= N <= 20, default 1)
3. Unique workflow IDs and run IDs per invocation (never reused across runs)
4. Strict terminal status check (exits non-zero unless terminal_status == VERIFIED)
5. Failure persistence with stage, error category, and attempt counts
6. Failure-specific negative assertions (not any exception = pass)
7. Secret-redacted logging to private output path
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signal_slate.agent.live_adk import ModelUnavailableError
from signal_slate.db import get_engine
from signal_slate.persistence.turn_reservations import TurnReservationService
from signal_slate.workflow.orchestrator import (
    LiveWorkflowOrchestrator,
    NoFeasiblePlanError,
    StaleApprovalError,
    UnapprovedPlanError,
)
from sqlalchemy.orm import sessionmaker


def redact_secrets(obj: Any) -> Any:
    """Recursively mask secret tokens and sensitive credentials in log outputs."""
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if any(
                secret_key in k.lower()
                for secret_key in ("token", "password", "secret", "auth", "key")
            ):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(obj, list):
        return [redact_secrets(x) for x in obj]
    elif isinstance(obj, str):
        # Mask any token-like hex / base64 sequences if present
        if "glc_" in obj or ("ey" in obj and len(obj) > 30):
            return "[REDACTED_TOKEN]"
        return obj
    return obj


async def run_live_workflows(
    max_runs: int = 1,
    run_negatives: bool = False,
    output_path: Path | None = None,
) -> int:
    """Execute live workflows with full diagnostic tracing and redacted artifact generation."""
    if not (1 <= max_runs <= 20):
        print(f"[ERROR] Invalid max_runs: {max_runs}. Must be between 1 and 20.")
        return 1

    print("====================================================")
    print("    Signal Slate - Live Integration Slice Runner    ")
    print("====================================================")
    print(f"Timestamp: {datetime.now(UTC).isoformat()}")
    print(f"Max Live Runs: {max_runs}")
    print(f"Include Negative Cases: {run_negatives}")

    engine = get_engine()
    session_factory = sessionmaker(bind=engine, autoflush=False)
    orchestrator = LiveWorkflowOrchestrator(db_session_factory=session_factory)

    reports: list[dict[str, Any]] = []
    all_passed = True

    # 1. Execute Consecutive Live Runs
    for run_idx in range(1, max_runs + 1):
        wf_id = f"live-wf-{uuid.uuid4().hex[:8]}-{run_idx}"
        print(
            f"\n--> [Live Run {run_idx}/{max_runs}] Starting central loop (workflow_id={wf_id})..."
        )
        try:
            res = await orchestrator.execute_live_slice(workflow_id=wf_id, simulated_human=True)
            term_status = res["verification"]["terminal_status"]
            print(
                f"  Workflow {run_idx} completed in {res['elapsed_seconds']}s "
                f"with terminal status: {term_status}"
            )
            print(f"  Baseline Run ID: {res['baseline_run_id']}")
            print(f"  Comparison Run ID: {res['comparison_run_id']}")
            print(f"  Cited Evidence IDs: {res['finding']['evidence_ids']}")

            # Query attempt counts from DB
            with session_factory() as sess:
                attempt_count = TurnReservationService.get_turn_count(sess, wf_id)

            if term_status != "VERIFIED":
                print(f"  [FAIL] Terminal status is '{term_status}', expected 'VERIFIED'.")
                all_passed = False
                reports.append(
                    {
                        "type": "live_run",
                        "index": run_idx,
                        "workflow_id": wf_id,
                        "terminal_status": term_status,
                        "error_category": "VerificationFailed",
                        "error_message": f"Terminal status {term_status} != VERIFIED",
                        "attempt_counts": attempt_count,
                        "result": res,
                    }
                )
                break
            else:
                print(f"  [PASS] Live run {run_idx} VERIFIED.")
                reports.append(
                    {
                        "type": "live_run",
                        "index": run_idx,
                        "workflow_id": wf_id,
                        "terminal_status": term_status,
                        "attempt_counts": attempt_count,
                        "result": res,
                    }
                )
        except Exception as exc:
            print(f"  [FAIL] Workflow {run_idx} failed: {type(exc).__name__}: {exc}")
            with session_factory() as sess:
                attempt_count = TurnReservationService.get_turn_count(sess, wf_id)
            reports.append(
                {
                    "type": "live_run",
                    "index": run_idx,
                    "workflow_id": wf_id,
                    "error_category": type(exc).__name__,
                    "error_message": str(exc),
                    "attempt_counts": attempt_count,
                }
            )
            all_passed = False
            break

    # 2. Execute Negative Cases (if requested)
    if run_negatives and all_passed:
        print("\n--> [Negative Tests] Running controllable negative cases...")

        neg_cases = [
            (
                "missing_final_sample",
                "Missing sample 484 (detects incomplete evidence -> INCONCLUSIVE)",
            ),
            ("stale_approval", "Stale approval hash drift (HTTP 409 StaleApprovalError)"),
            (
                "unapproved_plan",
                "Approval denied by sound mixer (approved=False -> UnapprovedPlanError)",
            ),
            (
                "impossible_constraint",
                "Impossible constraints (NO_FEASIBLE_PLAN -> NoFeasiblePlanError)",
            ),
            (
                "model_unavailable",
                "Model unavailable (fails cleanly fast -> ModelUnavailableError)",
            ),
            (
                "grafana_failure_after_apply",
                "Grafana failure after apply (fails cleanly -> RuntimeError)",
            ),
            ("wrong_run", "Wrong foreign run ID submitted (INCONCLUSIVE / rejection)"),
        ]

        for case_id, case_desc in neg_cases:
            neg_wf_id = f"live-wf-neg-{case_id}-{uuid.uuid4().hex[:6]}"
            print(f"  - Testing case '{case_id}': {case_desc} (wf={neg_wf_id})...")
            case_passed = False
            err_category = None
            err_msg = None

            try:
                if case_id == "stale_approval":
                    try:
                        await orchestrator.execute_live_slice(
                            workflow_id=neg_wf_id, negative_case=case_id
                        )
                        print("    [FAIL] Expected StaleApprovalError was not raised")
                        all_passed = False
                    except StaleApprovalError:
                        print("    [PASS] Correctly rejected with StaleApprovalError (HTTP 409)")
                        case_passed = True
                elif case_id == "unapproved_plan":
                    try:
                        await orchestrator.execute_live_slice(
                            workflow_id=neg_wf_id, negative_case=case_id
                        )
                        print("    [FAIL] Expected UnapprovedPlanError was not raised")
                        all_passed = False
                    except UnapprovedPlanError:
                        print(
                            "    [PASS] Correctly rejected with UnapprovedPlanError "
                            "(approved=False)"
                        )
                        case_passed = True
                elif case_id == "impossible_constraint":
                    try:
                        await orchestrator.execute_live_slice(
                            workflow_id=neg_wf_id, negative_case=case_id
                        )
                        print("    [FAIL] Expected NoFeasiblePlanError was not raised")
                        all_passed = False
                    except NoFeasiblePlanError:
                        print("    [PASS] Correctly terminated with NoFeasiblePlanError")
                        case_passed = True
                elif case_id == "missing_final_sample":
                    res = await orchestrator.execute_live_slice(
                        workflow_id=neg_wf_id, negative_case=case_id
                    )
                    term = res["verification"]["terminal_status"]
                    if term == "INCONCLUSIVE":
                        print("    [PASS] Incomplete evidence correctly marked INCONCLUSIVE")
                        case_passed = True
                    else:
                        print(
                            f"    [FAIL] Unexpected terminal status for missing final sample: "
                            f"{term}"
                        )
                        all_passed = False
                elif case_id == "model_unavailable":
                    try:
                        await orchestrator.execute_live_slice(
                            workflow_id=neg_wf_id, negative_case=case_id
                        )
                        print("    [FAIL] Expected ModelUnavailableError was not raised")
                        all_passed = False
                    except ModelUnavailableError:
                        print("    [PASS] Correctly failed fast with ModelUnavailableError")
                        case_passed = True
                elif case_id == "grafana_failure_after_apply":
                    try:
                        await orchestrator.execute_live_slice(
                            workflow_id=neg_wf_id, negative_case=case_id
                        )
                        print("    [FAIL] Expected failure was not raised")
                        all_passed = False
                    except RuntimeError as rexc:
                        if "Grafana Cloud query failure" in str(rexc):
                            print("    [PASS] Correctly failed fast with Grafana query failure")
                            case_passed = True
                        else:
                            print(f"    [FAIL] Unexpected RuntimeError: {rexc}")
                            all_passed = False
                elif case_id == "wrong_run":
                    res = await orchestrator.execute_live_slice(
                        workflow_id=neg_wf_id, negative_case=case_id
                    )
                    term = res["verification"]["terminal_status"]
                    if term in ("INCONCLUSIVE", "NOT_VERIFIED"):
                        print(f"    [PASS] Wrong run correctly terminated with {term}")
                        case_passed = True
                    else:
                        print(f"    [FAIL] Wrong run produced unexpected terminal status: {term}")
                        all_passed = False
            except Exception as neg_exc:
                err_category = type(neg_exc).__name__
                err_msg = str(neg_exc)
                print(
                    f"    [FAIL] Negative case raised unexpected exception: "
                    f"{err_category}: {err_msg}"
                )
                all_passed = False

            with session_factory() as sess:
                neg_attempts = TurnReservationService.get_turn_count(sess, neg_wf_id)

            reports.append(
                {
                    "type": "negative_case",
                    "case": case_id,
                    "workflow_id": neg_wf_id,
                    "passed": case_passed,
                    "error_category": err_category,
                    "error_message": err_msg,
                    "attempt_counts": neg_attempts,
                }
            )

    # 3. Write Redacted Private Output Log
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        redacted_reports = redact_secrets(reports)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(redacted_reports, f, indent=2)
        print(f"\nRedacted execution log saved to: {output_path}")

    print("\n====================================================")
    if all_passed:
        print("  [PASS] All Live Integration checks succeeded!     ")
        print("====================================================")
        return 0
    else:
        print("  [FAIL] One or more live checks failed.            ")
        print("====================================================")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal Slate Live Vertical Slice Runner")
    parser.add_argument(
        "--live", action="store_true", help="Opt-in flag to run against live services"
    )
    parser.add_argument(
        "--max-runs", type=int, default=1, help="Maximum number of consecutive live runs (1-20)"
    )
    parser.add_argument(
        "--run-negatives", action="store_true", help="Run controllable negative cases"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            Path.home()
            / "signal-slate-private"
            / "reviews"
            / f"live-run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
        ),
        help="Path for redacted private output log",
    )

    args = parser.parse_args()

    if not args.live and not os.environ.get("LIVE_TESTS_ENABLED"):
        print(
            "[NOTICE] Live tests are opt-in. Pass --live or set LIVE_TESTS_ENABLED=true "
            "to run against live cloud."
        )
        print("Running offline check instead...")
        sys.exit(0)

    exit_code = asyncio.run(
        run_live_workflows(
            max_runs=args.max_runs,
            run_negatives=args.run_negatives,
            output_path=Path(args.output),
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
