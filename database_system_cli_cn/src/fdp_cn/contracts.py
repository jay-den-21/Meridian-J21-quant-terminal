"""UI-neutral result and progress contracts shared by CN CLI and Menu."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol


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
    """One failed endpoint or work unit."""

    unit: str
    category: str
    message: str


@dataclass(frozen=True)
class JobPreflight:
    """Read-only plan shown before provider or database work."""

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
    """Stable result returned by CLI, Menu, and Python calls."""

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
    """One presentation-neutral progress event."""

    kind: ProgressKind
    job: str
    completed: int
    total: int
    unit: str | None = None
    message: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


class ProgressReporter(Protocol):
    def on_event(self, event: ProgressEvent) -> None: ...

    def on_api_event(self, event: object) -> None: ...


class NullProgressReporter:
    def on_event(self, event: ProgressEvent) -> None:
        return None

    def on_api_event(self, event: object) -> None:
        return None
