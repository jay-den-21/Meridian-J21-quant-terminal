#!/usr/bin/env python3
"""Aggregate original-framework endpoint results without touching provider or DB.

The input contract is the report directory produced by
``tools/verification/original_endpoint_log_runner.py``. Completed endpoints come from
``results/*.json``; line-oriented counters and the pre-run database snapshot
come from ``logs/NNN_get_*.log``.  A matching log without a result is retained
as an incomplete endpoint instead of being mistaken for a pass.

This module intentionally uses only the Python standard library and never
imports the original or replica application.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


SCHEMA_VERSION = 2
JSON_OUTPUT_NAME = "endpoint_results.json"
MARKDOWN_OUTPUT_NAME = "endpoint_results.md"

ENDPOINT_LOG_NAME_RE = re.compile(
    r"^(?P<sequence>\d{3})_(?P<endpoint>get_[A-Za-z0-9_]+)\.log$"
)
CALL_RE = re.compile(
    r"对应的接口已调用\s*(?P<ordinal>[\d,]+)\s*次.*?"
    r"抓取条数\s*(?P<fetched>[\d,]+)\s*"
    r"清洗后\s*(?P<cleaned>[\d,]+)\s*"
    r"最终入库\s*(?P<written>[\d,]+)"
)
TOTAL_RE = re.compile(
    r"本次总共抓取数据\s*(?P<fetched>[\d,]+)\s*条[，,]?\s*"
    r"清洗后\s*(?P<cleaned>[\d,]+)\s*"
    r"最终入库\s*(?P<written>[\d,]+)"
)
EXPLICIT_ZERO_RE = re.compile(r"总抓取数据\s*0\s*条")
DUPLICATE_FOUND_RE = re.compile(
    r"找到重复数据\s*(?P<batch>[\d,]+)\s*行[，,]\s*"
    r"共\s*(?P<total>[\d,]+)\s*条"
)
DUPLICATE_DELETED_RE = re.compile(
    r"删除\s*(?P<actual>[\d,]+)\s*行重复数据"
    r"（预期\s*(?P<expected>[\d,]+)\s*行）"
)

# Match only an affirmative provider denial.  The framework's generic
# "可能...没有权限" zero-row warning is deliberately not permission evidence.
EXPLICIT_PERMISSION_RE = re.compile(
    r"没有访问该接口的权限|没有接口\([^)]*\)访问权限|"
    r"权限不足[，,\s]*无法访问该接口",
    re.IGNORECASE,
)
RATE_LIMIT_RE = re.compile(
    r"频率超限|每(?:分钟|小时|日)[^\n]*最多访问|"
    r"最多访问[^\n]*次/(?:分钟|小时|日)|rate[ -]?limit",
    re.IGNORECASE,
)
NETWORK_ERROR_RE = re.compile(
    r"ConnectionError|ConnectTimeout|ReadTimeout|SSLError|"
    r"Temporary failure|Name or service not known|连接[^\n]*(?:失败|超时)",
    re.IGNORECASE,
)
DB_SCHEMA_ERROR_RE = re.compile(
    r"ProgrammingError|OperationalError|DataError|IntegrityError|"
    r"Unknown column|doesn't exist|Table '[^']+' doesn't exist",
    re.IGNORECASE,
)


class AggregationError(RuntimeError):
    """Raised when the report directory cannot be safely aggregated."""


@dataclass
class LogEvidence:
    """Secret-free counters and classifications derived from one log."""

    before_snapshot: dict[str, Any] | None = None
    endpoint_metadata: dict[str, Any] | None = None
    provider_calls_observed: int = 0
    max_call_ordinal: int | None = None
    call_fetched: int = 0
    call_cleaned: int = 0
    call_written: int = 0
    total_records: int = 0
    total_fetched: int = 0
    total_cleaned: int = 0
    total_written: int = 0
    explicit_zero: bool = False
    duplicate_found_records: int = 0
    duplicate_rows_found: int = 0
    duplicate_cleanup_records: int = 0
    duplicate_rows_deleted: int = 0
    duplicate_rows_expected: int = 0
    saw_warning: bool = False
    saw_error: bool = False
    traceback: bool = False
    explicit_permission: bool = False
    rate_limit: bool = False
    network_error: bool = False
    db_schema_error: bool = False
    postprocess_index_error: bool = False
    table_missing_message: bool = False
    anomalies: list[str] = field(default_factory=list)


def _add_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _count(raw: str) -> int:
    return int(raw.replace(",", ""))


def _json_object_from_marker(
    payload: str,
    *,
    malformed_code: str,
    anomalies: list[str],
) -> dict[str, Any] | None:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        _add_once(anomalies, malformed_code)
        return None
    if not isinstance(value, dict):
        _add_once(anomalies, malformed_code)
        return None
    return value


def parse_log(path: Path) -> LogEvidence:
    """Parse one log in a streaming pass and retain no raw message text."""

    evidence = LogEvidence()
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        evidence.anomalies.append("LOG_READ_ERROR")
        return evidence

    with handle:
        for line in handle:
            if line.startswith("RUNNER_DB_BEFORE="):
                if evidence.before_snapshot is not None:
                    _add_once(evidence.anomalies, "MULTIPLE_BEFORE_SNAPSHOTS")
                else:
                    evidence.before_snapshot = _json_object_from_marker(
                        line.split("=", 1)[1],
                        malformed_code="BEFORE_SNAPSHOT_MALFORMED",
                        anomalies=evidence.anomalies,
                    )
            elif line.startswith("RUNNER_ENDPOINT="):
                if evidence.endpoint_metadata is not None:
                    _add_once(evidence.anomalies, "MULTIPLE_ENDPOINT_METADATA")
                else:
                    evidence.endpoint_metadata = _json_object_from_marker(
                        line.split("=", 1)[1],
                        malformed_code="ENDPOINT_METADATA_MALFORMED",
                        anomalies=evidence.anomalies,
                    )

            call = CALL_RE.search(line)
            if call:
                ordinal = _count(call.group("ordinal"))
                evidence.provider_calls_observed += 1
                evidence.max_call_ordinal = max(
                    evidence.max_call_ordinal or 0,
                    ordinal,
                )
                evidence.call_fetched += _count(call.group("fetched"))
                evidence.call_cleaned += _count(call.group("cleaned"))
                evidence.call_written += _count(call.group("written"))

            total = TOTAL_RE.search(line)
            if total:
                evidence.total_records += 1
                evidence.total_fetched += _count(total.group("fetched"))
                evidence.total_cleaned += _count(total.group("cleaned"))
                evidence.total_written += _count(total.group("written"))

            evidence.explicit_zero = bool(
                evidence.explicit_zero or EXPLICIT_ZERO_RE.search(line)
            )

            duplicate_found = DUPLICATE_FOUND_RE.search(line)
            if duplicate_found:
                evidence.duplicate_found_records += 1
                # The second number is the framework's total duplicate count;
                # the first is only the current batch size.
                evidence.duplicate_rows_found += _count(duplicate_found.group("total"))

            duplicate_deleted = DUPLICATE_DELETED_RE.search(line)
            if duplicate_deleted:
                evidence.duplicate_cleanup_records += 1
                evidence.duplicate_rows_deleted += _count(
                    duplicate_deleted.group("actual")
                )
                evidence.duplicate_rows_expected += _count(
                    duplicate_deleted.group("expected")
                )

            evidence.saw_warning = evidence.saw_warning or "| WARNING" in line
            evidence.saw_error = evidence.saw_error or any(
                marker in line for marker in ("| ERROR", "Traceback", "服务器返回错误")
            )
            evidence.traceback = evidence.traceback or "Traceback" in line
            evidence.explicit_permission = bool(
                evidence.explicit_permission or EXPLICIT_PERMISSION_RE.search(line)
            )
            evidence.rate_limit = bool(
                evidence.rate_limit or RATE_LIMIT_RE.search(line)
            )
            evidence.network_error = bool(
                evidence.network_error or NETWORK_ERROR_RE.search(line)
            )
            evidence.db_schema_error = bool(
                evidence.db_schema_error or DB_SCHEMA_ERROR_RE.search(line)
            )
            evidence.postprocess_index_error = bool(
                evidence.postprocess_index_error or "建立索引时出错" in line
            )
            evidence.table_missing_message = bool(
                evidence.table_missing_message or "表不存在，无法启动自动去重" in line
            )

    return evidence


def _load_result(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregationError(f"cannot read result JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise AggregationError(f"result JSON is not an object: {path.name}")
    return value


def _strict_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strict_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _strict_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _snapshot_value(snapshot: dict[str, Any] | None, key: str) -> Any:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    if key == "table_exists":
        return _strict_bool(value)
    return _strict_int(value)


def _snapshot_quality(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> str:
    if before is not None and after is not None:
        return "before_and_after_information_schema_estimates"
    if after is not None:
        return "after_information_schema_estimate_only"
    if before is not None:
        return "before_information_schema_estimate_only"
    return "missing"


def _row_metrics(
    evidence: LogEvidence,
    *,
    incomplete: bool,
) -> tuple[int | None, int | None, int | None, str | None]:
    if evidence.total_records:
        source = "total_summary"
        values = (
            evidence.total_fetched,
            evidence.total_cleaned,
            evidence.total_written,
        )
    elif evidence.provider_calls_observed:
        source = "per_call"
        values = (
            evidence.call_fetched,
            evidence.call_cleaned,
            evidence.call_written,
        )
    elif evidence.explicit_zero:
        source = "explicit_zero"
        values = (0, 0, 0)
    else:
        return None, None, None, None
    if incomplete:
        source += "_partial"
    return *values, source


def _metadata_mismatch(
    result: dict[str, Any],
    endpoint_metadata: dict[str, Any] | None,
) -> bool:
    if not endpoint_metadata:
        return False
    keys = ("name", "table", "group", "start", "end", "sample_code")
    return any(
        key in result
        and key in endpoint_metadata
        and result[key] != endpoint_metadata[key]
        for key in keys
    )


def _build_endpoint(
    *,
    endpoint_name: str,
    log_path: Path | None,
    report_dir: Path,
    result: dict[str, Any] | None,
    initial_anomalies: Iterable[str] = (),
) -> dict[str, Any]:
    completed = result is not None
    result_fields_valid = True
    identity_mismatch = False
    evidence = parse_log(log_path) if log_path is not None else LogEvidence()
    anomalies = list(initial_anomalies)
    for code in evidence.anomalies:
        _add_once(anomalies, code)

    metadata = evidence.endpoint_metadata or {}
    if completed:
        assert result is not None
        name = _optional_text(result.get("name")) or endpoint_name
        table = _optional_text(result.get("table"))
        group = _optional_text(result.get("group"))
        start = _optional_text(result.get("start"))
        end = _optional_text(result.get("end"))
        sample_code = result.get("sample_code")
        returncode = _strict_int(result.get("returncode"))
        result_warning = _strict_bool(result.get("saw_warning"))
        result_error = _strict_bool(result.get("saw_error"))
        duration_seconds = _strict_number(result.get("duration_seconds"))
        after_snapshot = result.get("final_database_snapshot")
        if after_snapshot is not None and not isinstance(after_snapshot, dict):
            after_snapshot = None
            _add_once(anomalies, "FINAL_SNAPSHOT_MALFORMED")
        if name != endpoint_name or _metadata_mismatch(
            result, evidence.endpoint_metadata
        ):
            _add_once(anomalies, "ENDPOINT_METADATA_MISMATCH")
            identity_mismatch = True
        required_valid = (
            table is not None
            and group is not None
            and returncode is not None
            and result_warning is not None
            and result_error is not None
            and duration_seconds is not None
        )
        if not required_valid:
            _add_once(anomalies, "RESULT_FIELD_INVALID")
            result_fields_valid = False
        if result_warning is not None and result_warning != evidence.saw_warning:
            _add_once(anomalies, "RESULT_FLAG_MISMATCH")
        if result_error is not None and result_error != evidence.saw_error:
            _add_once(anomalies, "RESULT_FLAG_MISMATCH")
        saw_warning = bool(result_warning or evidence.saw_warning)
        saw_error = bool(result_error or evidence.saw_error)
    else:
        name = endpoint_name
        table = _optional_text(metadata.get("table"))
        group = _optional_text(metadata.get("group"))
        start = _optional_text(metadata.get("start"))
        end = _optional_text(metadata.get("end"))
        sample_code = metadata.get("sample_code")
        returncode = None
        duration_seconds = None
        after_snapshot = None
        saw_warning = evidence.saw_warning
        saw_error = evidence.saw_error
        _add_once(anomalies, "INCOMPLETE_LOG_ONLY")
        if metadata.get("name") not in (None, endpoint_name):
            _add_once(anomalies, "ENDPOINT_METADATA_MISMATCH")

    if log_path is None:
        _add_once(anomalies, "LOG_MISSING")
    if evidence.before_snapshot is None:
        _add_once(anomalies, "BEFORE_SNAPSHOT_MISSING")
    if completed and after_snapshot is None:
        _add_once(anomalies, "FINAL_SNAPSHOT_MISSING")

    fetched, cleaned, written, metrics_source = _row_metrics(
        evidence,
        incomplete=not completed,
    )
    if metrics_source is None:
        _add_once(anomalies, "NO_METRICS")
    if evidence.total_records and evidence.provider_calls_observed:
        total_values = (
            evidence.total_fetched,
            evidence.total_cleaned,
            evidence.total_written,
        )
        call_values = (
            evidence.call_fetched,
            evidence.call_cleaned,
            evidence.call_written,
        )
        if total_values != call_values:
            _add_once(anomalies, "ROWS_COUNTER_MISMATCH")
    counter_mismatch = "ROWS_COUNTER_MISMATCH" in anomalies

    duplicate_rows_found = (
        evidence.duplicate_rows_found if evidence.duplicate_found_records else None
    )
    duplicate_rows_deleted = (
        evidence.duplicate_rows_deleted if evidence.duplicate_cleanup_records else None
    )
    duplicate_rows_expected = (
        evidence.duplicate_rows_expected if evidence.duplicate_cleanup_records else None
    )
    if evidence.duplicate_cleanup_records:
        duplicate_cleanup_complete: bool | None = (
            evidence.duplicate_rows_deleted == evidence.duplicate_rows_expected
        )
        if (
            evidence.duplicate_found_records
            and evidence.duplicate_rows_found != evidence.duplicate_rows_expected
        ):
            duplicate_cleanup_complete = False
    elif evidence.duplicate_found_records:
        duplicate_cleanup_complete = False
    else:
        duplicate_cleanup_complete = None

    if duplicate_cleanup_complete is False:
        if evidence.duplicate_cleanup_records:
            _add_once(anomalies, "DUPLICATE_CLEANUP_MISMATCH")
        else:
            _add_once(anomalies, "DUPLICATE_CLEANUP_INCOMPLETE")
    if evidence.traceback:
        _add_once(anomalies, "TRACEBACK")
    if evidence.explicit_permission:
        _add_once(anomalies, "PROVIDER_PERMISSION")
    if evidence.rate_limit:
        _add_once(anomalies, "PROVIDER_RATE_LIMIT")
    if evidence.network_error:
        _add_once(anomalies, "NETWORK_ERROR")
    if evidence.db_schema_error:
        _add_once(anomalies, "DB_SCHEMA_ERROR")
    if evidence.postprocess_index_error:
        _add_once(anomalies, "POSTPROCESS_INDEX_ERROR")

    after_exists = _snapshot_value(after_snapshot, "table_exists")
    if after_exists is False or evidence.table_missing_message:
        _add_once(anomalies, "TABLE_NOT_CREATED")

    is_empty = fetched == cleaned == written == 0
    if is_empty:
        _add_once(anomalies, "EMPTY_RESPONSE")

    if not completed:
        status = "INCOMPLETE"
    elif returncode is None or not result_fields_valid or identity_mismatch:
        status = "INVALID_RESULT"
    elif returncode != 0:
        _add_once(anomalies, "PROCESS_NONZERO")
        status = "PROCESS_FAILED"
    elif evidence.explicit_permission:
        status = "EXTERNAL_PERMISSION"
    elif evidence.rate_limit:
        status = "EXTERNAL_RATE_LIMIT"
    elif evidence.network_error:
        status = "EXTERNAL_NETWORK"
    elif saw_error or evidence.traceback or evidence.db_schema_error:
        status = "CODE_OR_DB_ERROR"
    elif counter_mismatch:
        status = "COUNTER_MISMATCH"
    elif duplicate_cleanup_complete is False:
        status = "DUPLICATE_CLEANUP_MISMATCH"
    elif is_empty:
        status = "EMPTY_AMBIGUOUS"
    elif log_path is None or metrics_source is None or after_snapshot is None:
        status = "INSUFFICIENT_EVIDENCE"
    elif duplicate_rows_found and duplicate_cleanup_complete:
        status = "FRAMEWORK_LOG_PASS_WITH_DUPLICATE_CLEANUP"
    else:
        status = "FRAMEWORK_LOG_PASS"

    before_snapshot = evidence.before_snapshot
    log_relative = (
        log_path.relative_to(report_dir).as_posix() if log_path is not None else None
    )
    return {
        "endpoint": name,
        "group": group,
        "table": table,
        "start": start,
        "end": end,
        "sample_code": sample_code,
        "completed": completed,
        "returncode": returncode,
        "saw_warning": saw_warning,
        "saw_error": saw_error,
        "duration_seconds": duration_seconds,
        "provider_calls_observed": evidence.provider_calls_observed,
        "max_call_ordinal": evidence.max_call_ordinal,
        "fetched_rows": fetched,
        "cleaned_rows": cleaned,
        "written_rows": written,
        "metrics_source": metrics_source,
        "duplicate_rows_found": duplicate_rows_found,
        "duplicate_rows_deleted": duplicate_rows_deleted,
        "duplicate_rows_expected": duplicate_rows_expected,
        "duplicate_cleanup_complete": duplicate_cleanup_complete,
        "database_bytes_before": _snapshot_value(
            before_snapshot,
            "database_bytes",
        ),
        "database_bytes_after": _snapshot_value(
            after_snapshot,
            "database_bytes",
        ),
        "table_exists_before": _snapshot_value(before_snapshot, "table_exists"),
        "table_rows_estimate_before": _snapshot_value(
            before_snapshot,
            "table_rows_estimate",
        ),
        "table_bytes_before": _snapshot_value(before_snapshot, "table_bytes"),
        "table_exists_after": after_exists,
        "table_rows_estimate_after": _snapshot_value(
            after_snapshot,
            "table_rows_estimate",
        ),
        "table_bytes_after": _snapshot_value(after_snapshot, "table_bytes"),
        "snapshot_quality": _snapshot_quality(before_snapshot, after_snapshot),
        "status": status,
        "anomaly_codes": anomalies,
        "log": log_relative,
    }


def _endpoint_logs(logs_dir: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for path in sorted(logs_dir.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            match = ENDPOINT_LOG_NAME_RE.fullmatch(path.name)
            if match:
                raise AggregationError(
                    f"endpoint log must not be a symlink: {path.name}"
                )
            continue
        if not path.is_file():
            continue
        match = ENDPOINT_LOG_NAME_RE.fullmatch(path.name)
        if not match:
            continue
        grouped.setdefault(match.group("endpoint"), []).append(path)
    return grouped


def _select_log(
    *,
    endpoint: str,
    result: dict[str, Any] | None,
    candidates: list[Path],
    logs_dir: Path,
) -> tuple[Path | None, list[str]]:
    anomalies: list[str] = []
    if result is not None:
        raw_log = result.get("log")
        if isinstance(raw_log, str) and raw_log:
            basename = Path(raw_log).name
            direct = logs_dir / basename
            if direct in candidates:
                return direct, anomalies
            _add_once(anomalies, "RESULT_LOG_PATH_MISMATCH")
    if not candidates:
        return None, anomalies
    if len(candidates) > 1:
        _add_once(anomalies, "MULTIPLE_LOGS")
    # Sequence-prefixed filenames sort in execution order.  For an ambiguous
    # log-only endpoint, retain the latest partial attempt and flag ambiguity.
    return candidates[-1], anomalies


def aggregate_report(report_dir: Path) -> dict[str, Any]:
    """Aggregate a report directory and atomically write both output files."""

    report_dir = report_dir.resolve()
    results_dir = report_dir / "results"
    logs_dir = report_dir / "logs"
    if not report_dir.is_dir():
        raise AggregationError(f"report directory does not exist: {report_dir}")
    if not results_dir.is_dir() or not logs_dir.is_dir():
        raise AggregationError("report directory must contain results/ and logs/")
    if results_dir.is_symlink() or logs_dir.is_symlink():
        raise AggregationError("results/ and logs/ must not be symlinks")

    grouped_logs = _endpoint_logs(logs_dir)
    endpoints: list[dict[str, Any]] = []
    completed_names: set[str] = set()
    result_paths = sorted(results_dir.glob("*.json"), key=lambda item: item.name)

    for result_path in result_paths:
        if result_path.is_symlink():
            raise AggregationError(
                f"result JSON must not be a symlink: {result_path.name}"
            )
        if not result_path.is_file():
            continue
        result = _load_result(result_path)
        endpoint = _optional_text(result.get("name")) or result_path.stem
        if endpoint in completed_names:
            raise AggregationError(f"duplicate completed endpoint: {endpoint}")
        completed_names.add(endpoint)
        candidates = grouped_logs.get(endpoint, [])
        log_path, anomalies = _select_log(
            endpoint=endpoint,
            result=result,
            candidates=candidates,
            logs_dir=logs_dir,
        )
        endpoints.append(
            _build_endpoint(
                endpoint_name=endpoint,
                log_path=log_path,
                report_dir=report_dir,
                result=result,
                initial_anomalies=anomalies,
            )
        )

    for endpoint in sorted(set(grouped_logs) - completed_names):
        log_path, anomalies = _select_log(
            endpoint=endpoint,
            result=None,
            candidates=grouped_logs[endpoint],
            logs_dir=logs_dir,
        )
        endpoints.append(
            _build_endpoint(
                endpoint_name=endpoint,
                log_path=log_path,
                report_dir=report_dir,
                result=None,
                initial_anomalies=anomalies,
            )
        )

    endpoint_log_paths = {
        path.resolve() for paths in grouped_logs.values() for path in paths
    }
    auxiliary_attempts: list[dict[str, Any]] = []
    unclassified_logs: list[str] = []
    physical_logs = sorted(logs_dir.glob("*.log"), key=lambda item: item.name)
    for log_path in physical_logs:
        if log_path.is_symlink():
            raise AggregationError(f"report log must not be a symlink: {log_path.name}")
        if not log_path.is_file() or log_path.resolve() in endpoint_log_paths:
            continue
        evidence = parse_log(log_path)
        metadata = evidence.endpoint_metadata
        endpoint_name = (
            _optional_text(metadata.get("name")) if isinstance(metadata, dict) else None
        )
        if endpoint_name is None:
            unclassified_logs.append(log_path.relative_to(report_dir).as_posix())
            continue
        auxiliary_attempts.append(
            _build_endpoint(
                endpoint_name=endpoint_name,
                log_path=log_path,
                report_dir=report_dir,
                result=None,
                initial_anomalies=("AUXILIARY_ATTEMPT_WITHOUT_RESULT",),
            )
        )

    endpoints.sort(key=lambda item: str(item["endpoint"]))
    status_counts = Counter(str(item["status"]) for item in endpoints)
    anomaly_counts = Counter(
        code for item in endpoints for code in item["anomaly_codes"]
    )
    completed_count = sum(bool(item["completed"]) for item in endpoints)
    document = {
        "schema_version": SCHEMA_VERSION,
        "source_counts": {
            "result_files": len(result_paths),
            "endpoint_log_files": sum(len(paths) for paths in grouped_logs.values()),
            "auxiliary_attempt_log_files": len(auxiliary_attempts),
            "unclassified_log_files": len(unclassified_logs),
            "physical_log_files": len(physical_logs),
        },
        "total_endpoints": len(endpoints),
        "completed_count": completed_count,
        "incomplete_count": len(endpoints) - completed_count,
        "status_counts": dict(sorted(status_counts.items())),
        "anomaly_counts": dict(sorted(anomaly_counts.items())),
        "endpoints": endpoints,
        "auxiliary_attempts": auxiliary_attempts,
        "unclassified_logs": unclassified_logs,
    }
    _write_outputs(report_dir, document)
    return document


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _markdown_cell(value: Any) -> str:
    return _format_value(value).replace("\\", "\\\\").replace("|", "\\|")


def render_markdown(document: dict[str, Any]) -> str:
    """Render a concise, deterministic human-readable endpoint table."""

    lines = [
        "# Original endpoint log aggregation",
        "",
        f"- Completed results: {document['completed_count']}",
        f"- Log-only incomplete endpoints: {document['incomplete_count']}",
        f"- Total endpoint logs: {document['source_counts']['endpoint_log_files']}",
        f"- Additional write-capable attempts without a result: {document['source_counts']['auxiliary_attempt_log_files']}",
        f"- Supporting/unclassified logs: {document['source_counts']['unclassified_log_files']}",
        "- Database table row figures are `information_schema.tables` estimates, not exact counts.",
        "- `written` is the framework's write counter; it is not the net table-row delta after cleanup.",
        "- `FRAMEWORK_LOG_PASS*` means the original framework log completed without an unexplained error; it is not a field-level database parity claim.",
        "",
        "## Status counts",
        "",
        "| status | count |",
        "| --- | ---: |",
    ]
    for status, count in document["status_counts"].items():
        lines.append(f"| {_markdown_cell(status)} | {count} |")

    lines.extend(
        [
            "",
            "## Endpoint results",
            "",
            "| endpoint | log | rc | warning | error | calls | fetched | cleaned | written | table rows (estimate) | table bytes | status | anomalies |",
            "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in document["endpoints"]:
        anomaly_text = ", ".join(item["anomaly_codes"]) or "—"
        log_path = item["log"]
        log_link = f"[{log_path}]({log_path})" if log_path else "—"
        values = (
            item["endpoint"],
            log_link,
            item["returncode"],
            item["saw_warning"],
            item["saw_error"],
            item["provider_calls_observed"],
            item["fetched_rows"],
            item["cleaned_rows"],
            item["written_rows"],
            item["table_rows_estimate_after"],
            item["table_bytes_after"],
            item["status"],
            anomaly_text,
        )
        lines.append(
            "| " + " | ".join(_markdown_cell(value) for value in values) + " |"
        )

    lines.extend(
        [
            "",
            "## Additional attempts without a result",
            "",
            "These attempts performed provider/database work but did not produce a final result snapshot. They are not included in the completed endpoint counts above.",
            "",
            "| endpoint | log | start | end | calls | fetched | cleaned | written | status | anomalies |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in document["auxiliary_attempts"]:
        anomaly_text = ", ".join(item["anomaly_codes"]) or "—"
        log_path = item["log"]
        log_link = f"[{log_path}]({log_path})" if log_path else "—"
        values = (
            item["endpoint"],
            log_link,
            item["start"],
            item["end"],
            item["provider_calls_observed"],
            item["fetched_rows"],
            item["cleaned_rows"],
            item["written_rows"],
            item["status"],
            anomaly_text,
        )
        lines.append(
            "| " + " | ".join(_markdown_cell(value) for value in values) + " |"
        )
    if not document["auxiliary_attempts"]:
        lines.append("| — | — | — | — | — | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def _stage_file(path: Path, content: str) -> Path:
    descriptor, raw_temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(raw_temp_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _write_outputs(report_dir: Path, document: dict[str, Any]) -> None:
    json_path = report_dir / JSON_OUTPUT_NAME
    markdown_path = report_dir / MARKDOWN_OUTPUT_NAME
    json_content = (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )
    markdown_content = render_markdown(document)
    staged: list[tuple[Path, Path]] = []
    try:
        staged.append((json_path, _stage_file(json_path, json_content)))
        staged.append((markdown_path, _stage_file(markdown_path, markdown_content)))
        for destination, temporary in staged:
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        directory_descriptor = os.open(report_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate original endpoint result JSON and logs without importing "
            "the application or connecting to its provider/database."
        )
    )
    parser.add_argument("report_dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        document = aggregate_report(args.report_dir)
    except (AggregationError, OSError) as exc:
        print(f"aggregation failed: {exc}", file=os.sys.stderr)
        return 2
    print(
        f"wrote {document['total_endpoints']} endpoint results to "
        f"{args.report_dir / JSON_OUTPUT_NAME} and "
        f"{args.report_dir / MARKDOWN_OUTPUT_NAME}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
