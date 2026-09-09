"""Deterministic verifier for Signal Slate.

Verifies rehearsal success strictly against fresh Grafana Cloud MCP evidence.
Performs exact 484-sample grid check, 48-metric grid check, finite value verification,
source/path/fault commitment verification, metrics cross-check, threshold evaluation,
and deterministic constraint compliance.

Missing/stale/corrupted/contradictory evidence yields INCONCLUSIVE.
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from signal_slate.domain.models import (
    CandidatePlan,
    Constraint,
    ObservedRun,
    ShotContext,
    VerificationResult,
    actions_hash,
    canonical_hash,
)


def validate_observed_run_invariants(
    run: ObservedRun,
    expected_config_hash: str,
    expected_session_id: str,
    now_dt: datetime,
    max_age_seconds: float,
    shot_context: ShotContext,
    is_comparison: bool = False,
) -> tuple[bool, bool, list[str]]:
    """Validate all scope, authenticity, grid completeness, and cross-check invariants for a run.

    Returns:
        tuple[bool, bool, list[str]]: (completeness_passed, crosscheck_passed, failure_reasons)
    """
    failure_reasons: list[str] = []
    completeness_passed = True
    crosscheck_passed = True
    role = "Comparison" if is_comparison else "Baseline"

    def parse_utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("explicit UTC timestamp required")
        return parsed

    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        return False, False, ["Invalid evidence freshness bound"]
    # 1. Pre-publication Manifest Verification
    if run.manifest is None:
        completeness_passed = False
        failure_reasons.append(f"{role} run is missing required pre-publication EvidenceManifest")
        return completeness_passed, False, failure_reasons

    m = run.manifest
    if not m.manifest_id or not m.run_id or not m.session_id or not m.config_hash:
        completeness_passed = False
        failure_reasons.append(f"{role} manifest has empty provenance fields")

    if m.run_id != run.run_id:
        completeness_passed = False
        failure_reasons.append(
            f"{role} manifest run_id '{m.run_id}' does not match run '{run.run_id}'"
        )

    if m.session_id != expected_session_id or run.session_id != expected_session_id:
        completeness_passed = False
        failure_reasons.append(
            f"{role} session_id mismatch: expected '{expected_session_id}', "
            f"got run='{run.session_id}', manifest='{m.session_id}'"
        )

    if (
        m.sample_count != 484
        or m.metric_count != 48
        or run.retrieved_sample_count != len(run.samples)
    ):
        completeness_passed = False
        failure_reasons.append(f"{role} manifest or retrieval counts do not match required grids")
    if (
        m.source_audio_hash != shot_context.source_audio_hash
        or m.scenario_path_hash != shot_context.scenario_path_hash
    ):
        completeness_passed = False
        failure_reasons.append(f"{role} manifest source/path differs from trusted shot context")
    if not m.scenario_id or not m.scenario_version:
        completeness_passed = False
        failure_reasons.append(f"{role} manifest scenario identity missing")

    # 2. Config Hash Verification (Unconditional: NO fallback/defaults)
    if not expected_config_hash:
        completeness_passed = False
        failure_reasons.append(
            f"Authoritative expected_config_hash must be explicitly provided for {role} run"
        )
    elif run.config_hash != expected_config_hash:
        completeness_passed = False
        failure_reasons.append(
            f"{role} config hash '{run.config_hash}' does not match authoritative "
            f"expected config hash '{expected_config_hash}'"
        )

    if m.config_hash != expected_config_hash:
        completeness_passed = False
        failure_reasons.append(
            f"{role} manifest config_hash '{m.config_hash}' does not match "
            f"expected '{expected_config_hash}'"
        )

    # 3. Cryptographic Commitments
    if not m.source_audio_hash or not m.scenario_path_hash or not m.fault_commitment_hash:
        completeness_passed = False
        failure_reasons.append(
            f"{role} manifest contains missing or empty cryptographic commitments"
        )

    if m.fault_commitment_hash == m.source_audio_hash:
        completeness_passed = False
        failure_reasons.append(
            f"{role} fault commitment equals raw audio hash; invalid sealed commitment"
        )

    if not run.source_audio_hash or run.source_audio_hash != m.source_audio_hash:
        completeness_passed = False
        failure_reasons.append(f"{role} run source_audio_hash does not match manifest")

    if not run.scenario_path_hash or run.scenario_path_hash != m.scenario_path_hash:
        completeness_passed = False
        failure_reasons.append(f"{role} run scenario_path_hash does not match manifest")

    if not run.fault_commitment_hash or run.fault_commitment_hash != m.fault_commitment_hash:
        completeness_passed = False
        failure_reasons.append(f"{role} run fault_commitment_hash does not match manifest")

    # 4. Completion Marker & MCP Query Health
    if not run.completion_marker_present:
        completeness_passed = False
        failure_reasons.append(f"{role} run completion marker missing from cloud logs")

    if run.is_truncated:
        completeness_passed = False
        failure_reasons.append(f"{role} MCP query returned truncated results")

    if run.has_conflicting_duplicates:
        completeness_passed = False
        failure_reasons.append(f"{role} conflicting duplicate telemetry sample pairs detected")

    # 5. UTC Time & Staleness Bounds (Injected now, explicit max age, no year-only threshold)
    clock_tolerance = timedelta(seconds=5.0)
    max_age = timedelta(seconds=max_age_seconds)

    st_dt: datetime | None = None
    try:
        st_dt = parse_utc(run.start_time_rfc3339)
        et_dt = parse_utc(run.end_time_rfc3339)
        m_dt = parse_utc(m.created_at_rfc3339)
        if abs((et_dt - st_dt).total_seconds() - shot_context.duration_ms / 1000) > 0.01:
            raise ValueError("run window does not match shot duration")
        if m_dt > st_dt + timedelta(milliseconds=10):
            raise ValueError("manifest must precede rehearsal")
        if any(t > now_dt + clock_tolerance for t in (st_dt, et_dt, m_dt)):
            raise ValueError("future evidence timestamp")
        if any(t < now_dt - max_age for t in (st_dt, et_dt, m_dt)):
            raise ValueError("stale evidence older than max age")
    except (ValueError, TypeError) as exc:
        completeness_passed = False
        failure_reasons.append(f"{role} invalid UTC evidence timestamps: {exc}")

    def valid_row_time(value: str, offset_ms: int) -> bool:
        try:
            parsed = parse_utc(value)
            return (
                st_dt is not None
                and now_dt - max_age <= parsed <= now_dt + clock_tolerance
                and abs((parsed - st_dt).total_seconds() - offset_ms / 1000) <= 0.01
            )
        except (ValueError, TypeError):
            return False

    # 6. Exact 484 Sample Grid Verification (121 offsets x 4 mics)
    expected_offsets = list(
        range(
            0,
            shot_context.duration_ms + shot_context.sample_period_ms,
            shot_context.sample_period_ms,
        )
    )
    expected_sample_grid = {
        (m_id, off) for m_id in shot_context.mic_ids for off in expected_offsets
    }
    actual_sample_grid = {(s.mic_id, s.offset_ms) for s in run.samples}

    if actual_sample_grid != expected_sample_grid or len(run.samples) != 484:
        completeness_passed = False
        missing_pairs = expected_sample_grid - actual_sample_grid
        failure_reasons.append(
            f"{role} sample grid incomplete: expected 484 unique pairs, got "
            f"{len(actual_sample_grid)} "
            f"(missing {len(missing_pairs)})"
        )

    # Validate individual sample provenance, finiteness, and timestamps
    for s in run.samples:
        if not s.run_id or s.run_id != run.run_id:
            completeness_passed = False
            failure_reasons.append(f"{role} sample has invalid or foreign run_id: '{s.run_id}'")
            break
        if not s.session_id or s.session_id != expected_session_id:
            completeness_passed = False
            failure_reasons.append(
                f"{role} sample has invalid or foreign session_id: '{s.session_id}'"
            )
            break
        if not s.config_hash or s.config_hash != expected_config_hash:
            completeness_passed = False
            failure_reasons.append(
                f"{role} sample has invalid or foreign config_hash: '{s.config_hash}'"
            )
            break
        if not (
            math.isfinite(s.quality)
            and math.isfinite(s.link_margin_db)
            and math.isfinite(s.battery_pct)
        ):
            completeness_passed = False
            failure_reasons.append(
                f"{role} non-finite sample value found in {s.mic_id} offset {s.offset_ms}"
            )
            break
        if not (0.0 <= s.quality <= 100.0) or not (0.0 <= s.battery_pct <= 100.0):
            completeness_passed = False
            failure_reasons.append(
                f"{role} sample value out of bounds in {s.mic_id} offset {s.offset_ms}"
            )
            break
        if not valid_row_time(s.timestamp_rfc3339, s.offset_ms):
            completeness_passed = False
            failure_reasons.append(
                f"{role} invalid sample timestamp in {s.mic_id} offset {s.offset_ms}"
            )
            break

    # 7. Exact 48 Metrics Grid Verification (12 seconds x 4 mics)
    expected_metric_grid = {(m_id, sec) for m_id in shot_context.mic_ids for sec in range(12)}
    actual_metric_grid = {(m.mic_id, m.second) for m in run.metrics}

    if actual_metric_grid != expected_metric_grid or len(run.metrics) != 48:
        completeness_passed = False
        missing_m = expected_metric_grid - actual_metric_grid
        failure_reasons.append(
            f"{role} metrics grid incomplete: expected 48 metric rows (12 sec x 4 mics), "
            f"got {len(actual_metric_grid)} (missing {len(missing_m)})"
        )

    # Validate individual metric provenance and finiteness
    for m_val in run.metrics:
        if not m_val.run_id or m_val.run_id != run.run_id:
            completeness_passed = False
            failure_reasons.append(f"{role} metric has invalid or foreign run_id: '{m_val.run_id}'")
            break
        if not m_val.session_id or m_val.session_id != expected_session_id:
            completeness_passed = False
            failure_reasons.append(
                f"{role} metric has invalid or foreign session_id: '{m_val.session_id}'"
            )
            break
        if not m_val.config_hash or m_val.config_hash != expected_config_hash:
            completeness_passed = False
            failure_reasons.append(
                f"{role} metric has invalid or foreign config_hash: '{m_val.config_hash}'"
            )
            break
        if not (
            math.isfinite(m_val.min_quality)
            and math.isfinite(m_val.min_link_margin_db)
            and math.isfinite(m_val.min_battery_pct)
            and math.isfinite(m_val.clipping_duration_ms)
            and math.isfinite(m_val.dropout_duration_ms)
        ):
            completeness_passed = False
            failure_reasons.append(
                f"{role} non-finite metric value found in {m_val.mic_id} sec {m_val.second}"
            )
            break
        if not (0.0 <= m_val.min_quality <= 100.0) or not (0.0 <= m_val.min_battery_pct <= 100.0):
            completeness_passed = False
            failure_reasons.append(
                f"{role} metric value out of bounds in {m_val.mic_id} sec {m_val.second}"
            )
            break

        if not valid_row_time(m_val.timestamp_rfc3339, m_val.second * 1000):
            completeness_passed = False
            failure_reasons.append(
                f"{role} invalid metric timestamp in {m_val.mic_id} sec {m_val.second}"
            )
            break
        if not (0 <= m_val.clipping_duration_ms <= 1000 and 0 <= m_val.dropout_duration_ms <= 1000):
            completeness_passed = False
            failure_reasons.append(f"{role} metric duration out of bounds")
            break

    # 8. Metrics Cross-check Pass (Prometheus metrics vs Loki samples)
    if len(run.metrics) == 48 and len(run.samples) == 484 and completeness_passed:
        for m_val in run.metrics:
            sec_start = m_val.second * 1000
            sec_end = (m_val.second + 1) * 1000
            # Half-open interval for durations: [sec_start, sec_end)
            sec_samples = [
                s
                for s in run.samples
                if s.mic_id == m_val.mic_id and sec_start <= s.offset_ms < sec_end
            ]
            if sec_samples:
                # Instantaneous minimums evaluation (includes boundary 12000ms at second 11)
                if m_val.second == 11:
                    boundary_s = [
                        s for s in run.samples if s.mic_id == m_val.mic_id and s.offset_ms == 12000
                    ]
                    eval_samples = sec_samples + boundary_s
                else:
                    eval_samples = sec_samples

                calc_min_q = min(s.quality for s in eval_samples)
                calc_min_link = min(s.link_margin_db for s in eval_samples)
                calc_min_batt = min(s.battery_pct for s in eval_samples)
                calc_drop = sum(100 for s in sec_samples if s.is_dropout)
                calc_clip = sum(100 for s in sec_samples if s.is_clipped)

                if (
                    abs(calc_min_q - m_val.min_quality) > 0.2
                    or abs(calc_min_link - m_val.min_link_margin_db) > 0.2
                    or abs(calc_min_batt - m_val.min_battery_pct) > 0.2
                ):
                    crosscheck_passed = False
                    failure_reasons.append(
                        f"{role} metric crosscheck contradiction for {m_val.mic_id} sec "
                        f"{m_val.second}: "
                        f"Q={m_val.min_quality} (calc={calc_min_q:.1f}), "
                        f"Link={m_val.min_link_margin_db} (calc={calc_min_link:.1f}), "
                        f"Batt={m_val.min_battery_pct} (calc={calc_min_batt:.1f})"
                    )
                if (
                    calc_drop != m_val.dropout_duration_ms
                    or calc_clip != m_val.clipping_duration_ms
                ):
                    crosscheck_passed = False
                    failure_reasons.append(
                        f"{role} metric duration contradiction for {m_val.mic_id} sec "
                        f"{m_val.second}: "
                        f"dropout={m_val.dropout_duration_ms} (calc={calc_drop}), "
                        f"clipping={m_val.clipping_duration_ms} (calc={calc_clip})"
                    )
    else:
        crosscheck_passed = False

    return completeness_passed, crosscheck_passed, failure_reasons


class DeterministicVerifier:
    def __init__(self, context: ShotContext | None = None) -> None:
        self.context = context or ShotContext()

    def verify_baseline_run(
        self,
        baseline_run: ObservedRun,
        expected_base_config_hash: str,
        now: datetime | None = None,
        max_age_seconds: float = 1800.0,
    ) -> VerificationResult:
        """Reject incomplete baseline evidence before Gemini.

        Verifies baseline scope, prepublication manifest, exact 484/48 grids, finite values,
        timestamps, and metric crosschecks.
        """
        now_dt = now or datetime.now(UTC)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=UTC)

        completeness_passed, crosscheck_passed, failure_reasons = validate_observed_run_invariants(
            run=baseline_run,
            expected_config_hash=expected_base_config_hash,
            expected_session_id=baseline_run.session_id,
            now_dt=now_dt,
            max_age_seconds=max_age_seconds,
            shot_context=self.context,
            is_comparison=False,
        )

        terminal_status: Literal["VERIFIED", "NOT_VERIFIED", "INCONCLUSIVE"] = (
            "VERIFIED" if (completeness_passed and crosscheck_passed) else "INCONCLUSIVE"
        )

        return VerificationResult(
            terminal_status=terminal_status,
            completeness_passed=completeness_passed,
            crosscheck_passed=crosscheck_passed,
            thresholds_passed=True,
            dialogue_coverage_passed=True,
            constraints_passed=True,
            baseline_run_id=baseline_run.run_id,
            comparison_run_id="",
            evidence_hashes={
                "baseline_evidence_hash": canonical_hash(baseline_run.model_dump(mode="json")),
            },
            failure_reasons=failure_reasons,
            details={"baseline_completeness_passed": completeness_passed},
        )

    def verify_run(
        self,
        baseline_run: ObservedRun,
        comparison_run: ObservedRun,
        approved_plan: CandidatePlan,
        confirmed_constraints: list[Constraint],
        expected_config_hash: str | None = None,
        now: datetime | None = None,
        max_age_seconds: float = 1800.0,
    ) -> VerificationResult:
        """Run all deterministic verification passes against comparison evidence.

        Enforces:
        - Unconditional comparison.config_hash == expected_config_hash
        - Full baseline AND comparison grid, finiteness, manifest, and crosscheck validation
        - Accurate UTC age bounds with injected now
        - Half-open interval endpoint weighting (no extra 100ms on duration totals)
        - Full critical mic dropout and clipping evaluation
        - Strict fail-closed creative constraint compliance
        """
        failure_reasons: list[str] = []
        details: dict[str, Any] = {}
        now_dt = now or datetime.now(UTC)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=UTC)

        inconclusive = False

        # Check distinct run IDs
        if baseline_run.run_id == comparison_run.run_id:
            inconclusive = True
            failure_reasons.append(
                f"Comparison run ID matches baseline run ID "
                f"('{baseline_run.run_id}'); distinct runs required"
            )

        # Check session ID equality
        if baseline_run.session_id != comparison_run.session_id:
            inconclusive = True
            failure_reasons.append(
                f"Session ID mismatch between baseline ('{baseline_run.session_id}') "
                f"and comparison ('{comparison_run.session_id}')"
            )

        # 1. Authoritative Expected Config Hash (Finding 1: Unconditional equality, NO fallback)
        if not expected_config_hash:
            inconclusive = True
            failure_reasons.append(
                "Authoritative expected_config_hash is required; fallback "
                "derivation from baseline is forbidden."
            )
            target_expected_hash = ""
        else:
            target_expected_hash = expected_config_hash

        no_action_control = bool(approved_plan.actions) and all(
            a.action_type == "NO_ACTION" and not a.parameters for a in approved_plan.actions
        )
        if approved_plan.action_hash != actions_hash(approved_plan.actions):
            inconclusive = True
            failure_reasons.append("Approved action hash does not match its action list")
        if target_expected_hash == baseline_run.config_hash and not no_action_control:
            inconclusive = True
            failure_reasons.append("Comparison must use a different applied configuration")

        # 2. Validate Baseline Run Invariants (Finding 4: An incomplete baseline cannot be trusted)
        base_complete, base_crosscheck, base_reasons = validate_observed_run_invariants(
            run=baseline_run,
            expected_config_hash=approved_plan.base_config_hash,
            expected_session_id=baseline_run.session_id,
            now_dt=now_dt,
            max_age_seconds=max_age_seconds,
            shot_context=self.context,
            is_comparison=False,
        )
        if not base_complete or not base_crosscheck:
            inconclusive = True
            failure_reasons.extend(base_reasons)

        # 3. Validate Comparison Run Invariants (Finding 1, 2, 3, 4, 7)
        comp_complete, comp_crosscheck, comp_reasons = validate_observed_run_invariants(
            run=comparison_run,
            expected_config_hash=target_expected_hash,
            expected_session_id=baseline_run.session_id,
            now_dt=now_dt,
            max_age_seconds=max_age_seconds,
            shot_context=self.context,
            is_comparison=True,
        )
        if not comp_complete or not comp_crosscheck:
            inconclusive = True
            failure_reasons.extend(comp_reasons)

        # 4. Cross-manifest Commitment Equality (Finding 3: Same fault realization commitment
        # reused)
        if baseline_run.manifest and comparison_run.manifest:
            if comparison_run.manifest.source_audio_hash != baseline_run.manifest.source_audio_hash:
                inconclusive = True
                failure_reasons.append(
                    "Source audio hash mismatch between baseline and comparison manifests"
                )

            if (
                comparison_run.manifest.scenario_path_hash
                != baseline_run.manifest.scenario_path_hash
            ):
                inconclusive = True
                failure_reasons.append(
                    "Scenario path hash mismatch between baseline and comparison manifests"
                )

            if (
                comparison_run.manifest.fault_commitment_hash
                != baseline_run.manifest.fault_commitment_hash
            ):
                inconclusive = True
                failure_reasons.append(
                    "Fault commitment hash mismatch between baseline and comparison manifests"
                )

            if (comparison_run.manifest.scenario_id, comparison_run.manifest.scenario_version) != (
                baseline_run.manifest.scenario_id,
                baseline_run.manifest.scenario_version,
            ):
                inconclusive = True
                failure_reasons.append(
                    "Scenario ID mismatch between baseline and comparison manifests"
                )

        completeness_passed = base_complete and comp_complete and not inconclusive
        crosscheck_passed = base_crosscheck and comp_crosscheck and not inconclusive

        details["completeness_passed"] = completeness_passed
        details["crosscheck_passed"] = crosscheck_passed

        # --- 5. Receiver Threshold Evaluation (Finding 5: Half-open interval duration weights) ---
        thresholds_passed = True
        for mic_id in self.context.mic_ids:
            mic_samples = [s for s in comparison_run.samples if s.mic_id == mic_id]
            if not mic_samples:
                continue

            min_quality = min((s.quality for s in mic_samples), default=0.0)
            # Sample 12000 is boundary only: sum duration strictly over half-open [0, 12000)
            total_dropouts = sum(
                100 for s in mic_samples if s.offset_ms < self.context.duration_ms and s.is_dropout
            )
            total_clipping = sum(
                100 for s in mic_samples if s.offset_ms < self.context.duration_ms and s.is_clipped
            )

            if min_quality < 70.0:
                thresholds_passed = False
                failure_reasons.append(
                    f"Mic '{mic_id}' minimum quality {min_quality:.1f} below threshold 70.0"
                )
            if total_dropouts > 100:
                thresholds_passed = False
                failure_reasons.append(
                    f"Mic '{mic_id}' total dropout {total_dropouts}ms exceeded 100ms"
                )
            if total_clipping > 0:
                thresholds_passed = False
                failure_reasons.append(
                    f"Mic '{mic_id}' clipping detected ({total_clipping}ms); receiver check failed"
                )

        details["thresholds_passed"] = thresholds_passed

        # --- 6. Critical-line Dialogue Coverage Pass (Finding 5: Check all critical mic
        # dropouts/clipping) ---
        crit_start = self.context.critical_line_start_ms
        crit_end = self.context.critical_line_end_ms

        # Only an explicitly approved routing action can change the selected source.
        # Receiver samples are never rewritten. Availability is derived from the
        # same complete cloud-observed grid, not a configured or imagined backup.
        backup_sources: dict[str, str] = {}
        for action in approved_plan.actions:
            if action.action_type != "BOOM_COVERAGE":
                continue
            source = action.parameters.get("source_mic")
            if (
                set(action.parameters) != {"source_mic"}
                or not isinstance(source, str)
                or source not in self.context.available_backup_sources.get(action.mic_id, [])
                or action.mic_id in backup_sources
            ):
                inconclusive = True
                failure_reasons.append("Approved backup routing is invalid or duplicated")
                continue
            backup_sources[action.mic_id] = source

        critical_offsets = set(range(crit_start, crit_end, self.context.sample_period_ms))
        selected_sources: dict[str, str] = {}
        uncovered_by_mic: dict[str, int] = {}
        dialogue_coverage_passed = True
        for mic_id in self.context.mic_ids:
            source = backup_sources.get(mic_id, mic_id)
            selected_sources[mic_id] = source
            source_samples = {
                sample.offset_ms: sample
                for sample in comparison_run.samples
                if sample.mic_id == source and crit_start <= sample.offset_ms < crit_end
            }
            uncovered = [
                offset
                for offset in critical_offsets
                if offset not in source_samples
                or source_samples[offset].is_dropout
                or source_samples[offset].is_clipped
                or source_samples[offset].quality < 70.0
            ]
            uncovered_by_mic[mic_id] = len(uncovered) * self.context.sample_period_ms
            if uncovered:
                dialogue_coverage_passed = False
                if source == mic_id:
                    failure_reasons.append(
                        f"Mic '{mic_id}' exhibited dropout or clipping during critical "
                        "dialogue interval or did not meet clean-signal threshold"
                    )
                else:
                    failure_reasons.append(
                        f"Backup source '{source}' did not cover dialogue for '{mic_id}'"
                    )
        if not dialogue_coverage_passed:
            failure_reasons.append(
                "Critical dialogue is not fully covered by clean observed sources"
            )
        details["selected_dialogue_sources"] = selected_sources
        details["uncovered_dialogue_ms"] = uncovered_by_mic
        details["dialogue_coverage_passed"] = dialogue_coverage_passed
        details["backup_coverage_used"] = bool(backup_sources)

        # --- 7. Exact typed creative constraints; shared with approval semantics. ---
        constraints_passed = True
        for c in confirmed_constraints:
            allowed_parameters = {
                "CHANNEL_EXCLUSION": {"excluded_channel"},
                "RIG_LOCK": set(),
                "ANTENNA_LOCK": {"locked_antenna"},
                "BOOM_EXCLUSION": set(),
            }.get(c.kind)
            if (
                not c.confirmed
                or allowed_parameters is None
                or set(c.parameters) != allowed_parameters
                or (c.target_mic is not None and c.target_mic not in self.context.mic_ids)
            ):
                constraints_passed = False
                failure_reasons.append(f"Unsupported or unconfirmed constraint '{c.constraint_id}'")
                continue
            if c.kind == "CHANNEL_EXCLUSION":
                excluded_ch = c.parameters["excluded_channel"]
                if type(excluded_ch) is not int:
                    constraints_passed = False
                    failure_reasons.append(f"Constraint '{c.constraint_id}' has invalid channel")
                elif any(
                    a.action_type == "CHANNEL_SWITCH"
                    and c.target_mic in (None, a.mic_id)
                    and a.parameters.get("channel") == excluded_ch
                    for a in approved_plan.actions
                ):
                    constraints_passed = False
                    failure_reasons.append(
                        f"Action violates constraint: channel {excluded_ch} is excluded"
                    )
            elif c.kind == "RIG_LOCK":
                if c.target_mic is None or any(
                    a.mic_id == c.target_mic and a.action_type not in ("NO_ACTION", "BOOM_COVERAGE")
                    for a in approved_plan.actions
                ):
                    constraints_passed = False
                    failure_reasons.append(
                        f"Action violates constraint: rig on mic '{c.target_mic}' is locked "
                        "or target is missing"
                    )
            elif c.kind == "ANTENNA_LOCK":
                locked = c.parameters["locked_antenna"]
                if locked not in self.context.available_antennas or any(
                    a.action_type == "ANTENNA_SWITCH" and a.parameters.get("antenna") != locked
                    for a in approved_plan.actions
                ):
                    constraints_passed = False
                    failure_reasons.append("Action violates locked antenna routing")
            elif c.kind == "BOOM_EXCLUSION":
                if any(
                    a.action_type == "BOOM_COVERAGE" and c.target_mic in (None, a.mic_id)
                    for a in approved_plan.actions
                ):
                    constraints_passed = False
                    failure_reasons.append("Action violates backup source exclusion")
        details["constraints_passed"] = constraints_passed
        if backup_sources and dialogue_coverage_passed and not thresholds_passed:
            details["coverage_summary"] = "Dialogue covered; receiver issue remains"
        elif dialogue_coverage_passed:
            details["coverage_summary"] = "Dialogue covered by clean observed sources"
        else:
            details["coverage_summary"] = "Dialogue coverage incomplete"

        # --- 8. Baseline vs Comparison Improvement Check ---
        base_lead_dropouts = sum(
            100
            for s in baseline_run.samples
            if s.mic_id == "mic_1" and crit_start <= s.offset_ms < crit_end and s.is_dropout
        )
        comp_lead_dropouts = sum(
            100
            for s in comparison_run.samples
            if s.mic_id == "mic_1" and crit_start <= s.offset_ms < crit_end and s.is_dropout
        )
        if base_lead_dropouts > 0 and comp_lead_dropouts >= base_lead_dropouts:
            thresholds_passed = False
            failure_reasons.append("Comparison run failed to improve dropouts over baseline")

        details["thresholds_passed"] = thresholds_passed
        # --- 9. Terminal Status Determination ---
        terminal_status: Literal["VERIFIED", "NOT_VERIFIED", "INCONCLUSIVE"]
        if inconclusive or not completeness_passed or not crosscheck_passed:
            terminal_status = "INCONCLUSIVE"
        elif thresholds_passed and dialogue_coverage_passed and constraints_passed:
            terminal_status = "VERIFIED"
        else:
            terminal_status = "NOT_VERIFIED"

        return VerificationResult(
            terminal_status=terminal_status,
            completeness_passed=completeness_passed,
            crosscheck_passed=crosscheck_passed,
            thresholds_passed=thresholds_passed,
            dialogue_coverage_passed=dialogue_coverage_passed,
            constraints_passed=constraints_passed,
            baseline_run_id=baseline_run.run_id,
            comparison_run_id=comparison_run.run_id,
            evidence_hashes={
                "baseline_evidence_hash": canonical_hash(baseline_run.model_dump(mode="json")),
                "comparison_evidence_hash": canonical_hash(comparison_run.model_dump(mode="json")),
            },
            failure_reasons=failure_reasons,
            details=details,
        )
