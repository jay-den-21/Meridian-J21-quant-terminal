"""Runtime construction shared by CLI, terminal menu, and direct Python jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from fdp.config import (
    EodhdRuntimeConfig,
    database_url_from_env,
    eodhd_api_key_from_env,
    eodhd_runtime_config_from_env,
)
from fdp.get_data.contracts import NullProgressReporter, ProgressReporter
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.retry import EodhdRequestRateLimiter

ClientFactory = Callable[..., EodhdClient]


@dataclass
class JobRuntime:
    """Lazy runtime dependencies for one or more ingest jobs.

    Input: database engine, EODHD runtime controls, and optional injected client.
    Output: reusable DB engine and lazily constructed API clients.
    Flow: env/YAML -> runtime -> job preflight -> API client only after confirmation.
    """

    engine: Engine
    config: EodhdRuntimeConfig
    injected_client: EodhdClient | None = None
    client_factory: ClientFactory = EodhdClient

    @classmethod
    def from_env(cls) -> "JobRuntime":
        return cls(
            engine=create_engine(database_url_from_env()),
            config=eodhd_runtime_config_from_env(),
        )

    def client(
        self,
        reporter: ProgressReporter | None = None,
        *,
        max_requests_per_minute: int | None = None,
    ) -> EodhdClient:
        if self.injected_client is not None:
            return self.injected_client

        active_reporter = reporter or NullProgressReporter()
        requests_per_minute = max_requests_per_minute or self.config.max_requests_per_minute
        return self.client_factory(
            api_key=eodhd_api_key_from_env(),
            max_retries=self.config.max_retries,
            retry_delay_seconds=self.config.retry_delay_seconds,
            rate_limiter=EodhdRequestRateLimiter(requests_per_minute),
            progress_callback=active_reporter.on_api_event,
        )
