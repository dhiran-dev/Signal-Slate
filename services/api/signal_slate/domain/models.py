"""Domain models and contracts for Signal Slate rehearsal workflow.

Strict Pydantic models with explicit types and field validation.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def canonical_hash(obj: Any) -> str:
    """Compute deterministic SHA-256 hash of a JSON-serializable object or model."""
    if hasattr(obj, "model_dump"):
        data = obj.model_dump(mode="json")
    elif isinstance(obj, dict):
        data = obj
    else:
        data = obj
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ShotContext(BaseModel):
    """Context for the 12-second rehearsed cinema scene."""

    model_config = ConfigDict(extra="forbid")

    shot_id: str = "shot_012_alleyway"
    duration_ms: int = 12000
    sample_period_ms: int = 100
    mic_ids: list[str] = Field(default_factory=lambda: ["mic_1", "mic_2", "mic_3", "mic_4"])
    performer_names: dict[str, str] = Field(
        default_factory=lambda: {
            "mic_1": "Elena (Lead)",
            "mic_2": "Marcus (Lead)",
            "mic_3": "Security Guard",
            "mic_4": "Overhead Boom",
        }
    )
    critical_line_start_ms: int = 4900
    critical_line_end_ms: int = 6800
    transcript: str = (
        "Perimeter sensors detected breached access at section nine; "
        "whatever happens, do not cut the feed until our squad secures point alpha."
    )
    critical_dialogue_text: str = "do not cut the feed"
    vulnerable_word: str = "cut"
    timing_precision: str = "approximate"
    synthetic_disclosure: str = (
        "Explicitly synthetic speech generated via Google Cloud Vertex AI Text-to-Speech API. "
        "Phrase timings are approximate intervals based on audio energy profile "
        "for rehearsal alignment, "
        "not forced word-level alignments."
    )
    source_audio_hash: str = "d7afbe4395aad34313673f18fae92c90be7fd34e33d072fe882cf3ed24c50c03"
    scenario_path_hash: str = "4f738b55be5534c0fa6b986e66164f9bf3cf8813a408719bc45d6148386b0336"
    available_channels: dict[str, list[int]] = Field(
        default_factory=lambda: {
            "mic_1": [10, 11, 12],
            "mic_2": [20, 21],
            "mic_3": [30, 31],
            "mic_4": [40],
        }
    )
    available_antennas: list[str] = Field(default_factory=lambda: ["A", "B"])
    available_backup_sources: dict[str, list[str]] = Field(
        default_factory=lambda: {"mic_1": ["mic_4"], "mic_2": ["mic_4"], "mic_3": ["mic_4"]}
    )
    notes: str = "Exterior alleyway scene. Metal fire escape causes RF reflection."


class MicSample(BaseModel):
    """100ms raw observation sample for a specific microphone."""

    model_config = ConfigDict(extra="forbid")

    offset_ms: int = Field(ge=0, le=12000)
    mic_id: str
    quality: float = Field(ge=0.0, le=100.0)
    link_margin_db: float
    battery_pct: float = Field(ge=0.0, le=100.0)
    is_clipped: bool = False
    is_dropout: bool = False
    timestamp_rfc3339: str = ""
    run_id: str = ""
    session_id: str = ""
    config_hash: str = ""


class PerSecondMetric(BaseModel):
    """Per-second aggregated telemetry metric summary for a microphone."""

    model_config = ConfigDict(extra="forbid")

    second: int = Field(ge=0, le=11)
    mic_id: str
    min_quality: float = Field(ge=0.0, le=100.0)
    min_link_margin_db: float
    min_battery_pct: float = Field(ge=0.0, le=100.0)
    clipping_duration_ms: int = Field(ge=0, le=1000)
    dropout_duration_ms: int = Field(ge=0, le=1000)
    timestamp_rfc3339: str = ""
    run_id: str = ""
    session_id: str = ""
    config_hash: str = ""


class EvidenceManifest(BaseModel):
    """Cryptographic manifest binding cloud evidence, commitments, and run metadata."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    run_id: str
    session_id: str
    config_hash: str
    scenario_id: str = "scene_12_rehearsal"
    scenario_version: str = "1.0"
    source_audio_hash: str
    scenario_path_hash: str
    fault_commitment_hash: str
    created_at_rfc3339: str
    sample_count: int = 484
    metric_count: int = 48

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self)


