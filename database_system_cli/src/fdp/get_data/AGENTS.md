# Shared Job Context

本文件适用于 `fdp.get_data` 及其子目录，并继承上级 `AGENTS.md`。

## 本层拥有

- CLI、terminal menu、Python caller 共用的 Job 编排。
- `JobPreflight`、`JobResult`、progress event 和 parameter-source 契约。
- lazy `JobRuntime`、预算/范围检查、work-unit 事务编排和 Job registry。

## 本层不拥有

- Typer 或 terminal prompt 的展示细节。
- EODHD 原始 payload 的 HTTP、解析和字段映射。
- SQLAlchemy table definition、Alembic migration 或研究查询。

## 开工前读取

- `../../../../.trellis/spec/backend/ingest-job-contracts.md`
- `../../../docs/architecture.md`
- `contracts.py`、`runtime.py`、`registry.py`
- 被修改 Job 调用的 `../sources/eodhd/ingest/` 实现

## 数据流

```text
显式参数/Job default -> preflight -> lazy runtime/client -> provider ingest
                     -> progress events -> versioned JobResult
```

## 修改检查

- 参数优先级固定为 explicit > Job default > `ValueError`。
- preflight 必须只读；越预算时不得读取 API key 或创建 API client。
- 新增/修改 human-operable Job 时同步 `registry.py`、`fdp/cli.py`、
  `fdp/menu/app.py`、tests 和 CLI/menu 文档。
- CLI/menu 不得复制 Job 业务逻辑，也不得互相 shell 调用。
- JSON stdout 只能有一个稳定 `JobResult`；progress 写 stderr。
- 历史任务保持 aggregate run + 每 symbol 独立 transaction；并行任务停止后要
  drain 已运行 work units，使结果计数等于已提交事实。
- 至少运行 Job、CLI 和 menu 相关测试，以及 Ruff/compileall。
