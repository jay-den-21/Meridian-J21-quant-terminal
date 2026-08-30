"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
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
