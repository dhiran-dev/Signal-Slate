"""Deterministic boundaries around untrusted model interpretations and citations."""

from signal_slate.domain.models import ConstraintInterpretation, Finding, ShotContext
from signal_slate.evidence.mcp_client import BoundedModelEvidenceWrapper


class ConstraintValidationError(ValueError):
    """An interpretation cannot be presented as a confirmable constraint."""


def validate_interpretation(
    result: ConstraintInterpretation, source: str, context: ShotContext
) -> ConstraintInterpretation:
    if result.status != "SUPPORTED":
        if result.constraints:
            raise ConstraintValidationError(
                "Non-supported interpretation must contain no constraints."
            )
        return result
    if not result.constraints:
        raise ConstraintValidationError("Supported interpretation requires a typed constraint.")
    ids: set[str] = set()
    locks: dict[str | None, str] = {}
    for c in result.constraints:
        if c.confirmed:
            raise ConstraintValidationError("Only the human may confirm constraints.")
        if not c.constraint_id or c.constraint_id in ids:
            raise ConstraintValidationError("Constraint IDs must be nonempty and unique.")
        ids.add(c.constraint_id)
        if (
            c.source_text != source
            or not c.exact_source_span.strip()
            or c.exact_source_span not in source
        ):
            raise ConstraintValidationError("Constraint source must match the original human text.")
        if c.target_mic is not None and c.target_mic not in context.mic_ids:
            raise ConstraintValidationError("Unknown target microphone.")
        if c.kind == "CHANNEL_EXCLUSION":
            if (
                set(c.parameters) != {"excluded_channel"}
                or type(c.parameters["excluded_channel"]) is not int
            ):
                raise ConstraintValidationError(
                    "Channel exclusion requires an integer channel only."
                )
            channels = (
                context.available_channels.get(c.target_mic, [])
                if c.target_mic
                else [ch for values in context.available_channels.values() for ch in values]
            )
            if c.parameters["excluded_channel"] not in channels:
                raise ConstraintValidationError(
                    "Excluded channel is outside the declared candidates."
                )
        elif c.kind == "RIG_LOCK":
            if c.parameters or c.target_mic not in context.mic_ids:
                raise ConstraintValidationError(
                    "Rig lock requires a known microphone and empty parameters."
                )
        elif c.kind == "BOOM_EXCLUSION":
            if c.parameters:
                raise ConstraintValidationError("Boom exclusion accepts no parameters.")
        elif c.kind == "ANTENNA_LOCK":
            if (
                set(c.parameters) != {"locked_antenna"}
                or c.parameters["locked_antenna"] not in context.available_antennas
            ):
                raise ConstraintValidationError("Unknown or malformed antenna lock.")
            antenna = c.parameters["locked_antenna"]
            if locks and antenna not in locks.values():
                raise ConstraintValidationError("Conflicting antenna locks require clarification.")
            locks[c.target_mic] = antenna
        else:
            raise ConstraintValidationError("Unsupported constraint kind.")
    return result


def validate_finding_evidence(
    finding: Finding,
    wrapper: BoundedModelEvidenceWrapper,
    returned_ids: set[str],
    context: ShotContext,
) -> None:
    """Require citations to support the declared microphone, interval and risk class.

    This validates measurable claims, not arbitrary prose or causal certainty.
    """
    start, end = finding.interval_ms
    if finding.affected_mic not in context.mic_ids or not 0 <= start < end <= context.duration_ms:
        raise ValueError("Finding microphone or interval is outside the observed shot.")
    if not finding.evidence_ids:
        raise ValueError("Finding has no evidence citations.")
    support = False
    for cid in finding.evidence_ids:
        env = wrapper._envelopes.get(cid)
        if cid not in returned_ids or env is None:
            raise ValueError("Finding cited an unreturned evidence ID.")
        if (
            env.run_id != wrapper.observed_run.run_id
            or env.config_hash != wrapper.observed_run.config_hash
            or env.mic_id != finding.affected_mic
        ):
            raise ValueError("Citation does not support the claimed run/configuration/microphone.")
        if env.offset_ms is None:
            raise ValueError("Citation has no observation time.")
        width = 1000 if env.observation_type == "metric_summary" else context.sample_period_ms
        if not (env.offset_ms < end and env.offset_ms + width > start):
            raise ValueError(
                f"Citation {cid} covers [{env.offset_ms}, {env.offset_ms + width})ms "
                f"but claimed interval is [{start}, {end})ms. End is exclusive."
            )
        value = env.value
        anomalous = bool(
            value.get("is_dropout")
            or value.get("is_clipped")
            or value.get("dropout_duration_ms", 0)
            or value.get("clipping_duration_ms", 0)
            or value.get("quality", value.get("min_quality", 100)) < 60
        )
        support = support or anomalous
    if finding.status == "RISK_IDENTIFIED" and not support:
        raise ValueError("Healthy citations cannot establish the claimed risk.")
    if finding.status == "HEALTHY":
        if any(
            s.mic_id == finding.affected_mic
            and start <= s.offset_ms < end
            and (s.is_dropout or s.is_clipped or s.quality < 60)
            for s in wrapper.observed_run.samples
        ):
            raise ValueError("Healthy claim contradicts the observed interval.")

    interval_samples = [
        s
        for s in wrapper.observed_run.samples
        if s.mic_id == finding.affected_mic and start <= s.offset_ms < end
    ]
    pure_clipping = any(s.is_clipped for s in interval_samples) and all(
        not s.is_dropout and s.quality >= 60 and s.link_margin_db >= 0 for s in interval_samples
    )
    if pure_clipping and finding.recommended_action.action_type in (
        "CHANNEL_SWITCH",
        "ANTENNA_SWITCH",
    ):
        raise ValueError("RF intervention cannot address isolated clipping with healthy RF.")
    if (
        finding.status in ("HEALTHY", "INCONCLUSIVE")
        and finding.recommended_action.action_type != "NO_ACTION"
    ):
        raise ValueError(
            "Healthy or inconclusive findings cannot authorize corrective interventions."
        )
