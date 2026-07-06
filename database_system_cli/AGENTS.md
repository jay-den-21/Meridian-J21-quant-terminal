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
- `database_system_cli/` 先保留一个 `AGENTS.md`。
- 不要预创建空的模块级 `AGENTS.md`。
- 等 `src/sources/eodhd/`、`src/storage/`、`src/quality/` 等模块真实出现后，再按模块添加局部约束。
