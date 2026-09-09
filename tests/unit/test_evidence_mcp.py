"""Unit tests for MCP v1.3.0 schema parsing, error fail-closed, and Prometheus querying."""

import json

import pytest
from signal_slate.evidence.mcp_client import (
    ALLOWED_CHILD_ENV_VARS,
    GrafanaMcpClient,
    McpResponseError,
    McpSecurityError,
    validate_opaque_id,
)


def test_validate_opaque_id_permits_safe_ids():
    validate_opaque_id("run-123_test.abc:1", "run_id")
    validate_opaque_id("sess_456", "session_id")
    validate_opaque_id("grafanacloud-prom", "datasource_uid")


def test_validate_opaque_id_rejects_malicious_characters():
    with pytest.raises(McpSecurityError):
        validate_opaque_id("run-123; rm -rf /", "run_id")

    with pytest.raises(McpSecurityError):
        validate_opaque_id('run" OR 1=1 --', "run_id")

    with pytest.raises(McpSecurityError):
        validate_opaque_id("", "empty_id")

    with pytest.raises(McpSecurityError):
        validate_opaque_id("a" * 150, "too_long_id")


def test_server_params_strictly_uses_env_allowlist():
    client = GrafanaMcpClient()
    params = client._get_server_params()

    # All keys in child env must be in ALLOWED_CHILD_ENV_VARS or the 2 explicit Grafana keys
    allowed_keys = ALLOWED_CHILD_ENV_VARS | {"GRAFANA_URL", "GRAFANA_SERVICE_ACCOUNT_TOKEN"}
    for k in params.env.keys():
        assert k in allowed_keys, f"Forbidden environment key leaked to child: {k}"
    assert "GRAFANA_TELEMETRY_WRITE_TOKEN" not in params.env


def test_parse_loki_entries_valid_mcp_1_3_response():
    client = GrafanaMcpClient()
    sample_payload = {
        "event": "sample",
        "run_id": "run-test-1",
        "session_id": "sess-1",
        "mic_id": "mic_1",
        "offset_ms": 100,
        "quality": 95.0,
        "link_margin_db": 18.0,
        "battery_pct": 98.0,
        "is_dropout": False,
        "is_clipped": False,
        "config_hash": "cfg1",
    }
    raw_mcp_output = json.dumps(
        {
            "data": [
                {
                    "timestamp": "2026-09-08T12:00:00.100Z",
                    "line": json.dumps(sample_payload),
                    "labels": {"app": "signal-slate", "run_id": "run-test-1"},
                }
            ],
            "metadata": {
                "resultsTruncated": False,
                "totalLines": 1,
            },
        }
    )

    entries, is_trunc, has_conflicts = client._parse_loki_entries(
        raw_mcp_output, expected_run_id="run-test-1"
    )
    assert is_trunc is False
    assert has_conflicts is False
    assert len(entries) == 1
    assert entries[0]["mic_id"] == "mic_1"


def test_parse_loki_entries_detects_truncation():
    client = GrafanaMcpClient()
    raw_output = json.dumps(
        {
            "data": [],
            "metadata": {
                "resultsTruncated": True,
            },
        }
    )
    entries, is_trunc, _ = client._parse_loki_entries(raw_output, expected_run_id="run-test-1")
    assert is_trunc is True


def test_parse_loki_entries_fails_closed_on_malformed_json():
    client = GrafanaMcpClient()
    with pytest.raises(McpResponseError, match="Failed to parse Loki MCP response"):
        client._parse_loki_entries("not a json string", expected_run_id="run-1")


