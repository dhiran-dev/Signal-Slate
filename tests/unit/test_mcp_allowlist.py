"""Unit tests for Grafana MCP transport allowlist and tool boundary."""

import pytest
from signal_slate.domain.models import RunConfig, ShotContext
from signal_slate.evidence.mcp_client import (
    ALLOWLISTED_MCP_TOOLS,
    BoundedModelEvidenceWrapper,
    GrafanaMcpClient,
    McpSecurityError,
)
from signal_slate.simulator.engine import SimulatorEngine


def test_transport_allowlist_contains_only_permitted_tools():
    expected = {"list_datasources", "query_prometheus", "query_loki_logs"}
    assert ALLOWLISTED_MCP_TOOLS == expected


@pytest.mark.asyncio
async def test_calling_unauthorized_mcp_tool_raises_security_error():
    client = GrafanaMcpClient()

    # Forbidden Tempo query
    with pytest.raises(McpSecurityError, match="forbidden by transport allowlist"):
        await client.call_mcp_tool("query_tempo", {"traceId": "12345"})

    # Forbidden search tool
    with pytest.raises(McpSecurityError, match="forbidden by transport allowlist"):
        await client.call_mcp_tool("search", {"query": "test"})

    # Forbidden annotation or write tool
    with pytest.raises(McpSecurityError, match="forbidden by transport allowlist"):
        await client.call_mcp_tool("create_annotation", {})


def test_mcp_child_env_strictly_omits_write_token(monkeypatch):
    monkeypatch.setenv("GRAFANA_TELEMETRY_WRITE_TOKEN", "super_secret_write_token_12345")
    monkeypatch.setenv("GRAFANA_SERVICE_ACCOUNT_TOKEN", "safe_read_token_viewer")

    client = GrafanaMcpClient()
    params = client._get_server_params()

    assert "GRAFANA_TELEMETRY_WRITE_TOKEN" not in params.env
    assert params.env.get("GRAFANA_SERVICE_ACCOUNT_TOKEN") == "safe_read_token_viewer"


def test_bounded_model_wrapper_generates_citable_envelopes():
    context = ShotContext()
    engine = SimulatorEngine(context)
    samples, metrics, _ = engine.run_rehearsal(RunConfig(channel_assignments={"mic_1": 10}))

    from signal_slate.domain.models import ObservedRun

    run = ObservedRun(
        run_id="run-test-wrapper",
        session_id="sess-test",
        config_hash="cfg_hash",
        samples=samples,
        metrics=metrics,
        completion_marker_present=True,
        retrieved_sample_count=len(samples),
        start_time_rfc3339="2026-09-08T12:00:00Z",
        end_time_rfc3339="2026-09-08T12:00:12Z",
    )

    wrapper = BoundedModelEvidenceWrapper(run, context)

    # get_run_metrics
    ret_metrics = wrapper.get_run_metrics("run-test-wrapper", ["mic_1"], 4000, 7000)
    assert len(ret_metrics) > 0
    assert all("evidence_id" in m for m in ret_metrics)

    # get_run_events
    ret_events = wrapper.get_run_events("run-test-wrapper", ["mic_1"], 4000, 7000)
    assert len(ret_events) > 0
    assert all("evidence_id" in e for e in ret_events)
    assert all(e["evidence_id"].startswith("ev-") for e in ret_events)

    # Foreign run returns empty
    assert wrapper.get_run_metrics("foreign-run-id") == []
    assert wrapper.get_run_events("foreign-run-id") == []
