# AGENTS.md

本文件是 `financial-data-platform/database_system_cli` 子项目的 AI 工作约束。执行本子项目任务前先读 `PROJECT.md`，再按本文件约束行动。

## 行为准则

这些准则来自 `/Users/boqingxin/Downloads/CODEX.md`，在本子项目内按 skill 级别执行。

- **Think Before Coding**：不要静默假设。实现前先说明关键假设；有多种解释时要说清取舍；不清楚时先指出疑点再继续。
- **Simplicity First**：写能解决问题的最小代码。不要添加未要求的功能、一次性抽象、过度配置或不必要的复杂错误处理。
- **Surgical Changes**：只改完成任务必须改的地方。不要顺手重构、格式化、清理无关代码；只清理自己改动造成的未使用代码。
- **Goal-Driven Execution**：把任务转成可验证目标。多步骤任务先给简短计划，每步说明如何验证；完成后必须运行或说明相应验证。

## 硬边界

- 禁止修改 `../tushare2db/`。它只是学习参考，不是本项目代码。
- 禁止提交真实 `.env`、API key、MySQL 密码、token、私钥。
- 只能提交 `.env.example` 这类无敏感值模板。
- 禁止 silent fallback、猜测式修复、自动篡改价格数据。
- 缺失交易日不得插入空价格行。
- 异常 OHLCV 不得自动修正。
- 大批量写入必须通过唯一键 upsert，禁止依赖事后去重作为主防线。

## Schema 规则

- 业务 schema：`us_share`、`a_share`。
- 系统 schema：`system`。
- 测试 schema：`test_us_share`、`test_a_share`、`test_system`。
- 旧的本地 A 股程序/数据库名 `qtdb_pro` 只作为历史备注；本项目 A 股 schema 仍统一使用 `a_share`。
- 改 schema 必须新增 Alembic migration。
- 不能只改 Python table definition 而不写 migration。
- 不能只改 migration 而不更新代码和测试。

## API 字段映射规则

修改 API 字段、表字段、数据口径时，必须同步检查：

- source parser
- table schema
- Alembic migration
- upsert statement
- quality checks
- query access layer
- tests
- `PROJECT.md` 中仍然有效的规格

EODHD `provider_symbol` 必须保留，例如 `AAPL.US`。标准 `symbol` 也必须保留，例如 `AAPL`。

## 数据质量规则

- 允许网络/API/数据库临时失败最多重试 3 次。
- 重试 3 次后仍失败，必须记录任务失败或部分失败。
- 异常行不得入库。
- 异常行必须写入 `system.data_quality_issue`。
- 缺失数据必须生成 repair/backfill plan。
- repair 执行前必须通过 CLI 展示影响范围并要求人工确认。

## 用户参与式数据拉取

- 小规模 smoke test、诊断命令、dry-run、只读数据库验证可以由 AI agent 执行。
- 大规模 API-consuming ingest 默认由用户亲自执行，例如长区间 `daily-range --execute --yes` 或高 API-call 预算任务。
- AI agent 负责在用户执行前给出精确 CLI 命令、日期范围、API-call 预算、预期写入表和失败处理方式。
- 用户执行后，AI agent 负责读取 CLI 输出、任务日志或数据库，说明具体验证了哪些表、哪些行数、哪些缺失/重复/异常。
- 只有当用户明确说“你帮我跑”或同等授权时，AI agent 才能代跑大规模真实 ingest。

## 数据拉取双入口

- `poetry run j21 ingest ...` 是确定性的 CLI 入口，面向 AI、自动化和熟悉命令行的用户。
- `poetry run j21 menu` 是中英文交互式入口，面向希望用方向键选择参数并查看进度条的用户。
- 两个入口必须调用同一个 `fdp.get_data` Job；菜单禁止通过 shell 再调用 CLI，CLI 也不得复制 Job 的业务流程。
- Job 负责参数解析、只读 preflight、API/存储预算、执行、失败策略和结构化结果；Typer 与 terminal menu 只负责输入输出。
- 参数优先级固定为：CLI/menu 显式值 > Python Job 模块中的可编辑默认值 > 缺失时报 `ValueError`。不得猜 symbol、日期或 asset type。
- 新增可拉取 workflow 时，必须同步检查 Job registry、Typer 命令、菜单 wizard、tests 和 CLI/menu 文档。
- `--output json` 的 stdout 只能包含一个稳定 JSON 结果；进度事件写 stderr，且任何输出都不得包含 API key。
- 菜单不会改变“大规模拉数由用户操作”的规则；确认页必须先显示目标表、参数来源和预算，默认选择取消。