def test_parse_loki_entries_detects_conflicting_duplicates():
    client = GrafanaMcpClient()
    s1 = {
        "event": "sample",
        "run_id": "run-test-1",
        "mic_id": "mic_1",
        "offset_ms": 100,
        "quality": 90.0,
        "link_margin_db": 15.0,
        "is_dropout": False,
    }
    s2_conflict = {
        "event": "sample",
        "run_id": "run-test-1",
        "mic_id": "mic_1",
        "offset_ms": 100,
        "quality": 20.0,  # Contradictory quality!
        "link_margin_db": -10.0,
        "is_dropout": True,
    }
    raw_output = json.dumps(
        {
            "data": [
                {"line": json.dumps(s1)},
                {"line": json.dumps(s2_conflict)},
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    entries, is_trunc, has_conflicts = client._parse_loki_entries(
        raw_output, expected_run_id="run-test-1"
    )
    assert has_conflicts is True
    assert len(entries) == 2


def test_parse_loki_entries_rejects_foreign_run_id():
    client = GrafanaMcpClient()
    s_foreign = {
        "event": "sample",
        "run_id": "FOREIGN_RUN_999",
        "mic_id": "mic_1",
        "offset_ms": 100,
    }
    raw_output = json.dumps(
        {
            "data": [{"line": json.dumps(s_foreign)}],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpResponseError, match="foreign run log"):
        client._parse_loki_entries(raw_output, expected_run_id="run-expected-1")


def test_parse_prometheus_metrics_genuine_schema():
    client = GrafanaMcpClient()
    raw_prom_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "88.5"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_link_margin_db",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "16.2"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_battery_pct",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "98.0"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_clipping_duration_ms",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "0"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_dropout_duration_ms",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "0"],
                },
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    metrics, envelopes, is_trunc = client._parse_prometheus_metrics(
        raw_prom_output, expected_run_id="run-prom-1", require_full_grid=False
    )
    assert is_trunc is False
    assert len(metrics) == 1
    assert metrics[0].mic_id == "mic_1"
    assert metrics[0].second == 0
    assert metrics[0].min_quality == 88.5
    assert metrics[0].min_link_margin_db == 16.2
    assert metrics[0].min_battery_pct == 98.0
    assert metrics[0].clipping_duration_ms == 0
    assert metrics[0].dropout_duration_ms == 0
    assert len(envelopes) == 5
    assert envelopes[0].source_tool == "query_prometheus"


def test_parse_prometheus_metrics_rejects_missing_metric_family():
    """Finding 7: Must fail closed if any of the 5 families is missing."""
    client = GrafanaMcpClient()
    # Provide only 4 families, omitting clipping_duration_ms
    raw_prom_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "88.5"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_link_margin_db",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "16.2"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_battery_pct",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "98.0"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_dropout_duration_ms",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "0"],
                },
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpResponseError, match="missing required metric families"):
        client._parse_prometheus_metrics(
            raw_prom_output, expected_run_id="run-prom-1", require_full_grid=False
        )


def test_parse_prometheus_metrics_rejects_missing_run_label():
    """Finding 7: Must NOT substitute requested run if run_id label is missing."""
    client = GrafanaMcpClient()
    raw_prom_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        # Missing run_id label!
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "88.5"],
                }
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpResponseError, match="missing required 'run_id' label"):
        client._parse_prometheus_metrics(raw_prom_output, expected_run_id="run-prom-1")


def test_parse_prometheus_metrics_rejects_malformed_number():
    """Finding 7: Must fail closed and not coerce malformed number to 0.0."""
    client = GrafanaMcpClient()
    raw_prom_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "not_a_float"],
                }
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpResponseError, match="Malformed non-numeric value"):
        client._parse_prometheus_metrics(raw_prom_output, expected_run_id="run-prom-1")


def test_parse_prometheus_metrics_rejects_contradictory_duplicates():
    """Finding 7: Conflicting duplicate metrics must raise McpContradictionError."""
    from signal_slate.evidence.mcp_client import McpContradictionError

    client = GrafanaMcpClient()
    raw_prom_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "88.5"],
                },
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "run-prom-1",
                        "session_id": "sess-1",
                        "config_hash": "cfg_prom",
                    },
                    "value": [1725800000.0, "45.0"],  # Different contradictory value!
                },
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpContradictionError, match="Conflicting duplicate metric"):
        client._parse_prometheus_metrics(raw_prom_output, expected_run_id="run-prom-1")


def test_parse_prometheus_metrics_rejects_foreign_run():
    client = GrafanaMcpClient()
    raw_output = json.dumps(
        {
            "data": [
                {
                    "metric": {
                        "timestamp_rfc3339": "2024-09-08T12:53:20+00:00",
                        "__name__": "signal_slate_receiver_quality",
                        "mic_id": "mic_1",
                        "second": "0",
                        "run_id": "FOREIGN_RUN_ABC",
                    },
                    "value": [1725800000.0, "85.0"],
                }
            ],
            "metadata": {"resultsTruncated": False},
        }
    )

    with pytest.raises(McpResponseError, match="foreign run metric"):
        client._parse_prometheus_metrics(raw_output, expected_run_id="run-expected-1")