class EvidenceContext(BaseModel):
    """Context holding immutable session parameters and sealed fault commitment."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    scenario_id: str = "scene_12_rehearsal"
    scenario_version: str = "1.0"
    source_audio_hash: str
    scenario_path_hash: str
    fault_commitment_hash: str
    base_config_hash: str

    def create_manifest(
        self,
        run_id: str,
        config_hash: str,
        created_at_rfc3339: str | None = None,
        sample_count: int = 484,
        metric_count: int = 48,
    ) -> EvidenceManifest:
        """Create an immutable pre-publication evidence manifest bound to a run."""
        created_at = created_at_rfc3339 or datetime.now(UTC).isoformat()
        return EvidenceManifest(
            manifest_id=f"manifest-{run_id}",
            run_id=run_id,
            session_id=self.session_id,
            config_hash=config_hash,
            scenario_id=self.scenario_id,
            scenario_version=self.scenario_version,
            source_audio_hash=self.source_audio_hash,
            scenario_path_hash=self.scenario_path_hash,
            fault_commitment_hash=self.fault_commitment_hash,
            created_at_rfc3339=created_at,
            sample_count=sample_count,
            metric_count=metric_count,
        )


class RunConfig(BaseModel):
    """Configuration applied to the simulator for a rehearsal run."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = "scene_12_rehearsal"
    channel_assignments: dict[str, int] = Field(
        default_factory=lambda: {
            "mic_1": 10,
            "mic_2": 20,
            "mic_3": 30,
            "mic_4": 40,
        }
    )
    antenna_selection: str = "A"
    backup_sources: dict[str, str] = Field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        return canonical_hash(self)


class EvidenceEnvelope(BaseModel):
    """Normalized evidence record retrieved from Grafana Cloud via MCP."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    run_id: str
    mic_id: str
    offset_ms: int | None = None
    source_tool: str  # e.g., 'query_prometheus', 'query_loki_logs'
    query_hash: str
    observation_type: str  # e.g., 'sample_dropout', 'metric_summary', 'completion_marker'
    value: Any
    unit: str = ""
    retrieval_time: str
    config_hash: str


class CandidateAction(BaseModel):
    """Specific corrective intervention applied to microphone configuration."""

    model_config = ConfigDict(extra="forbid")

    action_type: Literal["CHANNEL_SWITCH", "ANTENNA_SWITCH", "BOOM_COVERAGE", "NO_ACTION"]
    mic_id: str
    parameters: dict[str, Any]

    @property
    def action_hash(self) -> str:
        return canonical_hash(self)


def actions_hash(actions: list[CandidateAction]) -> str:
    """Bind the complete ordered action list using canonical JSON."""
    return canonical_hash([action.model_dump(mode="json") for action in actions])


class Constraint(BaseModel):
    """Creative constraint discovered or confirmed by human operator."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    kind: Literal["CHANNEL_EXCLUSION", "RIG_LOCK", "ANTENNA_LOCK", "BOOM_EXCLUSION", "CUSTOM"]
    target_mic: str | None = None
    parameters: dict[str, Any]  # e.g. {"excluded_channel": 11}
    exact_source_span: str
    source_text: str
    confirmed: bool = False

    @property
    def constraint_hash(self) -> str:
        return canonical_hash(self)


class ConstraintInterpretation(BaseModel):
    """Output of Gemini constraint parsing from human natural text."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUPPORTED", "AMBIGUOUS", "CONTRADICTORY", "UNSUPPORTED"]
    constraints: list[Constraint]
    rationale: str


class CandidatePlan(BaseModel):
    """Proposed corrective plan with explicit hash binding."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_version: int = 1
    actions: list[CandidateAction]
    action_hash: str
    constraints_hash: str
    base_config_hash: str
    rationale: str
    tradeoffs: list[str] = Field(default_factory=list)


