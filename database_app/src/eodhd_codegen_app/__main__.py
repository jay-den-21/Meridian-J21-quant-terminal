from __future__ import annotations

import argparse

from eodhd_codegen_app.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EODHD code generator app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, open_browser=args.open_browser)


if __name__ == "__main__":
    main()
