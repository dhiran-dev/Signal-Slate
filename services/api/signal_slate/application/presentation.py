"""Read-only setup summaries and run-bound Grafana links for the guided workspace."""

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from signal_slate.config import get_settings
from signal_slate.evidence.mcp_client import GrafanaMcpClient, validate_opaque_id
from signal_slate.telemetry.publisher import GrafanaTelemetryPublisher


def readiness() -> dict:
    """Report local configuration, never call providers or claim a successful connection."""
    settings = get_settings()
    enabled = os.getenv("SIGNAL_SLATE_RUNTIME_ENABLED", "true") == "true"
    explicit_adc = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    cloud_config = Path(os.getenv("CLOUDSDK_CONFIG", str(Path.home() / ".config/gcloud")))
    adc = (
        Path(explicit_adc).expanduser()
        if explicit_adc
        else cloud_config / "application_default_credentials.json"
    )
    gemini = bool(settings.google_cloud_project and settings.gemini_model and adc.is_file())
    reader, publisher = GrafanaMcpClient(), GrafanaTelemetryPublisher()
    grafana = bool(
        reader.read_token
        and publisher.write_token
        and reader.prom_uid
        and reader.loki_uid
        and reader.grafana_url
        and publisher.otlp_endpoint
        and publisher.loki_push_url
    )
    missing = []
    if not enabled:
        missing.append("Cloud checks are disabled on this server.")
    if not gemini:
        missing.append("Configure the Google project and application credentials on the server.")
    if not grafana:
        missing.append("Configure the Grafana reading and publishing credentials on the server.")
    return {
        "live_available": enabled and gemini and grafana,
        "runtime_enabled": enabled,
        "gemini": {"configured": gemini},
        "grafana": {"configured": grafana},
        "missing": missing,
    }


def evidence_links(state: dict, session_id: str) -> dict:
    """Build official Explore URLs; opening them still requires the user's Grafana login.

    https://grafana.com/docs/grafana/latest/visualizations/explore/get-started-with-explore/
    Absolute observed time bounds keep a historical report anchored to its original run.
    No API token or browser-session credential is part of a link.
    """
    result: dict = {"source": "grafana" if state.get("mode") == "live" else "preview", "links": []}
    if result["source"] != "grafana":
        return result
    reader = GrafanaMcpClient()
    url = urlsplit(reader.grafana_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        return result
    validate_opaque_id(session_id, "session_id")
    for key, label in (("baseline", "Before"), ("comparison", "After")):
        run = state.get(key)
        if not run:
            continue
        try:
            run_id = run["run_id"]
            validate_opaque_id(run_id, "run_id")
            start = datetime.fromisoformat(run["start_time_rfc3339"])
            end = datetime.fromisoformat(run["end_time_rfc3339"])
            if start.tzinfo is None or end.tzinfo is None or end < start:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        time_range = {
            "from": str(int(start.timestamp() * 1000) - 30_000),
            "to": str(int(end.timestamp() * 1000) + 30_000),
        }
        match = f'run_id="{run_id}",session_id="{session_id}"'
        panes = {}
        for pane, uid, kind, expr in (
            ("logs", reader.loki_uid, "loki", "{" + match + "} | json"),
            (
                "metrics",
                reader.prom_uid,
                "prometheus",
                "signal_slate_receiver_quality{" + match + "}",
            ),
        ):
            panes[pane] = {
                "datasource": uid,
                "queries": [
                    {
                        "refId": "A",
                        "datasource": {"uid": uid, "type": kind},
                        "expr": expr,
                        "editorMode": "code",
                        "range": True,
                    }
                ],
                "range": time_range,
            }
        query = urlencode(
            {"panes": json.dumps(panes, separators=(",", ":")), "schemaVersion": "1", "orgId": "1"}
        )
        result["links"].append(
            {"label": label, "url": f"{reader.grafana_url.rstrip('/')}/explore?{query}"}
        )
    return result
