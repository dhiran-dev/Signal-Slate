"""Deterministic rehearsal simulator for Signal Slate.

Generates exactly 484 samples (121 samples x 4 mics @ 100ms over 12s).
Simulates RF propagation, interference families, and receiver metrics.
"""

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

from signal_slate.domain.models import (
    EvidenceContext,
    EvidenceManifest,
    MicSample,
    PerSecondMetric,
    RunConfig,
    ShotContext,
)


def _deterministic_seed_offset(mic_id: str, seed: int) -> int:
    """Compute a stable offset independent of Python hash randomization."""
    h = hashlib.sha256(f"{mic_id}:{seed}".encode()).digest()
    return int.from_bytes(h[:4], "big")


class SimulatorEngine:
    def __init__(
        self, context: ShotContext | None = None, fault_family: str = "channel_interference"
    ) -> None:
        if fault_family not in {
            "channel_interference",
            "antenna_shadow",
            "audio_clipping",
            "healthy",
        }:
            raise ValueError("Unknown private fault family")
        self.context = context or ShotContext()
        # Private simulator input: never serialized into observations or model context.
        self._fault_family = fault_family

    def create_prepublication_manifest(
        self,
        run_id: str,
        session_id: str,
        config: RunConfig,
        evidence_context: EvidenceContext,
        created_at_rfc3339: str | None = None,
    ) -> EvidenceManifest:
        """Generate an immutable pre-publication manifest before telemetry is pushed."""
        return evidence_context.create_manifest(
            run_id=run_id,
            config_hash=config.config_hash,
            created_at_rfc3339=created_at_rfc3339,
            sample_count=484,
            metric_count=48,
        )

    def run_rehearsal(
        self,
        config: RunConfig,
        seed: int = 42,
        start_time_sec: float | None = None,
        session_id: str = "",
        run_id: str = "",
    ) -> tuple[list[MicSample], list[PerSecondMetric], list[dict[str, Any]]]:
        """Execute deterministic simulation for 4 microphones over 12,000 ms.

        Returns:
            samples: Exactly 484 MicSample objects (121 offsets x 4 mics) with provenance.
            metrics: 48 PerSecondMetric objects (12 seconds x 4 mics) with provenance.
            events: Telemetry lifecycle events (dropout start/end, run_completed).
        """
        start_sec = 0.0 if start_time_sec is None else start_time_sec
        samples: list[MicSample] = []
        events: list[dict[str, Any]] = []

        offsets = list(
            range(
                0,
                self.context.duration_ms + self.context.sample_period_ms,
                self.context.sample_period_ms,
            )
        )
        assert len(offsets) == 121, f"Expected 121 offsets, got {len(offsets)}"

        active_dropouts: dict[str, int | None] = {m: None for m in self.context.mic_ids}

        for offset in offsets:
            sample_ts = datetime.fromtimestamp(start_sec + offset / 1000.0, tz=UTC).isoformat()
            for mic_id in self.context.mic_ids:
                sample = self._generate_sample(
                    mic_id=mic_id,
                    offset_ms=offset,
                    config=config,
                    seed=seed,
                    timestamp_rfc3339=sample_ts,
                    run_id=run_id,
                    session_id=session_id,
                )
                samples.append(sample)

                # Track dropout events
                if sample.is_dropout and active_dropouts[mic_id] is None:
                    active_dropouts[mic_id] = offset
                    events.append(
                        {
                            "event": "dropout_start",
                            "mic_id": mic_id,
                            "offset_ms": offset,
                            "run_id": run_id,
                            "session_id": session_id,
                        }
                    )
                elif not sample.is_dropout and active_dropouts[mic_id] is not None:
                    start_ms = active_dropouts[mic_id]
                    assert start_ms is not None
                    events.append(
                        {
                            "event": "dropout_end",
                            "mic_id": mic_id,
                            "start_offset_ms": start_ms,
                            "end_offset_ms": offset,
                            "duration_ms": offset - start_ms,
                            "run_id": run_id,
                            "session_id": session_id,
                        }
                    )
                    active_dropouts[mic_id] = None

        # Close any open dropouts at the boundary
        for mic_id, start_off in active_dropouts.items():
            if start_off is not None:
                events.append(
                    {
                        "event": "dropout_end",
                        "mic_id": mic_id,
                        "start_offset_ms": start_off,
                        "end_offset_ms": self.context.duration_ms,
                        "duration_ms": self.context.duration_ms - start_off,
                        "run_id": run_id,
                        "session_id": session_id,
                    }
                )

        assert len(samples) == 484, f"Expected exactly 484 samples, got {len(samples)}"

        # Compute per-second metrics
        metrics = self._compute_per_second_metrics(
            samples=samples,
            start_time_sec=start_sec,
            run_id=run_id,
            session_id=session_id,
            config_hash=config.config_hash,
        )
        assert len(metrics) == 48, f"Expected 48 per-second metrics, got {len(metrics)}"

        # Add completion marker with exact metadata matching prepublication manifest
        events.append(
            {
                "event": "run_completed",
                "samples_count": len(samples),
                "metrics_count": len(metrics),
                "status": "completed",
                "run_id": run_id,
                "session_id": session_id,
                "config_hash": config.config_hash,
            }
        )

        return samples, metrics, events

    def _generate_sample(
        self,
        mic_id: str,
        offset_ms: int,
        config: RunConfig,
        seed: int,
        timestamp_rfc3339: str = "",
        run_id: str = "",
        session_id: str = "",
    ) -> MicSample:
        channel = config.channel_assignments.get(
            mic_id,
            10
            if mic_id == "mic_1"
            else (20 if mic_id == "mic_2" else (30 if mic_id == "mic_3" else 40)),
        )

        # Base clean battery and signal curve
        base_battery = 98.0 - (offset_ms / 12000.0) * 0.5
        t_sec = offset_ms / 1000.0
        det_val = _deterministic_seed_offset(mic_id, seed)
        phase = (det_val % 1000) / 100.0

        valid_channels = self.context.available_channels.get(mic_id, [])
        critical = (
            self.context.critical_line_start_ms <= offset_ms < self.context.critical_line_end_ms
        )
        quality = 92.0 + 3.0 * math.sin(t_sec + phase)
        link_margin = 18.5 + 1.5 * math.cos(t_sec + phase)
        is_dropout = False
        is_clipped = False

        if (
            channel not in valid_channels
            or config.antenna_selection not in self.context.available_antennas
        ):
            quality, link_margin, is_dropout = 0.0, -30.0, True
        elif mic_id == "mic_1":
            if self._fault_family == "channel_interference":
                # Changing antenna cannot remove energy from the occupied channel.
                if channel == 10 and critical:
                    quality = 18.0 + 5.0 * math.sin(t_sec * 4.0 + phase)
                    link_margin = -14.0 + 2.0 * math.cos(t_sec * 3.0 + phase)
                    is_dropout = True
                elif channel == 11:
                    quality = 74.0 + 4.0 * math.sin(t_sec * 2.0 + phase)
                    link_margin = 8.0 + 2.0 * math.cos(t_sec + phase)
            elif self._fault_family == "antenna_shadow":
                # A spatial null lasts longer than the spoken phrase. Retuning cannot
                # change this path. The alternate antenna samples a different path.
                shadow = (
                    max(0, self.context.critical_line_start_ms - 1000)
                    <= offset_ms
                    < min(self.context.duration_ms, self.context.critical_line_end_ms + 1000)
                )
                if config.antenna_selection == "A" and shadow:
                    quality = 39.0 + 4.0 * math.sin(t_sec + phase)
                    link_margin = -5.0 + 1.0 * math.cos(t_sec + phase)
                    is_dropout = critical
            elif self._fault_family == "audio_clipping":
                # Saturation occurs before the RF link. Neither retuning nor antenna
                # selection repairs clipped source audio. Backup routing is handled
                # separately by dialogue coverage, never by changing receiver health.
                is_clipped = critical

        # Receiver measurements deliberately do not depend on backup_sources.
        return MicSample(
            offset_ms=offset_ms,
            mic_id=mic_id,
            quality=round(max(0.0, min(100.0, quality)), 1),
            link_margin_db=round(link_margin, 1),
            battery_pct=round(base_battery, 1),
            is_clipped=is_clipped,
            is_dropout=is_dropout,
            timestamp_rfc3339=timestamp_rfc3339,
            run_id=run_id,
            session_id=session_id,
            config_hash=config.config_hash,
        )

    def _compute_per_second_metrics(
        self,
        samples: list[MicSample],
        start_time_sec: float | None = None,
        run_id: str = "",
        session_id: str = "",
        config_hash: str = "",
    ) -> list[PerSecondMetric]:
        """Aggregate 100ms samples into 12 per-second summaries per mic (48 total)."""
        metrics: list[PerSecondMetric] = []

        for second in range(12):
            sec_start = second * 1000
            sec_end = (second + 1) * 1000
            sec_ts = (
                datetime.fromtimestamp(start_time_sec + second, tz=UTC).isoformat()
                if start_time_sec is not None
                else ""
            )

            for mic_id in self.context.mic_ids:
                sec_samples = [
                    s for s in samples if s.mic_id == mic_id and sec_start <= s.offset_ms < sec_end
                ]
                if not sec_samples:
                    continue

                if second == 11:
                    boundary_sample = [
                        s for s in samples if s.mic_id == mic_id and s.offset_ms == 12000
                    ]
                    eval_samples = sec_samples + boundary_sample
                else:
                    eval_samples = sec_samples

                min_quality = min(s.quality for s in eval_samples)
                min_link = min(s.link_margin_db for s in eval_samples)
                min_batt = min(s.battery_pct for s in eval_samples)
                dropout_ms = sum(100 for s in sec_samples if s.is_dropout)
                clipping_ms = sum(100 for s in sec_samples if s.is_clipped)

                sample_run_id = run_id or sec_samples[0].run_id
                sample_session_id = session_id or sec_samples[0].session_id
                sample_config_hash = config_hash or sec_samples[0].config_hash
                metric_ts = sec_ts or sec_samples[0].timestamp_rfc3339

                metrics.append(
                    PerSecondMetric(
                        second=second,
                        mic_id=mic_id,
                        min_quality=round(min_quality, 1),
                        min_link_margin_db=round(min_link, 1),
                        min_battery_pct=round(min_batt, 1),
                        clipping_duration_ms=clipping_ms,
                        dropout_duration_ms=dropout_ms,
                        timestamp_rfc3339=metric_ts,
                        run_id=sample_run_id,
                        session_id=sample_session_id,
                        config_hash=sample_config_hash,
                    )
                )

        return metrics
