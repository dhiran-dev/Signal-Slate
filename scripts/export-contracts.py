"""Freeze API paths plus shared domain schemas without credentials or network I/O."""

import json
from pathlib import Path

from pydantic import TypeAdapter
from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    ConstraintInterpretation,
    EvidenceEnvelope,
    EvidenceManifest,
    Finding,
    ObservedRun,
    PlanApproval,
    RunConfig,
    ShotContext,
    VerificationResult,
)
from signal_slate.main import app

models = TypeAdapter(
    tuple[
        CandidateAction,
        CandidatePlan,
        Constraint,
        ConstraintInterpretation,
        EvidenceEnvelope,
        EvidenceManifest,
        Finding,
        ObservedRun,
        PlanApproval,
        RunConfig,
        ShotContext,
        VerificationResult,
    ]
)
schema = app.openapi()
definitions = models.json_schema(ref_template="#/components/schemas/{model}")["$defs"]
schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
path = Path(__file__).resolve().parents[1] / "contracts" / "openapi.json"
if "--check" in __import__("sys").argv:
    if not path.exists() or path.read_text() != content:
        raise SystemExit("API contract drift: run uv run scripts/export-contracts.py")
    print("Frozen OpenAPI and domain schemas match current source")
else:
    path.write_text(content)
    print("Exported contracts/openapi.json")
