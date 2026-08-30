"""Isolated adapter for preserved getter execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping

from fdp_cn.tushare.errors import safe_error_message
from fdp_cn.tushare.models import EndpointSpec


PRODUCT_ROOT = Path(__file__).resolve().parents[3]
ProcessExecutor = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LegacyRunResult:
    endpoint: str
    table: str
    status: str
    returncode: int
    message: str


class LegacyEndpointRunner:
    """Run one getter in a child so its traceback cannot stop the parent batch."""

    def __init__(
        self,
        *,
        executor: ProcessExecutor = subprocess.run,
        python_executable: str | None = None,
    ) -> None:
        self._executor = executor
        self._python = python_executable or sys.executable

    def run(
        self,
        spec: EndpointSpec,
        *,
        date_from: date,
        date_to: date,
        codes: tuple[str, ...] = (),
        params: Mapping[str, object] | None = None,
        timeout_seconds: int = 3600,
    ) -> LegacyRunResult:
        command = [
            self._python,
            "-B",
            "-m",
            "fdp_cn.tushare.legacy_worker",
            "--endpoint",
            spec.key,
            "--from",
            date_from.strftime("%Y%m%d"),
            "--to",
            date_to.strftime("%Y%m%d"),
            "--params-json",
            json.dumps(dict(params or {}), ensure_ascii=False, default=str),
        ]
        if codes:
            command.extend(["--codes", ",".join(codes)])
        environment = dict(os.environ)
        source_root = str(PRODUCT_ROOT / "src")
        current_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            os.pathsep.join((source_root, str(PRODUCT_ROOT), current_path))
            if current_path
            else os.pathsep.join((source_root, str(PRODUCT_ROOT)))
        )
        try:
            completed = self._executor(
                command,
                cwd=PRODUCT_ROOT,
                env=environment,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return LegacyRunResult(
                spec.key,
                spec.target_table,
                "failed",
                124,
                f"接口运行超过 {timeout_seconds} 秒，已终止当前子进程",
            )
        except OSError as error:
            return LegacyRunResult(
                spec.key,
                spec.target_table,
                "failed",
                126,
                "兼容 getter 子进程启动失败: "
                f"{safe_error_message(error)}",
            )
        if completed.returncode == 0:
            return LegacyRunResult(
                spec.key,
                spec.target_table,
                "success",
                0,
                "兼容 getter 已完成",
            )
        return LegacyRunResult(
            spec.key,
            spec.target_table,
            "failed",
            completed.returncode,
            f"兼容 getter 退出码 {completed.returncode}",
        )