class PlanApproval(BaseModel):
    """Human decision record binding exact plan version and hashes."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_version: int
    action_hash: str
    constraints_hash: str
    base_config_hash: str
    approved: bool
    approved_by: str = "sound_mixer"
    approved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def verify_match(self, plan: CandidatePlan) -> bool:
        """Verify that approval matches the target plan exactly without stale drift."""
        return (
            self.plan_id == plan.plan_id
            and self.plan_version == plan.plan_version
            and self.action_hash == plan.action_hash
            and self.constraints_hash == plan.constraints_hash
            and self.base_config_hash == plan.base_config_hash
        )


class Finding(BaseModel):
    """Investigation finding produced by Google ADK reasoning agent."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["RISK_IDENTIFIED", "HEALTHY", "INCONCLUSIVE"]
    affected_mic: str
    interval_ms: tuple[int, int]
    observations: list[str]
    evidence_ids: list[str] = Field(
        description="Must cite actual EvidenceEnvelope IDs returned by wrapper tools"
    )
    competing_explanations: list[str] = Field(default_factory=list)
    recommended_action: CandidateAction


class ObservedRun(BaseModel):
    """Fresh run evidence assembled strictly from Grafana Cloud MCP queries."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    config_hash: str
    samples: list[MicSample]
    metrics: list[PerSecondMetric]
    completion_marker_present: bool
    retrieved_sample_count: int
    start_time_rfc3339: str
    end_time_rfc3339: str
    is_truncated: bool = False
    has_conflicting_duplicates: bool = False
    identical_duplicate_count: int = Field(default=0, ge=0)
    source_audio_hash: str = ""
    scenario_path_hash: str = ""
    fault_commitment_hash: str = ""
    manifest: EvidenceManifest | None = None


def create_evidence_context(
    session_id: str,
    base_config: RunConfig,
    source_audio_hash: str = "d7afbe4395aad34313673f18fae92c90be7fd34e33d072fe882cf3ed24c50c03",
    scenario_path_hash: str = "4f738b55be5534c0fa6b986e66164f9bf3cf8813a408719bc45d6148386b0336",
    scenario_id: str = "scene_12_rehearsal",
    scenario_version: str = "1.0",
    seed: int = 42,
    fault_family: str = "channel_interference",
    fault_params: dict[str, Any] | None = None,
    secret_nonce: str | None = None,
) -> tuple[EvidenceContext, str]:
    """Create a sealed evidence context with a cryptographically opaque fault commitment.

    Returns:
        tuple[EvidenceContext, str]: (evidence_context, secret_nonce)
    The secret_nonce and fault realization parameters remain strictly private.
    Only the opaque SHA-256 commitment hash is published in manifests.
    The raw audio hash is NOT the fault commitment.
    """
    import uuid

    nonce = secret_nonce or uuid.uuid4().hex
    fault_realization = {
        "scenario_id": scenario_id,
        "scenario_version": scenario_version,
        "fault_family": fault_family,
        "fault_params": fault_params or {"channel": 10, "affected_mic": "mic_1"},
        "seed": seed,
        "nonce": nonce,
    }
    fault_commitment_hash = canonical_hash(fault_realization)
    assert fault_commitment_hash != source_audio_hash, "Raw audio hash cannot be fault commitment"

    ev_ctx = EvidenceContext(
        session_id=session_id,
        scenario_id=scenario_id,
        scenario_version=scenario_version,
        source_audio_hash=source_audio_hash,
        scenario_path_hash=scenario_path_hash,
        fault_commitment_hash=fault_commitment_hash,
        base_config_hash=base_config.config_hash,
    )
    return ev_ctx, nonce


class VerificationResult(BaseModel):
    """Deterministic verifier evaluation result computed from fresh cloud evidence."""

    model_config = ConfigDict(extra="forbid")

    terminal_status: Literal["VERIFIED", "NOT_VERIFIED", "INCONCLUSIVE"]
    completeness_passed: bool
    crosscheck_passed: bool
    thresholds_passed: bool
    dialogue_coverage_passed: bool
    constraints_passed: bool
    baseline_run_id: str
    comparison_run_id: str
    evidence_hashes: dict[str, str]
    failure_reasons: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
