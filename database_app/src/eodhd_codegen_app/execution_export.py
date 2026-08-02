from __future__ import annotations

import csv
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from threading import Lock
from typing import Any

from eodhd_codegen_app.request_model import ApiRequest


EXPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
CSV_FORMULA_RE = re.compile(r"^[\t\r\n ]*[=+\-@]")
PRIORITY_COLUMNS = ("_provider_symbol", "provider_symbol", "code", "symbol", "datetime", "date")


@dataclass(frozen=True)
class ExportSnapshot:
    export_id: str
    endpoint: str
    exchange: str
    created_at: datetime
    rows: tuple[dict[str, Any], ...]


class ExecutionExportStore:
    """Keep the latest successful execution in memory for full CSV export."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot: ExportSnapshot | None = None

    def replace(self, request: ApiRequest, rows: list[dict[str, Any]]) -> ExportSnapshot:
        snapshot = ExportSnapshot(
            export_id=secrets.token_urlsafe(24),
            endpoint=request.endpoint,
            exchange=request.exchange,
            created_at=datetime.now(timezone.utc),
            rows=tuple(dict(row) for row in rows),
        )
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def get(self, export_id: str) -> ExportSnapshot | None:
        if not EXPORT_ID_RE.fullmatch(export_id):
            return None
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None or not secrets.compare_digest(snapshot.export_id, export_id):
            return None
        return snapshot


def csv_bytes(snapshot: ExportSnapshot) -> bytes:
    columns = _ordered_columns(snapshot.rows)
    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\n")
    if columns:
        writer.writerow(_safe_cell(_display_column(column)) for column in columns)
        for row in snapshot.rows:
            writer.writerow(_safe_cell(row.get(column)) for column in columns)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def export_filename(snapshot: ExportSnapshot) -> str:
    exchange = re.sub(r"[^A-Za-z0-9_-]+", "-", snapshot.exchange).strip("-") or "all"
    timestamp = snapshot.created_at.strftime("%Y%m%dT%H%M%SZ")
    return f"eodhd_{snapshot.endpoint}_{exchange}_{timestamp}.csv"


def _ordered_columns(rows: tuple[dict[str, Any], ...]) -> list[str]:
    discovered: dict[str, None] = {}
    for row in rows:
        for key in row:
            discovered.setdefault(key, None)
    ordered = [column for column in PRIORITY_COLUMNS if column in discovered]
    ordered.extend(column for column in discovered if column not in PRIORITY_COLUMNS)
    return ordered


def _display_column(column: str) -> str:
    return "request_symbol" if column == "_provider_symbol" else column


def _safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if CSV_FORMULA_RE.match(text) else text
