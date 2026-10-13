"""
@author: Jayden21 <jayden0721@163.com>
SPDX-License-Identifier: MIT
Copyright (c) 2026 Jayden21. See the repository LICENSE.
"""

from pathlib import Path
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parent


def install_packages(poetry_executable=None):
    """
    使用隔离安装的 Poetry 按现有锁文件同步项目运行依赖。
    """
    poetry_executable = poetry_executable or shutil.which("poetry")
    if poetry_executable is None:
        raise RuntimeError(
            "未找到 Poetry。请先在项目虚拟环境之外安装 Poetry，再重新运行。"
        )
    commands = (
        [poetry_executable, "check", "--lock"],
        [poetry_executable, "sync", "--no-root"],
    )
    for command in commands:
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    try:
        install_packages()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as err:
        print(f"安装失败：{err}")
        raise SystemExit(1) from err
    print(
        "恭喜恭喜，(J21 database 框架版本: 7.0)安装成功！"
        "可以运行主程序 主控程序/盘后__串行抓取今日数据.py，抓取当日数据！"
        "或者使用，盘后__串行抓取历史数据.py，抓取历史数据！"
    )
