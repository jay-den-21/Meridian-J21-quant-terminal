"""Rich-only presentation helpers for guided Bulk reconciliation."""

from __future__ import annotations

import select as select_io
import sys
from threading import RLock
import time

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fdp.bulk_unmatched import BulkUnmatchedSummaryRow
from fdp.get_data.contracts import JobResult, ProgressEvent
from fdp.get_data.reporting import format_eodhd_event
from fdp.menu.i18n import Language
from fdp.sources.eodhd.retry import EodhdApiEvent


class RichReconcileProgressReporter:
    """Render only measured batch progress, speed, ETA, checkpoint, and counts."""

    def __init__(self, *, interactive: bool | None = None) -> None:
        detected = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = detected if interactive is None else interactive
        self.console = Console(force_terminal=self.interactive, no_color=not self.interactive)
        self._live: Live | None = None
        self._lock = RLock()
        self._started_at: float | None = None
        self._event: ProgressEvent | None = None

    def on_event(self, event: ProgressEvent) -> None:
        with self._lock:
            if event.kind == "start":
                self._started_at = time.monotonic()
                self._event = event
                if self.interactive:
                    self._live = Live(
                        self._render(event),
                        console=self.console,
                        refresh_per_second=8,
                        transient=False,
                    )
                    self._live.start()
                else:
                    self._print_plain(event)
                return
            self._event = event
            if self._live is not None:
                self._live.update(self._render(event), refresh=True)
            elif event.kind in {"unit_completed", "unit_failed", "finish"}:
                self._print_plain(event)
            if event.kind == "finish":
                self.close()

    def on_api_event(self, event: EodhdApiEvent) -> None:
        if event.kind in {"retry", "failed"}:
            self.console.print(format_eodhd_event(event))

    def close(self) -> None:
        with self._lock:
            if self._live is not None:
                self._live.stop()
                self._live = None

    def _render(self, event: ProgressEvent) -> Panel:
        elapsed = max(0.001, time.monotonic() - (self._started_at or time.monotonic()))
        speed = event.completed / elapsed
        remaining = max(0, event.total - event.completed)
        eta = remaining / speed if speed > 0 else None
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column(style="white")
        table.add_row("Stage", event.job)
        table.add_row("Progress", f"{event.completed:,} / {event.total:,}")
        table.add_row("Batch", event.unit or "-")
        table.add_row("Speed", f"{speed:,.1f} units/s")
        table.add_row("ETA", _duration(eta))
        table.add_row("Checkpoint", event.message or "-")
        for key, value in event.counters.items():
            table.add_row(key.replace("_", " ").title(), f"{value:,}")
        return Panel(table, title="J21 Reconcile", border_style="bright_cyan")

    def _print_plain(self, event: ProgressEvent) -> None:
        counters = " ".join(f"{key}={value}" for key, value in event.counters.items())
        suffix = f" {counters}" if counters else ""
        self.console.print(
            f"{event.job} {event.kind} completed={event.completed}/{event.total} "
            f"batch={event.unit or '-'} checkpoint={event.message or '-'}{suffix}"
        )


def show_reconcile_summary(
    rows: list[BulkUnmatchedSummaryRow],
    *,
    date_from: object,
    date_to: object,
    language: Language,
    interactive: bool | None = None,
) -> None:
    """Render the real staging counts before any classification confirmation."""
    detected = sys.stdout.isatty()
    use_color = detected if interactive is None else interactive
    console = Console(force_terminal=use_color, no_color=not use_color)
    title = "待处理 Bulk 数据" if language == "zh" else "Bulk staging backlog"
    table = Table(title=f"{title}  {date_from} .. {date_to}", border_style="bright_yellow")
    table.add_column("Status", style="bold")
    table.add_column("Asset", style="cyan")
    table.add_column("Rows", justify="right", style="bright_white")
    for row in rows:
        table.add_row(
            row.classification_status,
            row.classified_asset_type or "-",
            f"{row.row_count:,}",
        )
    if not rows:
        table.add_row("empty", "-", "0")
    console.print(table)


def hold_summary_for_review(
    *,
    seconds: int = 10,
    language: Language,
    interactive: bool | None = None,
) -> None:
    """Hold a TTY summary briefly; Enter skips without inventing workflow progress."""
    detected = sys.stdin.isatty() and sys.stdout.isatty()
    is_interactive = detected if interactive is None else interactive
    if not is_interactive or seconds <= 0:
        return
    console = Console(force_terminal=True)
    for remaining in range(seconds, 0, -1):
        message = (
            f"请核对统计，{remaining} 秒后继续；按 Enter 跳过"
            if language == "zh"
            else f"Review counts; continuing in {remaining}s. Press Enter to skip"
        )
        console.print(f"\r[bold yellow]{message}[/bold yellow]", end="")
        ready, _, _ = select_io.select([sys.stdin], [], [], 1.0)
        if ready:
            sys.stdin.readline()
            break
    console.print()


def play_j21_logo(*, interactive: bool | None = None) -> None:
    """Show a short logo transition without fabricating processing activity."""
    detected = sys.stdout.isatty()
    is_interactive = detected if interactive is None else interactive
    if not is_interactive:
        return
    console = Console(force_terminal=True)
    for frame in ("J", "J2", "J21"):
        console.print(
            Text(frame.center(9), style="bold bright_cyan"),
            end="\r",
        )
        time.sleep(0.08)
    console.print("J21", style="bold bright_cyan")


def show_reconcile_final_report(
    *,
    result: JobResult,
    remaining: list[BulkUnmatchedSummaryRow],
    language: Language,
    interactive: bool | None = None,
) -> None:
    """Render final committed counts and retained issue states."""
    detected = sys.stdout.isatty()
    use_color = detected if interactive is None else interactive
    console = Console(force_terminal=use_color, no_color=not use_color)
    title = "最终报告" if language == "zh" else "Final report"
    lines = [
        f"run_id={result.run_id}",
        f"status={result.status}",
        f"phase={result.metrics.get('checkpoint_phase', '-')}",
        f"quality_issues={result.metrics.get('quality_issue_count', 0)}",
        f"route_failed={result.metrics.get('route_failed', 0)}",
        "api_calls=0",
    ]
    if remaining:
        lines.append("remaining=" + ", ".join(
            f"{row.classification_status}:{row.row_count}" for row in remaining[:8]
        ))
    console.print(Panel("\n".join(lines), title=title, border_style="bright_green"))


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {remainder}s"
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"
