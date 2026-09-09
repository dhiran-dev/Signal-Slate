"""Grafana MCP Client supervising official mcp-grafana==1.3.0 process.

Enforces:
1. Strict transport allowlist: list_datasources, query_prometheus, query_loki_logs ONLY.
2. Two-level tool architecture: model interacts via bounded typed wrappers only.
3. Secret isolation: passes only read token to MCP child process; never leaks secrets.
"""

import asyncio
import json
import math
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from signal_slate.domain.models import (
    EvidenceEnvelope,
    EvidenceManifest,
    MicSample,
    ObservedRun,
    PerSecondMetric,
    ShotContext,
    canonical_hash,
)

ALLOWLISTED_MCP_TOOLS = frozenset({"list_datasources", "query_prometheus", "query_loki_logs"})
REQUIRED_METRIC_FAMILIES = frozenset(
    {
        "signal_slate_receiver_quality",
        "signal_slate_link_margin_db",
        "signal_slate_battery_pct",
        "signal_slate_clipping_duration_ms",
        "signal_slate_dropout_duration_ms",
    }
)
ALLOWED_CHILD_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SYSTEMROOT",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
    }
)

OPAQUE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.:]+$")


class McpSecurityError(Exception):
    """Raised when an unauthorized MCP tool or forbidden operation is attempted."""


class McpResponseError(Exception):
    """Raised when MCP tool returns an error or invalid response schema."""


class McpTruncationError(McpResponseError):
    """Raised when MCP query results are truncated."""


class McpContradictionError(McpResponseError):
    """Raised when conflicting duplicate evidence records are retrieved."""


class McpIngestionTimeoutError(Exception):
    """Raised when fresh telemetry ingestion into Grafana Cloud exceeds backoff timeout."""


def validate_opaque_id(val: str, field_name: str) -> None:
    """Validate that an ID contains only safe alphanumeric/identifier characters."""
    if not val or not OPAQUE_ID_REGEX.match(val) or len(val) > 128:
        raise McpSecurityError(f"Invalid or unsafe {field_name}: '{val}'")


