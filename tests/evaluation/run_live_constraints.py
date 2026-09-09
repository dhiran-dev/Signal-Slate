"""Explicit bounded live evaluation. Input cases and outputs stay outside the repository.

Admits one normal daily-budgeted browser session per two cases. Each case has one
model dispatch; no repair or implicit retry. Session and turn ledgers are retained.
"""

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import google.auth
from fastapi.testclient import TestClient
from signal_slate.agent.live_adk import SignalSlateAdkAgent
from signal_slate.config import get_settings
from signal_slate.db import get_engine
from signal_slate.domain.models import ShotContext
from signal_slate.main import app
from signal_slate.persistence.turn_reservations import TurnReservationService
from sqlalchemy.orm import sessionmaker


async def run(cases_path: Path, output_path: Path) -> int:
    root = Path(__file__).resolve().parents[2]
    if cases_path.resolve().is_relative_to(root) or output_path.resolve().is_relative_to(root):
        raise ValueError("Private evaluation inputs and reports must be outside the repository.")
    cases = json.loads(cases_path.read_text())
    if not 12 <= len(cases) <= 18:
        raise ValueError("Evaluation requires 12 to 18 cases; maximum 18 model requests.")
    try:
        google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise ValueError("BLOCKED: configure local Google ADC before live evaluation.") from exc
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    agent = SignalSlateAdkAgent(factory, get_settings())
    # Unlike production's two-response maximum, this evaluation permits only one
    # response per case. Tools are disabled for interpretation by the callback.
    original_callback = agent.agent.before_model_callback
    calls: dict[str, int] = {}

    def bounded_callback(callback_context, llm_request):
        key = str(callback_context.invocation_id)
        calls[key] = calls.get(key, 0) + 1
        if calls[key] > 1 or sum(calls.values()) > 18:
            raise ValueError("Evaluation one-response-per-case budget exhausted")
        return original_callback(callback_context=callback_context, llm_request=llm_request)

    agent.agent.before_model_callback = bounded_callback
    results = []
    with TestClient(app) as client:
        workflow = ""
        for index, case in enumerate(cases):
            if index % 2 == 0:
                response = client.post("/api/sessions", json={"mode": "live"})
                if response.status_code != 201:
                    results.append(
                        {"id": case["id"], "status": "BLOCKED", "reason": response.json()}
                    )
                    break
                workflow = "eval-" + response.json()["id"]
                with factory() as db:
                    TurnReservationService.ensure_workflow_session(db, workflow)
            try:
                result = await agent.interpret_constraint(workflow, case["text"], ShotContext())
                correct = result.status == case["status"]
                if case["status"] == "SUPPORTED":
                    correct = (
                        correct
                        and len(result.constraints) == 1
                        and all(
                            c.kind == case["kind"]
                            and c.target_mic == case["target"]
                            and c.parameters == case["parameters"]
                            for c in result.constraints
                        )
                    )
                else:
                    correct = correct and not result.constraints
                results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "status": "PASS" if correct else "FAIL",
                        "output": result.model_dump(mode="json"),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "status": "FAIL",
                        "error": type(exc).__name__,
                    }
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"results": results}, indent=2))
            os.chmod(output_path, 0o600)
    clear = [r for r in results if r.get("category", "").startswith("clear_")]
    correct = sum(r["status"] == "PASS" for r in clear)
    report = {
        "model": get_settings().gemini_model,
        "case_count": len(cases),
        "completed": len(results),
        "category_counts": dict(Counter(c["category"] for c in cases)),
        "clear_correct": correct,
        "clear_total": len(clear),
        "clear_accuracy": correct / len(clear) if clear else 0,
        "dispatches": sum(min(v, 1) for v in calls.values()),
        "results": results,
    }
    output_path.write_text(json.dumps(report, indent=2))
    os.chmod(output_path, 0o600)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))
    return (
        0
        if len(results) == len(cases)
        and correct / max(len(clear), 1) >= 0.9
        and all(
            r["status"] == "PASS" for r in results if not r.get("category", "").startswith("clear_")
        )
        else 1
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.cases, args.output)))
