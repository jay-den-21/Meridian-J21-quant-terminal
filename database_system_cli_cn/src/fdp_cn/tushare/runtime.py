"""Lazy Tushare runtime construction isolated from the EODHD runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from fdp_cn.config import (
    TushareRuntimeConfig,
    database_url_from_env,
    tushare_runtime_config_from_env,
    tushare_token_from_env,
)
from fdp_cn.tushare.client import TushareClient
from fdp_cn.tushare.models import TushareApiEvent

TushareClientFactory = Callable[..., TushareClient]
TushareProgressCallback = Callable[[TushareApiEvent], None]


@dataclass
class TushareJobRuntime:
    """Database engine plus a client that is constructed only for live execution."""

    engine: Engine
    config_override: TushareRuntimeConfig | None = None
    injected_client: TushareClient | None = None
    client_factory: TushareClientFactory = TushareClient

    @classmethod
    def from_env(cls) -> "TushareJobRuntime":
        return cls(
            engine=create_engine(database_url_from_env()),
            config_override=tushare_runtime_config_from_env(),
        )

    def config(self) -> TushareRuntimeConfig:
        if self.config_override is None:
            self.config_override = tushare_runtime_config_from_env()
        return self.config_override

    def client(
        self,
        *,
        max_retries: int | None = None,
        progress_callback: TushareProgressCallback | None = None,
    ) -> TushareClient:
        """Build one job-scoped client; this is the only method that reads the token."""
        if self.injected_client is not None:
            return self.injected_client
        config = self.config()
        return self.client_factory(
            token=tushare_token_from_env(),
            max_retries=(config.max_retries if max_retries is None else max_retries),
            retry_delay_seconds=config.retry_delay_seconds,
            progress_callback=progress_callback,
        )