class GrafanaMcpClient:
    def __init__(self, env_path: Path | None = None) -> None:
        path = env_path or (Path.home() / ".config" / "signal-slate" / "grafana.env")
        env_vals = dotenv_values(path) if path.is_file() else {}

        self.grafana_url: str = str(
            os.environ.get("GRAFANA_URL")
            or env_vals.get("GRAFANA_URL")
            or "https://nobledolphin1238.grafana.net"
        )
        self.read_token: str = str(
            os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN")
            or env_vals.get("GRAFANA_SERVICE_ACCOUNT_TOKEN")
            or ""
        )
        self.prom_uid: str = str(
            os.environ.get("GRAFANA_PROMETHEUS_DATASOURCE_UID")
            or env_vals.get("GRAFANA_PROMETHEUS_DATASOURCE_UID")
            or "grafanacloud-prom"
        )
        self.loki_uid: str = str(
            os.environ.get("GRAFANA_LOKI_DATASOURCE_UID")
            or env_vals.get("GRAFANA_LOKI_DATASOURCE_UID")
            or "grafanacloud-logs"
        )

    def _get_server_params(self) -> StdioServerParameters:
        """Create stdio server parameters passing ONLY essential env and read credentials."""
        child_env = {k: v for k, v in os.environ.items() if k in ALLOWED_CHILD_ENV_VARS}
        child_env["GRAFANA_URL"] = self.grafana_url
        child_env["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = self.read_token
        # Strictly ensure write token is NEVER passed to MCP child
        child_env.pop("GRAFANA_TELEMETRY_WRITE_TOKEN", None)

        return StdioServerParameters(
            command="uvx",
            args=[
                "mcp-grafana==1.3.0",
                "--disable-write",
                "--disable-search",
                "--enabled-tools",
                "datasource,prometheus,loki",
                "--max-loki-log-limit",
                "1000",
                "--transport",
                "stdio",
            ],
            env=child_env,
        )

    async def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 15.0,
    ) -> str:
        """Invoke an allowlisted MCP tool through the official transport with a timeout."""
        if tool_name not in ALLOWLISTED_MCP_TOOLS:
            raise McpSecurityError(
                f"Tool '{tool_name}' is forbidden by transport allowlist. "
                f"Permitted tools: {sorted(list(ALLOWLISTED_MCP_TOOLS))}"
            )

        params = self._get_server_params()
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout_seconds)
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=timeout_seconds,
                )
                if getattr(result, "isError", False):
                    err_msg = ""
                    if result.content:
                        err_msg = getattr(result.content[0], "text", str(result.content[0]))
                    raise McpResponseError(f"MCP tool '{tool_name}' returned error: {err_msg}")
                if not result.content:
                    return ""
                return getattr(result.content[0], "text", str(result.content[0]))

    async def list_datasources(self) -> list[dict[str, Any]]:
        """List available Grafana datasources via allowlisted MCP tool."""
        res_text = await self.call_mcp_tool("list_datasources", {})
        try:
            data = json.loads(res_text)
            ds = data.get("datasources", [])
            return [d for d in ds if isinstance(d, dict)]
        except Exception:
            return []

    async def query_loki_run_logs(
        self,
        run_id: str,
        start_rfc3339: str,
        end_rfc3339: str,
        limit: int = 1000,
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        """Execute parameterized LogQL query against Loki via allowlisted MCP tool.

        Returns: (entries, is_truncated, has_conflicting_duplicates)
        """
        validate_opaque_id(run_id, "run_id")
        validate_opaque_id(self.loki_uid, "loki_datasource_uid")
        bounded_limit = min(max(1, limit), 1000)

        logql = f'{{app="signal-slate", run_id="{run_id}"}}'
        args = {
            "datasourceUid": self.loki_uid,
            "logql": logql,
            "startRfc3339": start_rfc3339,
            "endRfc3339": end_rfc3339,
            "limit": bounded_limit,
            "direction": "forward",
        }
        res_text = await self.call_mcp_tool("query_loki_logs", args)
        return self._parse_loki_entries(res_text, expected_run_id=run_id)

    def _parse_loki_entries(
        self,
        raw_output: str,
        expected_run_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        """Parse structured logs returned by mcp-grafana query_loki_logs v1.3.0.

        Parses data entries containing timestamp, line and labels, plus truncation metadata.
        Fails closed on error/truncation/malformed schema.
        Detects conflicting duplicates.
        """
        if not raw_output:
            return [], False, False

        try:
            parsed = json.loads(raw_output)
        except Exception as exc:
            raise McpResponseError(f"Failed to parse Loki MCP response as JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise McpResponseError(
                f"Expected dict response from Loki MCP, got {type(parsed).__name__}"
            )

        metadata = parsed.get("metadata", {})
        is_truncated = False
        if isinstance(metadata, dict) and metadata.get("resultsTruncated") is True:
            is_truncated = True

        raw_items = parsed.get("data")
        if raw_items is None:
            raw_items = parsed.get("entries")
        if raw_items is None:
            raise McpResponseError("Loki MCP response missing 'data' or 'entries' field")
        if not isinstance(raw_items, list):
            raise McpResponseError(f"Loki 'data' must be a list, got {type(raw_items).__name__}")

        entries: list[dict[str, Any]] = []
        seen_samples: dict[tuple[str, int], dict[str, Any]] = {}
        has_conflicting_duplicates = False

        for item in raw_items:
            if not isinstance(item, dict):
                raise McpResponseError(
                    f"Loki data item must be an object, got {type(item).__name__}"
                )

            line_str = item.get("line")
            if line_str is None:
                continue

            try:
                line_data = json.loads(line_str) if isinstance(line_str, str) else line_str
            except Exception as exc:
                raise McpResponseError(f"Loki line is not valid JSON: {exc}") from exc

            if not isinstance(line_data, dict):
                continue

            # Check run_id
            if expected_run_id is not None:
                item_run_id = line_data.get("run_id")
                if item_run_id is not None and item_run_id != expected_run_id:
                    raise McpResponseError(
                        f"Loki returned foreign run log: expected {expected_run_id}, "
                        f"got {item_run_id}"
                    )

            if line_data.get("event") == "sample":
                mic_id = str(line_data.get("mic_id", ""))
                offset_ms = int(line_data.get("offset_ms", -1))
                key = (mic_id, offset_ms)
                if key in seen_samples:
                    prev = seen_samples[key]
                    if (
                        prev.get("quality") != line_data.get("quality")
                        or prev.get("link_margin_db") != line_data.get("link_margin_db")
                        or prev.get("battery_pct") != line_data.get("battery_pct")
                        or prev.get("is_dropout") != line_data.get("is_dropout")
                        or prev.get("is_clipped") != line_data.get("is_clipped")
                        or prev.get("run_id") != line_data.get("run_id")
                        or prev.get("session_id") != line_data.get("session_id")
                        or prev.get("config_hash") != line_data.get("config_hash")
                        or prev.get("timestamp_rfc3339") != line_data.get("timestamp_rfc3339")
                    ):
                        has_conflicting_duplicates = True
                else:
                    seen_samples[key] = line_data

            entries.append(line_data)

        return entries, is_truncated, has_conflicting_duplicates

    async def query_prometheus_run_metrics(
        self,
        run_id: str,
        start_rfc3339: str,
        end_rfc3339: str,
    ) -> tuple[list[PerSecondMetric], list[EvidenceEnvelope], bool]:
        """Execute parameterized query_prometheus against Prometheus via allowlisted MCP tool.

        Queries genuine cloud metrics independently from Loki logs.
        Returns:
            (metrics, envelopes, is_truncated)
        """
        validate_opaque_id(run_id, "run_id")
        validate_opaque_id(self.prom_uid, "prom_datasource_uid")

        families = "|".join(sorted(REQUIRED_METRIC_FAMILIES))
        expr = f'{{run_id="{run_id}",__name__=~"{families}"}}'
        args = {
            "datasourceUid": self.prom_uid,
            "expr": expr,
            "queryType": "instant",
            "endTime": datetime.fromisoformat(end_rfc3339.replace("Z", "+00:00")).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        res_text = await self.call_mcp_tool("query_prometheus", args)
        return self._parse_prometheus_metrics(res_text, expected_run_id=run_id)

    def _parse_prometheus_metrics(
        self,
        raw_output: str,
        expected_run_id: str | None = None,
        require_full_grid: bool = True,
    ) -> tuple[list[PerSecondMetric], list[EvidenceEnvelope], bool]:
        """Parse Prometheus query results returned by mcp-grafana query_prometheus v1.3.0.

        Parses metric labels, timestamp/value pairs, and truncation metadata.
        or {status: "success", data: {result: [...]}}
        Fails closed on error/truncation/malformed schema/missing measurement values.
        Requires all 5 metric families present exactly once per (mic_id, second) identity.
        """
        if not raw_output:
            return [], [], False

        try:
            parsed = json.loads(raw_output)
        except Exception as exc:
            raise McpResponseError(
                f"Failed to parse Prometheus MCP response as JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise McpResponseError(
                f"Expected dict response from Prometheus MCP, got {type(parsed).__name__}"
            )

        metadata = parsed.get("metadata", {})
        is_truncated = False
        if isinstance(metadata, dict) and metadata.get("resultsTruncated") is True:
            is_truncated = True

        raw_series = parsed.get("data")
        if isinstance(raw_series, dict) and "result" in raw_series:
            raw_series = raw_series["result"]
        elif raw_series is None:
            raw_series = parsed.get("result", [])

        if not isinstance(raw_series, list):
            raise McpResponseError(
                f"Prometheus data must be a list, got {type(raw_series).__name__}"
            )

        # Track received metric values per (mic_id, second, metric_name)
        # Store: (val, run_id, session_id, config_hash, ts_str)
        seen_family_points: dict[tuple[str, int, str], tuple[float, str, str, str, str]] = {}
        envelopes: list[EvidenceEnvelope] = []
        retrieval_time = datetime.now(UTC).isoformat()
        query_hash = canonical_hash({"tool": "query_prometheus", "run_id": expected_run_id})

        for item in raw_series:
            if not isinstance(item, dict):
                raise McpResponseError(
                    f"Prometheus data item must be a dict, got {type(item).__name__}"
                )
            metric_labels = item.get("metric", {})
            if not isinstance(metric_labels, dict):
                raise McpResponseError("Prometheus metric labels must be a dict")

            item_run_id = metric_labels.get("run_id")
            if not item_run_id:
                raise McpResponseError("Prometheus metric missing required 'run_id' label")
            if expected_run_id and item_run_id != expected_run_id:
                raise McpResponseError(
                    f"Prometheus returned foreign run metric: expected {expected_run_id}, "
                    f"got {item_run_id}"
                )

            session_id = metric_labels.get("session_id", "")
            if not session_id:
                raise McpResponseError("Prometheus metric missing required 'session_id' label")

            config_hash = metric_labels.get("config_hash", "")
            if not config_hash:
                raise McpResponseError("Prometheus metric missing required 'config_hash' label")

            metric_name = metric_labels.get("__name__", "")
            if metric_name not in REQUIRED_METRIC_FAMILIES:
                raise McpResponseError(
                    f"Unexpected metric family in Prometheus response: '{metric_name}'"
                )

            mic_id = metric_labels.get("mic_id", "")
            if not mic_id:
                raise McpResponseError("Prometheus metric missing required 'mic_id' label")

            sec_str = metric_labels.get("second")
            if sec_str is None:
                raise McpResponseError("Prometheus metric missing required 'second' label")

            try:
                second = int(sec_str)
            except (ValueError, TypeError) as exc:
                raise McpResponseError(
                    f"Malformed 'second' in Prometheus metric: '{sec_str}'"
                ) from exc

            if not (0 <= second <= 11):
                raise McpResponseError(f"Prometheus metric 'second' out of range [0, 11]: {second}")

            # Parse value strictly without default coercion
            val_raw = None
            ts_raw = ""
            if "value" in item and isinstance(item["value"], list) and len(item["value"]) >= 2:
                ts_raw = str(item["value"][0])
                val_raw = item["value"][1]
            elif "values" in item and isinstance(item["values"], list) and item["values"]:
                ts_raw = str(item["values"][-1][0])
                val_raw = item["values"][-1][1]
            else:
                raise McpResponseError(f"Prometheus metric {metric_name} missing valid value array")

            try:
                val = float(val_raw)
            except (ValueError, TypeError) as exc:
                raise McpResponseError(
                    f"Malformed non-numeric value in Prometheus metric {metric_name} "
                    f"for ({mic_id}, sec {second}): '{val_raw}'"
                ) from exc

            if not math.isfinite(val):
                raise McpResponseError(
                    f"Non-finite value in Prometheus metric {metric_name} "
                    f"for ({mic_id}, sec {second}): {val}"
                )

            source_time = metric_labels.get("timestamp_rfc3339")
            if not source_time:
                raise McpResponseError("Missing metric source timestamp label")
            try:
                parsed_source_time = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
                if parsed_source_time.tzinfo is None:
                    raise ValueError("naive timestamp")
                ts_raw = str(parsed_source_time.timestamp())
            except Exception as exc:
                raise McpResponseError("Invalid metric source timestamp label") from exc

            # Check for duplicate metric family data points
            key = (mic_id, second, metric_name)
            if key in seen_family_points:
                prev_val, prev_run, prev_sess, prev_cfg, _ = seen_family_points[key]
                if (
                    prev_val != val
                    or prev_run != item_run_id
                    or prev_sess != session_id
                    or prev_cfg != config_hash
                ):
                    raise McpContradictionError(
                        f"Conflicting duplicate metric in Prometheus for {metric_name} "
                        f"({mic_id}, sec {second}): {prev_val} vs {val}"
                    )
            else:
                seen_family_points[key] = (val, item_run_id, session_id, config_hash, str(ts_raw))

            ev_id = f"ev-prom-{item_run_id}-{metric_name}-{mic_id}-sec{second}"
            envelopes.append(
                EvidenceEnvelope(
                    evidence_id=ev_id,
                    run_id=item_run_id,
                    mic_id=mic_id,
                    offset_ms=second * 1000,
                    source_tool="query_prometheus",
                    query_hash=query_hash,
                    observation_type="metric_summary",
                    value={metric_name: val},
                    unit="prom_metric",
                    retrieval_time=retrieval_time,
                    config_hash=config_hash,
                )
            )

        # Assemble and validate identities
        # All 5 families MUST be present for every checked identity (NO healthy defaults!)
        canonical_mics = ["mic_1", "mic_2", "mic_3", "mic_4"]
        metrics: list[PerSecondMetric] = []

        if require_full_grid:
            target_identities = [(s, m) for s in range(12) for m in canonical_mics]
        else:
            target_identities = sorted(
                list({(sec, mic) for (mic, sec, fam) in seen_family_points.keys()})
            )

        for second, mic_id in target_identities:
            missing_fams = [
                fam
                for fam in REQUIRED_METRIC_FAMILIES
                if (mic_id, second, fam) not in seen_family_points
            ]
            if missing_fams:
                raise McpResponseError(
                    f"Prometheus response missing required metric families {sorted(missing_fams)} "
                    f"for mic '{mic_id}' second {second}. Refusing to invent healthy defaults."
                )

            q_val, r_id, s_id, c_hash, ts_str = seen_family_points[
                (mic_id, second, "signal_slate_receiver_quality")
            ]
            l_val, _, _, _, _ = seen_family_points[(mic_id, second, "signal_slate_link_margin_db")]
            b_val, _, _, _, _ = seen_family_points[(mic_id, second, "signal_slate_battery_pct")]
            c_val, _, _, _, _ = seen_family_points[
                (mic_id, second, "signal_slate_clipping_duration_ms")
            ]
            d_val, _, _, _, _ = seen_family_points[
                (mic_id, second, "signal_slate_dropout_duration_ms")
            ]

            identities = {
                seen_family_points[(mic_id, second, family)][1:4]
                for family in REQUIRED_METRIC_FAMILIES
            }
            if len(identities) != 1:
                raise McpContradictionError(
                    "Metric families disagree on run/session/config identity"
                )
            if c_val != int(c_val) or d_val != int(d_val):
                raise McpResponseError("Duration metrics must be integral milliseconds")

            ts_iso = ""
            if ts_str:
                try:
                    ts_f = float(ts_str)
                    ts_iso = datetime.fromtimestamp(ts_f, tz=UTC).isoformat()
                except Exception as exc:
                    raise McpResponseError("Invalid metric timestamp") from exc

            metrics.append(
                PerSecondMetric(
                    second=second,
                    mic_id=mic_id,
                    min_quality=round(q_val, 1),
                    min_link_margin_db=round(l_val, 1),
                    min_battery_pct=round(b_val, 1),
                    clipping_duration_ms=int(c_val),
                    dropout_duration_ms=int(d_val),
                    timestamp_rfc3339=ts_iso,
                    run_id=r_id,
                    session_id=s_id,
                    config_hash=c_hash,
                )
            )

        metrics.sort(key=lambda m: (m.second, m.mic_id))
        return metrics, envelopes, is_truncated

    async def poll_ingestion_ready(
        self,
        run_id: str,
        start_rfc3339: str,
        end_rfc3339: str,
        expected_samples: int = 484,
        timeout_seconds: float = 20.0,
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        """Poll Grafana Cloud with exponential backoff until run evidence is indexed."""
        backoffs = [1.0, 2.0, 4.0, 6.0, 8.0]
        start_poll = time.time()
        attempt = 0

        while (time.time() - start_poll) < timeout_seconds:
            entries, is_trunc, has_conflicts = await self.query_loki_run_logs(
                run_id, start_rfc3339, end_rfc3339, limit=1000
            )
            sample_entries = [e for e in entries if e.get("event") == "sample"]
            completion_marker = any(e.get("event") == "run_completed" for e in entries)

            if len(sample_entries) >= expected_samples and completion_marker:
                return entries, is_trunc, has_conflicts

            sleep_duration = backoffs[min(attempt, len(backoffs) - 1)]
            await asyncio.sleep(sleep_duration)
            attempt += 1

        return await self.query_loki_run_logs(run_id, start_rfc3339, end_rfc3339, limit=1000)

    async def collect_observed_run(
        self,
        run_id: str,
        session_id: str,
        start_time_sec: float,
        end_time_sec: float,
        expected_manifest: EvidenceManifest | None = None,
        timeout_seconds: float = 20.0,
    ) -> ObservedRun:
        """Collect complete run evidence from Grafana MCP and assemble into ObservedRun."""
        validate_opaque_id(run_id, "run_id")
        validate_opaque_id(session_id, "session_id")

        start_dt = datetime.fromtimestamp(start_time_sec - 30.0, tz=UTC)
        end_dt = datetime.fromtimestamp(end_time_sec + 30.0, tz=UTC)
        start_rfc = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_rfc = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        entries, loki_is_trunc, has_conflicting_duplicates = await self.poll_ingestion_ready(
            run_id=run_id,
            start_rfc3339=start_rfc,
            end_rfc3339=end_rfc,
            expected_samples=484,
            timeout_seconds=timeout_seconds,
        )

        samples: list[MicSample] = []
        completion_marker = False
        config_hash = ""

        for e in entries:
            if e.get("event") == "sample":
                if type(e.get("is_clipped")) is not bool or type(e.get("is_dropout")) is not bool:
                    raise McpResponseError("Sample flags must be explicit JSON booleans")
                s_ts = str(e.get("timestamp_rfc3339", ""))
                samples.append(
                    MicSample(
                        offset_ms=int(e["offset_ms"]),
                        mic_id=str(e["mic_id"]),
                        quality=float(e["quality"]),
                        link_margin_db=float(e["link_margin_db"]),
                        battery_pct=float(e["battery_pct"]),
                        is_clipped=bool(e.get("is_clipped", False)),
                        is_dropout=bool(e.get("is_dropout", False)),
                        timestamp_rfc3339=s_ts,
                        run_id=str(e.get("run_id", "")),
                        session_id=str(e.get("session_id", "")),
                        config_hash=str(e.get("config_hash", "")),
                    )
                )
                if not config_hash and "config_hash" in e:
                    config_hash = str(e["config_hash"])
            elif e.get("event") == "run_completed":
                # Validate completion marker against expected prepublication manifest
                if expected_manifest is not None:
                    m_cnt = e.get("samples_count")
                    m_met = e.get("metrics_count")
                    m_run = e.get("run_id")
                    m_cfg = e.get("config_hash")
                    if (
                        m_cnt == expected_manifest.sample_count
                        and m_met == expected_manifest.metric_count
                        and m_run == expected_manifest.run_id
                        and m_cfg == expected_manifest.config_hash
                        and e.get("session_id") == expected_manifest.session_id
                        and e.get("manifest_hash") == expected_manifest.manifest_hash
                    ):
                        completion_marker = True
                else:
                    completion_marker = True
                if not config_hash and "config_hash" in e:
                    config_hash = str(e["config_hash"])

        # Deduplicate samples by (mic_id, offset_ms)
        unique_samples_map: dict[tuple[str, int], MicSample] = {}
        identical_duplicate_count = 0
        for s in samples:
            key = (s.mic_id, s.offset_ms)
            if key in unique_samples_map:
                prev = unique_samples_map[key]
                if (
                    prev.quality != s.quality
                    or prev.link_margin_db != s.link_margin_db
                    or prev.battery_pct != s.battery_pct
                    or prev.is_dropout != s.is_dropout
                    or prev.is_clipped != s.is_clipped
                    or prev.run_id != s.run_id
                    or prev.session_id != s.session_id
                    or prev.config_hash != s.config_hash
                    or prev.timestamp_rfc3339 != s.timestamp_rfc3339
                ):
                    has_conflicting_duplicates = True
                else:
                    identical_duplicate_count += 1
            unique_samples_map[key] = s

        deduped_samples = sorted(
            list(unique_samples_map.values()),
            key=lambda x: (x.offset_ms, x.mic_id),
        )

        # Query Prometheus for independent cloud metrics
        prom_metrics: list[PerSecondMetric] = []
        prom_is_trunc = False
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                prom_metrics, _envelopes, prom_is_trunc = await self.query_prometheus_run_metrics(
                    run_id=run_id,
                    start_rfc3339=start_rfc,
                    end_rfc3339=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                break
            except McpResponseError:
                if time.monotonic() >= deadline:
                    prom_is_trunc = True
                    break
                await asyncio.sleep(1)

        if expected_manifest is not None:
            manifest = expected_manifest
            source_audio_hash = expected_manifest.source_audio_hash
            scenario_path_hash = expected_manifest.scenario_path_hash
            fault_commitment_hash = expected_manifest.fault_commitment_hash
            cfg_hash = expected_manifest.config_hash
        else:
            manifest = None
            source_audio_hash = ""
            scenario_path_hash = ""
            fault_commitment_hash = ""
            cfg_hash = config_hash

        return ObservedRun(
            run_id=run_id,
            session_id=session_id,
            config_hash=cfg_hash,
            samples=deduped_samples,
            metrics=prom_metrics,
            completion_marker_present=completion_marker,
            retrieved_sample_count=len(deduped_samples),
            start_time_rfc3339=datetime.fromtimestamp(start_time_sec, UTC).isoformat(),
            end_time_rfc3339=datetime.fromtimestamp(end_time_sec, UTC).isoformat(),
            is_truncated=(loki_is_trunc or prom_is_trunc),
            has_conflicting_duplicates=has_conflicting_duplicates,
            identical_duplicate_count=identical_duplicate_count,
            source_audio_hash=source_audio_hash,
            scenario_path_hash=scenario_path_hash,
            fault_commitment_hash=fault_commitment_hash,
            manifest=manifest,
        )


class BoundedModelEvidenceWrapper:
    """Bounded typed application wrapper tools exposed to Google ADK Gemini agent.

    The model interacts strictly through these tools and never sees raw PromQL/LogQL.
    """

    def __init__(self, observed_run: ObservedRun, context: ShotContext) -> None:
        self.observed_run = observed_run
        self.context = context
        self._envelopes: dict[str, EvidenceEnvelope] = {}
        self._build_evidence_envelopes()

    def _build_evidence_envelopes(self) -> None:
        """Create indexed EvidenceEnvelope objects with verifiable evidence IDs."""
        # 1. Summary envelope for each microphone
        for m in self.observed_run.metrics:
            ev_id = f"ev-metric-{m.mic_id}-sec{m.second}"
            self._envelopes[ev_id] = EvidenceEnvelope(
                evidence_id=ev_id,
                run_id=self.observed_run.run_id,
                mic_id=m.mic_id,
                offset_ms=m.second * 1000,
                source_tool="get_run_metrics",
                query_hash=canonical_hash({"metric": "summary", "sec": m.second, "mic": m.mic_id}),
                observation_type="metric_summary",
                value={
                    "min_quality": m.min_quality,
                    "min_link_margin_db": m.min_link_margin_db,
                    "dropout_duration_ms": m.dropout_duration_ms,
                    "clipping_duration_ms": m.clipping_duration_ms,
                    "min_battery_pct": m.min_battery_pct,
                },
                unit="metric_composite",
                retrieval_time=datetime.now(UTC).isoformat(),
                config_hash=self.observed_run.config_hash,
            )

        # 2. Dropout and anomaly envelopes for individual samples
        for s in self.observed_run.samples:
            if s.is_dropout or s.quality < 60.0 or s.is_clipped:
                ev_id = f"ev-dropout-{s.mic_id}-off{s.offset_ms}"
                self._envelopes[ev_id] = EvidenceEnvelope(
                    evidence_id=ev_id,
                    run_id=self.observed_run.run_id,
                    mic_id=s.mic_id,
                    offset_ms=s.offset_ms,
                    source_tool="get_run_events",
                    query_hash=canonical_hash({"offset": s.offset_ms, "mic": s.mic_id}),
                    observation_type=(
                        "sample_dropout"
                        if s.is_dropout
                        else "sample_clipping"
                        if s.is_clipped
                        else "degraded_quality"
                    ),
                    value={
                        "quality": s.quality,
                        "link_margin_db": s.link_margin_db,
                        "is_dropout": s.is_dropout,
                        "is_clipped": s.is_clipped,
                    },
                    unit="observation",
                    retrieval_time=datetime.now(UTC).isoformat(),
                    config_hash=self.observed_run.config_hash,
                )

    def get_run_metrics(
        self,
        run_id: str,
        mic_ids: list[str] | None = None,
        start_ms: int = 0,
        end_ms: int = 12000,
    ) -> list[dict[str, Any]]:
        """Return metric buckets overlapping [start_ms, end_ms); end is exclusive."""
        if run_id != self.observed_run.run_id:
            return []

        target_mics = set(mic_ids) if mic_ids else set(self.context.mic_ids)
        results = []
        for _ev_id, env in self._envelopes.items():
            if env.observation_type == "metric_summary" and env.mic_id in target_mics:
                if (
                    env.offset_ms is not None
                    and start_ms < end_ms
                    and env.offset_ms < end_ms
                    and env.offset_ms + 1000 > start_ms
                ):
                    results.append(
                        {
                            "evidence_id": env.evidence_id,
                            "mic_id": env.mic_id,
                            "offset_ms": env.offset_ms,
                            "value": env.value,
                        }
                    )
        return sorted(results, key=lambda x: (x["offset_ms"], x["mic_id"]))

    def get_run_events(
        self,
        run_id: str,
        mic_ids: list[str] | None = None,
        start_ms: int = 0,
        end_ms: int = 12000,
        event_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return anomalous sample intervals overlapping [start_ms, end_ms)."""
        if run_id != self.observed_run.run_id:
            return []

        target_mics = set(mic_ids) if mic_ids else set(self.context.mic_ids)
        results = []
        for _ev_id, env in self._envelopes.items():
            if (
                env.observation_type != "metric_summary"
                and env.mic_id in target_mics
                and (not event_types or env.observation_type in event_types)
            ):
                if (
                    env.offset_ms is not None
                    and start_ms < end_ms
                    and env.offset_ms < end_ms
                    and env.offset_ms + self.context.sample_period_ms > start_ms
                ):
                    results.append(
                        {
                            "evidence_id": env.evidence_id,
                            "mic_id": env.mic_id,
                            "offset_ms": env.offset_ms,
                            "observation_type": env.observation_type,
                            "value": env.value,
                        }
                    )
        return sorted(results, key=lambda x: (x["offset_ms"], x["mic_id"]))

    def get_shot_context(self) -> dict[str, Any]:
        """Bounded model tool: Retrieve scene metadata, dialogue interval, and channel options."""
        return self.context.model_dump(mode="json")
