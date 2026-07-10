"""Thread-safe tqdm reporter for interactive ingest jobs."""

from __future__ import annotations

from threading import Lock

from tqdm import tqdm

from fdp.get_data.contracts import ProgressEvent
from fdp.get_data.reporting import format_eodhd_event
from fdp.sources.eodhd.retry import EodhdApiEvent


class TqdmProgressReporter:
    """Render work-unit progress while keeping retry messages readable."""

    def __init__(self) -> None:
        self._bar: tqdm | None = None
        self._lock = Lock()

    def on_event(self, event: ProgressEvent) -> None:
        with self._lock:
            if event.kind == "start":
                self._close()
                self._bar = tqdm(
                    total=event.total, initial=event.completed, desc=event.job, unit="unit"
                )
                return
            if self._bar is None:
                return
            if event.kind in {"unit_completed", "unit_failed", "finish"}:
                delta = max(0, event.completed - self._bar.n)
                if delta:
                    self._bar.update(delta)
                if event.counters:
                    self._bar.set_postfix(event.counters, refresh=True)
            if event.kind == "finish":
                self._close()

    def on_api_event(self, event: EodhdApiEvent) -> None:
        if event.kind not in {"retry", "failed"}:
            return
        with self._lock:
            tqdm.write(format_eodhd_event(event))

    def close(self) -> None:
        """Close the active bar when a job exits outside the normal finish event."""
        with self._lock:
            self._close()

    def _close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None
