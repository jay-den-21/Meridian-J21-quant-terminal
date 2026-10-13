# Meridian J21

Local-first financial data tools: collect market data, track data quality, and
generate API requests. This repository contains source code, not a market dataset
or a hosted investment service.

| Component | Purpose | Entry point |
| --- | --- | --- |
| [US Database CLI](database_system_cli/README.md) | EODHD ingestion, resumable daily jobs, validation, repair, and research reads | `poetry run j21` / `poetry run j21 menu` |
| [CN Database CLI](database_system_cli_cn/README.md) | Tushare catalog, Chinese menu, historical getters, and index membership workflows | `poetry run j21` / `poetry run j21 menu` |
| [API Code Generator](database_app/README.md) | Local EODHD request builder, Python/curl/JS snippets, previews, and CSV export | `python -m eodhd_codegen_app` |

US and CN are independent applications. **Install them in separate virtual
environments and run their commands from the corresponding subdirectory.** Both
currently expose `j21`; a repository-wide unified launcher is a roadmap item,
not an available command.

## Start With The API App

Python 3.11+ is required. From a fresh clone:

```bash
git clone https://github.com/jay-den-21/Meridian-J21-quant-terminal.git
cd Meridian-J21-quant-terminal/database_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m eodhd_codegen_app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Code generation does not require an API key.
Executing requests requires your own EODHD entitlement and token. The optional
instrument browser requires an existing local US database; without one it shows
an explicit unavailable state, while request generation remains usable.

## US Database CLI

Install [Poetry](https://python-poetry.org/docs/#installation) and Python 3.11+.
From the repository root:

```bash
cd database_system_cli
poetry config virtualenvs.in-project true --local
poetry install
poetry run j21 --help
poetry run pytest
```

Help and offline tests do not require a funded provider account. Ingestion
requires MySQL, local configuration based on `.env.example`, migrations, and
your own EODHD subscription. Follow the [CLI tutorial](database_system_cli/docs/cli_commands.md)
and [Menu guide](database_system_cli/docs/terminal_menu.md) before executing writes.
Never run a long backfill without reviewing its API budget and target tables.

## CN Database CLI

The compatibility runtime currently pins **Python 3.11.3** and SQLAlchemy 1.4.
Do not combine it with the US environment, which uses SQLAlchemy 2.

```bash
cd database_system_cli_cn
poetry env use /path/to/python3.11.3
poetry config virtualenvs.in-project true --local
poetry install
poetry run j21 --help
poetry run j21 ingest list
PYTHONPATH=src poetry run python -B -m unittest discover -s tests -v
```

Use your own MySQL/Tushare configuration for ingestion. CLI plans are dry-run by
default; real writes require `--execute --yes`. The catalog distinguishes ordinary
points-tier access from separately enabled endpoints. Provider permissions can
change: consult the linked official sources and your account entitlements.
See the [CN guide](database_system_cli_cn/README.md).

## What Is Included

- SQLAlchemy tables and Alembic migrations for the US data system.
- Shared Job implementations behind CLI, Menu, and selected MCP tools.
- Explicit API budgets, task checkpoints, quality issues, and repair workflows.
- An independent CN ingestion product and local EODHD API playground.
- Tests, architecture documentation, and shared Trellis workflow infrastructure.

Personal websites, Research Terminal UI, private research, credentials, database
dumps, and purchased reference PDFs are not distributed here. Archived internal
planning is not required to install or run the public products. Historical release
branches/tags describe earlier versions, not the current quickstart.

## License And Data Rights

Original project code is released under [MIT](LICENSE). Third-party material keeps
its own notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The code license does **not** grant EODHD, Tushare, exchange, or index-provider data
access or redistribution rights. No API subscription, market data, constituent
dataset, or ready-to-download cleaned database is included. Any future data-bundle
delivery requires separate redistribution rights. This is research infrastructure,
not investment advice or an execution platform.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before contributing.
