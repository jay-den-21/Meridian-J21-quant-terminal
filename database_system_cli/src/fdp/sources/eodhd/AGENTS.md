# EODHD Provider Context

本文件适用于 `fdp.sources.eodhd`，并继承上级 `AGENTS.md`。

## 本层拥有

- EODHD URL/query 构造、HTTP 调用、retry/rate-limit 和响应标准化。
- instrument、calendar、daily price 等 provider payload 的解析与拒绝原因。
- `ingest/` 中 API audit、task-run 状态和调用 storage upsert 的 provider workflow。

## 本层不拥有

- Typer/menu 输入输出、跨入口 Job 契约或研究查询。
- 凭 ticker/name 猜测 instrument identity。
- silent fallback、自动修正 OHLCV 或未确认的数据合并。

## 开工前读取

- `../../../../docs/architecture.md`
- `../../get_data/AGENTS.md`（若修改被 Job 调用的流程）
- `client.py`、`retry.py`、对应 parser 和 `ingest/common.py`
- `../../storage/AGENTS.md`（若字段或写入目标变化）

## 数据流

```text
Job options -> EodhdClient -> EodhdApiResponse -> parser accepted/rejected
            -> split-table upsert/staging -> api_call_log + ingestion_task_run
```

## 修改检查

- API key 只从配置环境读取，不进入 URL 日志、结果或测试 fixture。
- provider symbol（如 `AAPL.US`）和 canonical symbol（如 `AAPL`）不得混淆。
- 所有 ingestion workflow 的 API 调用记录 `api_call_log`；workflow 完成时更新
  aggregate task run。
- parser 必须区分 accepted/rejected，异常行不得静默入库或改值。
- Bulk unmatched 必须进入 staging，不能因 instrument 不完整而丢弃。
- 新实现放在聚焦模块；`ingestion.py` 只保持兼容 facade。
- 字段变化必须联查 parser、tables、migration、upsert、quality、research、tests/docs。