## 常用命令

依赖安装：

```bash
poetry install
```

运行测试：

```bash
poetry run pytest
```

执行 migration：

```bash
poetry run alembic upgrade head
```

计划中的 CLI：

```bash
poetry run j21 ingest ...
poetry run j21 validate ...
poetry run j21 repair ...
```

## 文档规则

- `PROJECT.md` 是项目规格文字源文件，主要给 Codex/AI 执行使用。
- `PROJECT.html` 是给用户和 Codex/AI 同时阅读的看板版，适合浏览、检查和展示项目结构；它必须从 `PROJECT.md` 同步更新。
- `AGENTS.md` 是执行约束。
- 修改面向人阅读的 `.md` 文档时，如果存在对应 `.html` 文件，必须同步更新 HTML 版本。
- 修改规格、架构、流程、CLI 或进度相关文档时，必须同步更新 `PROGRESS.md` 看板；如果只是错别字/格式且不影响进度，应在最终说明中明确。
- 不要为每个叶子目录机械创建 `AGENTS.md`；只在职责、风险或验证方法确实不同的边界创建。
- 当前代码路径和完整调用关系以 `docs/architecture.md` 为入口。

## 局部上下文路由

规则按目录向下累积。修改下列路径前，除本文件外还必须读取对应的局部
`AGENTS.md`：

| 修改路径 | 最近的局部上下文 | 主要职责 |
| --- | --- | --- |
| `docs/**` | `docs/AGENTS.md` | 文档事实、Markdown/HTML 同步 |
| `src/fdp/get_data/**` | `src/fdp/get_data/AGENTS.md` | 共享 Job 契约与编排 |
| `src/fdp/menu/**` | `src/fdp/menu/AGENTS.md` | 人类终端输入和进度展示 |
| `src/fdp/sources/eodhd/**` | `src/fdp/sources/eodhd/AGENTS.md` | EODHD transport、parser、ingest |
| `src/fdp/storage/**` | `src/fdp/storage/AGENTS.md` | SQLAlchemy metadata、upsert、schema guard |
| `alembic/**` | `alembic/AGENTS.md` | 物理 schema 迁移历史 |
| `src/fdp/quality/**` | `src/fdp/quality/AGENTS.md` | 质量检测和 issue 记录 |
| `src/fdp/repair/**` | `src/fdp/repair/AGENTS.md` | 缺失数据的确认式修复 |
| `src/fdp/quarantine/**` | `src/fdp/quarantine/AGENTS.md` | 坏行归档和确认式移除 |
| `src/fdp/research/**` | `src/fdp/research/AGENTS.md` | 数据库只读研究接口 |

`src/fdp/cli.py` 是薄 Typer adapter，直接受本文件和
`src/fdp/get_data/AGENTS.md` 的共享 Job 约束。若一项修改跨越多个路径，必须读取所有
相关局部文件，并按 `docs/architecture.md` 检查上下游。

`src/fdp/bulk_unmatched.py` 是 unmatched classification/routing 的 domain service；它直接
继承本文件，并在修改时额外读取 `src/fdp/get_data/AGENTS.md`、
`src/fdp/storage/AGENTS.md` 和 `docs/architecture.md`。`src/fdp/config.py` 等未列出的顶层
模块直接继承本文件，不需要空的局部 `AGENTS.md`。

仓库级可视化位于平级 `../research_terminal/`。CLI 只拥有 canonical 数据、研究读取和
确定性命令契约；Terminal 只能通过只读查询消费这些契约，不能把 HTTP/UI 状态或写库入口
反向放入本子项目。
