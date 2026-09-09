"""Telemetry publisher for Signal Slate to Grafana Cloud.

Publishes:
1. 100ms observations and events to Loki (/loki/api/v1/push) as structured JSON.
2. Per-second metrics to OTLP Gateway (/otlp/v1/metrics) as standard OTLP JSON.

CRITICAL HYGIENE: Credentials loaded securely from ~/.config/signal-slate/grafana.env.
Tokens are NEVER printed or logged.
"""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from signal_slate.domain.models import EvidenceManifest, MicSample, PerSecondMetric


class TelemetryPublishError(Exception):
    """Raised when telemetry publication to Grafana Cloud fails."""


class GrafanaTelemetryPublisher:
    def __init__(self, env_path: Path | None = None) -> None:
        path = env_path or (Path.home() / ".config" / "signal-slate" / "grafana.env")
        env_vals = dotenv_values(path) if path.is_file() else {}

        self.write_token: str = str(
            os.environ.get("GRAFANA_TELEMETRY_WRITE_TOKEN")
            or env_vals.get("GRAFANA_TELEMETRY_WRITE_TOKEN")
            or ""
        )
        self.stack_id: str = str(
            os.environ.get("GRAFANA_STACK_ID") or env_vals.get("GRAFANA_STACK_ID") or "1822585"
        )
        endpoint: str = str(
            os.environ.get("GRAFANA_OTLP_ENDPOINT")
            or env_vals.get("GRAFANA_OTLP_ENDPOINT")
            or "https://otlp-gateway-prod-ap-south-1.grafana.net/otlp"
        )
        self.otlp_endpoint: str = endpoint
        if not endpoint.endswith("/v1/metrics"):
            self.otlp_metrics_url: str = f"{endpoint.rstrip('/')}/v1/metrics"
        else:
            self.otlp_metrics_url = endpoint

        self.loki_push_url: str = str(
            os.environ.get("GRAFANA_LOKI_PUSH_URL")
            or env_vals.get("GRAFANA_LOKI_PUSH_URL")
            or "https://logs-prod-028.grafana.net/loki/api/v1/push"
        )
        self.loki_tenant_id: str = str(
            os.environ.get("GRAFANA_LOGS_TENANT_ID")
            or env_vals.get("GRAFANA_LOGS_TENANT_ID")
            or "1780372"
        )

    def publish_run(
        self,
        run_id: str,
        session_id: str,
        config_hash: str,
        samples: list[MicSample],
        metrics: list[PerSecondMetric],
        events: list[dict[str, Any]],
        base_timestamp_sec: float | None = None,
        manifest: EvidenceManifest | None = None,
        simulate_missing_final_sample: bool = False,
        simulate_omit_completion_marker: bool = False,
        simulate_publish_failure: bool = False,
    ) -> dict[str, Any]:
        """Publish complete run telemetry to Loki and OTLP Gateway.

        Never sends future timestamps; timestamps end at the current time or base_timestamp_sec.
        Validates against immutable prepublication manifest when provided.
        """
        if simulate_publish_failure:
            raise TelemetryPublishError("Simulated publication failure for negative testing")

        if not self.write_token:
            raise TelemetryPublishError(
                "Grafana telemetry write token is missing from environment/config"
            )

        # Set end time to now (or base_timestamp_sec), starting 12 seconds prior
        end_time = base_timestamp_sec or time.time()
        start_time = end_time - 12.0

        pushed_samples = samples
        if simulate_missing_final_sample and pushed_samples:
            # Omit exactly the single last sample (sample 484, one pair only)
            pushed_samples = pushed_samples[:-1]

        if manifest:
            if not simulate_missing_final_sample and len(pushed_samples) != manifest.sample_count:
                raise TelemetryPublishError(
                    f"Sample count {len(pushed_samples)} does not match "
                    f"manifest count {manifest.sample_count}"
                )
            if len(metrics) != manifest.metric_count:
                raise TelemetryPublishError(
                    f"Metric count {len(metrics)} does not match "
                    f"manifest count {manifest.metric_count}"
                )

        sample_events = [e for e in events if e.get("event") != "run_completed"]
        completion_events = [e for e in events if e.get("event") == "run_completed"]

        # 1. Publish 100ms observations and normal events to Loki (WITHOUT completion marker)
        loki_status = self._push_to_loki(
            run_id=run_id,
            session_id=session_id,
            config_hash=config_hash,
            samples=pushed_samples,
            events=sample_events,
            start_time_sec=start_time,
        )

        # 2. Publish all 5 per-second metric families to OTLP Gateway
        otlp_status = self._push_to_otlp(
            run_id=run_id,
            session_id=session_id,
            config_hash=config_hash,
            metrics=metrics,
            start_time_sec=start_time,
        )

        # 3. Publish completion marker to Loki ONLY after Loki samples AND OTLP metrics accepted
        if completion_events and not simulate_omit_completion_marker:
            self._push_to_loki(
                run_id=run_id,
                session_id=session_id,
                config_hash=config_hash,
                samples=[],
                events=completion_events,
                start_time_sec=start_time,
            )

        return {
            "run_id": run_id,
            "session_id": session_id,
            "config_hash": config_hash,
            "samples_count": len(pushed_samples),
            "metrics_count": len(metrics),
            "loki_status_code": loki_status,
            "otlp_status_code": otlp_status,
            "start_time_sec": start_time,
            "end_time_sec": end_time,
        }

    def _push_to_loki(
        self,
        run_id: str,
        session_id: str,
        config_hash: str,
        samples: list[MicSample],
        events: list[dict[str, Any]],
        start_time_sec: float,
    ) -> int:
        """Push structured JSON logs to Loki endpoint via HTTP 204."""
        streams = []

        # Group samples by mic_id
        mics = sorted(list({s.mic_id for s in samples}))
        for mic_id in mics:
            mic_samples = [s for s in samples if s.mic_id == mic_id]
            values = []
            for s in mic_samples:
                sample_time_ns = int((start_time_sec + s.offset_ms / 1000.0) * 1e9)
                sample_ts_iso = (
                    datetime.fromtimestamp(
                        start_time_sec + s.offset_ms / 1000.0, tz=UTC
                    ).isoformat()
                    if start_time_sec
                    else (s.timestamp_rfc3339 or datetime.now(UTC).isoformat())
                )
                log_entry = {
                    "event": "sample",
                    "run_id": run_id or s.run_id,
                    "session_id": session_id or s.session_id,
                    "mic_id": mic_id,
                    "offset_ms": s.offset_ms,
                    "timestamp_rfc3339": sample_ts_iso,
                    "quality": s.quality,
                    "link_margin_db": s.link_margin_db,
                    "battery_pct": s.battery_pct,
                    "is_dropout": s.is_dropout,
                    "is_clipped": s.is_clipped,
                    "config_hash": config_hash or s.config_hash,
                }
                values.append([str(sample_time_ns), json.dumps(log_entry, separators=(",", ":"))])

            if values:
                streams.append(
                    {
                        "stream": {
                            "app": "signal-slate",
                            "run_id": run_id,
                            "session_id": session_id,
                            "mic_id": mic_id,
                        },
                        "values": values,
                    }
                )

        # Lifecycle events stream
        event_values = []
        for e in events:
            off_ms = e.get("offset_ms", 12000)
            event_time_ns = int((start_time_sec + off_ms / 1000.0) * 1e9)
            event_ts_iso = (
                datetime.fromtimestamp(start_time_sec + off_ms / 1000.0, tz=UTC).isoformat()
                if start_time_sec
                else datetime.now(UTC).isoformat()
            )
            e_payload = {
                "run_id": run_id,
                "session_id": session_id,
                "config_hash": config_hash,
                "timestamp_rfc3339": event_ts_iso,
                **e,
            }
            event_values.append([str(event_time_ns), json.dumps(e_payload, separators=(",", ":"))])

        if event_values:
            streams.append(
                {
                    "stream": {
                        "app": "signal-slate",
                        "run_id": run_id,
                        "session_id": session_id,
                        "event_type": "lifecycle",
                    },
                    "values": event_values,
                }
            )

        payload = {"streams": streams}

        auth = (self.loki_tenant_id, self.write_token)
        headers = {"Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(self.loki_push_url, json=payload, auth=auth, headers=headers)
                if resp.status_code not in (200, 204):
                    raise TelemetryPublishError(
                        f"Loki push failed with HTTP status {resp.status_code}: {resp.text}"
                    )
                return resp.status_code
        except Exception as exc:
            if isinstance(exc, TelemetryPublishError):
                raise
            raise TelemetryPublishError(
                f"Network error pushing to Loki: {type(exc).__name__}"
            ) from exc

    def _push_to_otlp(
        self,
        run_id: str,
        session_id: str,
        config_hash: str,
        metrics: list[PerSecondMetric],
        start_time_sec: float,
    ) -> int:
        """Push all 5 per-second metric families to Grafana Cloud OTLP Gateway."""
        gauge_data_points_quality = []
        gauge_data_points_link = []
        gauge_data_points_battery = []
        gauge_data_points_clipping = []
        gauge_data_points_dropout = []

        for m in metrics:
            sec_time_ns = int((start_time_sec + m.second) * 1e9)
            metric_ts_iso = (
                datetime.fromtimestamp(start_time_sec + m.second, tz=UTC).isoformat()
                if start_time_sec
                else (m.timestamp_rfc3339 or datetime.now(UTC).isoformat())
            )
            attrs = [
                {"key": "mic_id", "value": {"stringValue": m.mic_id}},
                {"key": "second", "value": {"intValue": str(m.second)}},
                {"key": "run_id", "value": {"stringValue": run_id or m.run_id}},
                {"key": "session_id", "value": {"stringValue": session_id or m.session_id}},
                {"key": "config_hash", "value": {"stringValue": config_hash or m.config_hash}},
                {"key": "timestamp_rfc3339", "value": {"stringValue": metric_ts_iso}},
            ]

            gauge_data_points_quality.append(
                {
                    "asDouble": m.min_quality,
                    "timeUnixNano": str(sec_time_ns),
                    "attributes": attrs,
                }
            )
            gauge_data_points_link.append(
                {
                    "asDouble": m.min_link_margin_db,
                    "timeUnixNano": str(sec_time_ns),
                    "attributes": attrs,
                }
            )
            gauge_data_points_battery.append(
                {
                    "asDouble": m.min_battery_pct,
                    "timeUnixNano": str(sec_time_ns),
                    "attributes": attrs,
                }
            )
            gauge_data_points_clipping.append(
                {
                    "asInt": str(m.clipping_duration_ms),
                    "timeUnixNano": str(sec_time_ns),
                    "attributes": attrs,
                }
            )
            gauge_data_points_dropout.append(
                {
                    "asInt": str(m.dropout_duration_ms),
                    "timeUnixNano": str(sec_time_ns),
                    "attributes": attrs,
                }
            )

        otlp_payload = {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "signal-slate"}},
                            {"key": "run_id", "value": {"stringValue": run_id}},
                            {"key": "session_id", "value": {"stringValue": session_id}},
                            {"key": "config_hash", "value": {"stringValue": config_hash}},
                        ]
                    },
                    "scopeMetrics": [
                        {
                            "scope": {"name": "signal-slate.simulator"},
                            "metrics": [
                                {
                                    "name": "signal_slate_receiver_quality",
                                    "description": "Per-second minimum receiver quality (0-100)",
                                    "gauge": {"dataPoints": gauge_data_points_quality},
                                },
                                {
                                    "name": "signal_slate_link_margin_db",
                                    "description": "Per-second minimum RF link margin in dB",
                                    "gauge": {"dataPoints": gauge_data_points_link},
                                },
                                {
                                    "name": "signal_slate_battery_pct",
                                    "description": "Per-second minimum battery percentage (0-100)",
                                    "gauge": {"dataPoints": gauge_data_points_battery},
                                },
                                {
                                    "name": "signal_slate_clipping_duration_ms",
                                    "description": "Per-second total clipping duration (ms)",
                                    "gauge": {"dataPoints": gauge_data_points_clipping},
                                },
                                {
                                    "name": "signal_slate_dropout_duration_ms",
                                    "description": "Per-second total dropout duration (ms)",
                                    "gauge": {"dataPoints": gauge_data_points_dropout},
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        auth = (self.stack_id, self.write_token)
        headers = {"Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    self.otlp_metrics_url, json=otlp_payload, auth=auth, headers=headers
                )
                if resp.status_code not in (200, 204):
                    raise TelemetryPublishError(
                        f"OTLP push failed with HTTP status {resp.status_code}: {resp.text}"
                    )
                # Parse protojson partialSuccess rejection counts
                if resp.text:
                    try:
                        resp_json = resp.json()
                        if isinstance(resp_json, dict) and "partialSuccess" in resp_json:
                            partial = resp_json["partialSuccess"]
                            if isinstance(partial, dict):
                                rej = partial.get("rejectedDataPoints", 0)
                                if int(rej) > 0:
                                    err_msg = partial.get("errorMessage", "OTLP partial rejection")
                                    raise TelemetryPublishError(
                                        f"OTLP push rejected {rej} data points: {err_msg}"
                                    )
                    except (json.JSONDecodeError, ValueError) as json_err:
                        if isinstance(json_err, TelemetryPublishError):
                            raise
                return resp.status_code
        except Exception as exc:
            if isinstance(exc, TelemetryPublishError):
                raise
            raise TelemetryPublishError(
                f"Network error pushing to OTLP: {type(exc).__name__}"
            ) from exc
