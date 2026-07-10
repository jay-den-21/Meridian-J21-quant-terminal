"""Shared contracts for human and programmatic data-ingest entrypoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from fdp.sources.eodhd.retry import EodhdApiEvent

JobStatus = Literal["dry_run", "success", "partial_failed", "failed", "cancelled"]
ProgressKind = Literal[
    "start",
    "unit_started",
    "unit_completed",
    "unit_failed",
    "message",
    "finish",
]


@dataclass(frozen=True)
class JobFailure:
    """One failed or unresolved work unit in an ingest job result."""

    unit: str
    category: str
    message: str


@dataclass(frozen=True)
class JobPreflight:
    """Read-only estimate shown before an ingest job performs API calls or writes."""

    job: str
    job_module: str
    target_tables: list[str]
    work_units: int
    estimated_api_calls: int
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    estimated_rows: int | None = None
    estimated_gb: float | None = None
    missing_symbols: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobResult:
    """Stable cross-entrypoint result consumed by CLI JSON and the terminal menu."""

    job: str
    status: JobStatus
    run_id: int | None
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    rows_fetched: int = 0
    rows_matched: int = 0
    rows_inserted: int = 0
    rows_rejected: int = 0
    rows_unmatched: int = 0
    api_calls: int = 0
    work_units_total: int = 0
    work_units_completed: int = 0
    work_units_failed: int = 0
    missing_symbols: list[str] = field(default_factory=list)
    failures: list[JobFailure] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    preflight: JobPreflight | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProgressEvent:
    """One UI-neutral ingest progress event."""

    kind: ProgressKind
    job: str
    completed: int
    total: int
    unit: str | None = None
    message: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


class ProgressReporter(Protocol):
    """Consumer implemented by plain CLI and interactive terminal UIs."""

    def on_event(self, event: ProgressEvent) -> None: ...

    def on_api_event(self, event: EodhdApiEvent) -> None: ...


class NullProgressReporter:
    """No-op reporter used by Python callers that do not request progress output."""

    def on_event(self, event: ProgressEvent) -> None:
        return None

    def on_api_event(self, event: EodhdApiEvent) -> None:
        return None


def resolved_value(
    explicit: Any,
    default: Any,
    *,
    name: str,
    explicit_source: str,
) -> tuple[Any, str]:
    """Resolve one job option without silently inventing a missing value."""
    if explicit is not None:
        return explicit, explicit_source
    if default is not None:
        return default, "job_default"
    raise ValueError(f"{name} is required; provide it explicitly or set the job default")
