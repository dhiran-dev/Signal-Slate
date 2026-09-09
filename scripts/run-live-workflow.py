"""Explicit, bounded live API acceptance. Never bypass session or model budgets."""

import argparse
import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from signal_slate.main import app

parser = argparse.ArgumentParser()
parser.add_argument("--preset", choices=["a", "b", "c", "control"], default="a")
parser.add_argument("--runs", type=int, choices=[1, 2, 3], default=1)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = args.output.expanduser().resolve()
if output.is_relative_to(root):
    raise SystemExit("Use a private output path outside the repository")
if os.getenv("LIVE_TESTS_ENABLED") != "true":
    raise SystemExit("BLOCKED: LIVE_TESTS_ENABLED=true is required")
results = []
failed = False
for index in range(args.runs):
    start = time.monotonic()
    try:
        with TestClient(app) as client:
            created = client.post("/api/sessions", json={"mode": "live", "preset": args.preset})
            if created.status_code != 201:
                raise RuntimeError(f"Admission rejected ({created.status_code}); no bypass")
            state = created.json()
            sid = state["id"]
            csrf = state["csrf_token"]

            def step(operation, extra=None, sid=sid, csrf=csrf, client=client):
                global state
                response = client.post(
                    f"/api/sessions/{sid}/{operation}",
                    json={"revision": state["revision"], **(extra or {})},
                    headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"acceptance-{operation}"},
                )
                if response.status_code != 200:
                    raise RuntimeError(f"{operation} rejected ({response.status_code})")
                state = response.json()
                if state.get("error"):
                    error = state["error"]
                    detail = (
                        error.get("code", "Operation failed") if isinstance(error, dict) else error
                    )
                    raise RuntimeError(f"{operation}: {detail}")

            step("baseline")
            step("investigate")
            if state["state"] != "NO_RISK":
                step("constraints", {"text": "Exclude channel 11"})
                constraints = [
                    c | {"confirmed": True} for c in state["interpretation"]["constraints"]
                ]
                step("confirm", {"constraints": constraints})
                if not state["candidate_plans"]:
                    raise RuntimeError("No feasible candidate")
                plan = state["candidate_plans"][0]
                approval = {
                    key: plan[key]
                    for key in (
                        "plan_id",
                        "plan_version",
                        "action_hash",
                        "constraints_hash",
                        "base_config_hash",
                    )
                }
                step("approve", {"approval": approval | {"approved": True}})
                step("apply")
            verdict = (state.get("verification") or {}).get("terminal_status", state["state"])
            # Preserve actual model choices; a complete failed correction is an honest outcome,
            # but does not count as a successful repair acceptance.
            accepted = verdict == "NO_RISK" if args.preset == "control" else verdict == "VERIFIED"
            if args.preset == "c":
                accepted = (
                    verdict == "NOT_VERIFIED"
                    and state["verification"]["dialogue_coverage_passed"]
                    and not state["verification"]["thresholds_passed"]
                )
            results.append(
                {
                    "attempt": index + 1,
                    "accepted": accepted,
                    "seconds": round(time.monotonic() - start, 1),
                    "session": {k: v for k, v in state.items() if k != "csrf_token"},
                }
            )
            failed = failed or not accepted
    except Exception as exc:
        results.append({"attempt": index + 1, "accepted": False, "error": str(exc)})
        failed = True
        break
output.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w") as file:
    json.dump(results, file, indent=2)
print(
    json.dumps(
        {
            "attempts": len(results),
            "accepted": sum(r["accepted"] for r in results),
            "passed": not failed,
        }
    )
)
raise SystemExit(1 if failed else 0)
