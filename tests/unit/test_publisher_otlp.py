"""Unit tests for Grafana telemetry publisher OTLP partialSuccess and completion sequence."""

from unittest.mock import MagicMock, patch

import pytest
from signal_slate.domain.models import RunConfig, ShotContext
from signal_slate.simulator.engine import SimulatorEngine
from signal_slate.telemetry.publisher import GrafanaTelemetryPublisher, TelemetryPublishError


def test_publisher_negative_missing_final_sample_omits_exactly_one_pair():
    """R9: Negative missing_final_sample removes exactly 1 pair, leaving 483 samples."""
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig()
    samples, metrics, events = engine.run_rehearsal(config, seed=42)
    assert len(samples) == 484

    publisher = GrafanaTelemetryPublisher()
    publisher.write_token = "mock_write_token"

    with (
        patch.object(publisher, "_push_to_loki", return_value=204) as mock_loki,
        patch.object(publisher, "_push_to_otlp", return_value=200),
    ):
        res = publisher.publish_run(
            run_id="run-neg-test",
            session_id="sess-test",
            config_hash="cfg_hash",
            samples=samples,
            metrics=metrics,
            events=events,
            simulate_missing_final_sample=True,
        )

        assert res["samples_count"] == 483
        first_call_samples = mock_loki.call_args_list[0].kwargs["samples"]
        assert len(first_call_samples) == 483


def test_publisher_completion_marker_sequence():
    """R9: Completion marker is published only AFTER Loki samples and OTLP metrics succeed."""
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig()
    samples, metrics, events = engine.run_rehearsal(config, seed=42)

    publisher = GrafanaTelemetryPublisher()
    publisher.write_token = "mock_write_token"

    call_order = []

    def mock_push_loki(*args, **kwargs):
        evs = kwargs.get("events", [])
        if any(e.get("event") == "run_completed" for e in evs):
            call_order.append("loki_completion_marker")
        else:
            call_order.append("loki_samples")
        return 204

    def mock_push_otlp(*args, **kwargs):
        call_order.append("otlp_metrics")
        return 200

    with (
        patch.object(publisher, "_push_to_loki", side_effect=mock_push_loki),
        patch.object(publisher, "_push_to_otlp", side_effect=mock_push_otlp),
    ):
        publisher.publish_run(
            run_id="run-seq-test",
            session_id="sess-test",
            config_hash="cfg_hash",
            samples=samples,
            metrics=metrics,
            events=events,
        )

    assert call_order == ["loki_samples", "otlp_metrics", "loki_completion_marker"]


def test_publisher_fails_closed_on_otlp_partial_success():
    """Reject OTLP partial success when any data point was rejected."""
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig()
    samples, metrics, events = engine.run_rehearsal(config, seed=42)

    publisher = GrafanaTelemetryPublisher()
    publisher.write_token = "mock_write_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        '{"partialSuccess": {"rejectedDataPoints": "3", "errorMessage": "Quota exceeded"}}'
    )
    mock_resp.json.return_value = {
        "partialSuccess": {"rejectedDataPoints": "3", "errorMessage": "Quota exceeded"}
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TelemetryPublishError, match="rejected 3 data points"):
            publisher._push_to_otlp(
                run_id="run-partial-fail",
                session_id="sess-test",
                config_hash="cfg_hash",
                metrics=metrics,
                start_time_sec=1000.0,
            )


def test_publisher_datapoint_labels_include_run_and_session():
    """R9: Data point attributes must include mic_id, second, run_id, session_id, config_hash."""
    context = ShotContext()
    engine = SimulatorEngine(context)
    config = RunConfig()
    _, metrics, _ = engine.run_rehearsal(config, seed=42)

    publisher = GrafanaTelemetryPublisher()
    publisher.write_token = "mock_write_token"

    captured_payload = {}

    def mock_post(url, json=None, **kwargs):
        nonlocal captured_payload
        captured_payload = json
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.text = "{}"
        mock_r.json.return_value = {}
        return mock_r

    with patch("httpx.Client.post", side_effect=mock_post):
        publisher._push_to_otlp(
            run_id="run-labels-test",
            session_id="sess-labels-test",
            config_hash="cfg_test_hash",
            metrics=metrics[:1],
            start_time_sec=1000.0,
        )

    dp = captured_payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["gauge"][
        "dataPoints"
    ][0]
    keys = {attr["key"]: attr["value"] for attr in dp["attributes"]}
    assert "run_id" in keys
    assert keys["run_id"]["stringValue"] == "run-labels-test"
    assert "session_id" in keys
    assert keys["session_id"]["stringValue"] == "sess-labels-test"
    assert "config_hash" in keys
    assert keys["config_hash"]["stringValue"] == "cfg_test_hash"
