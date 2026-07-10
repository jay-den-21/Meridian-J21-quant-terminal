# Repair Workflow Context

本文件适用于 `fdp.repair`，并继承上级 `AGENTS.md`。

## 本层拥有

- 从可修复 missing issue 创建、预览、确认、claim 和执行 repair plan。
- 以 immutable `instrument_id` 调用 EODHD 回填缺失日频数据并验证结果。

## 本层不拥有

- 修复 invalid OHLCV、non-trading rows 或 conflicting duplicate payload。
- 未经人工确认直接调用 API 或修改 issue 状态。

## 开工前读取

- `../../../PROJECT.md` 的 Repair plan 章节
- `../quality/AGENTS.md`、`../sources/eodhd/AGENTS.md`、`../storage/AGENTS.md`
- `plans.py` 及 CLI 中 `repair` commands

## 数据流

```text
open missing issue -> plan preview -> user confirm -> atomic claim(executing)
                   -> EODHD backfill by instrument_id -> verify row -> resolve issue
```

## 修改检查

- 同一 target/instrument/date 的 active plan 必须逻辑去重。
- 执行前重验 issue 仍 open、provider symbol 未漂移、plan 状态正确。
- 外部调用前从 confirmed 原子 claim 到 executing，避免双 operator 执行。
- 只有目标行实际存在才可 resolve；失败必须保留可审计 message/status。
- 不创建空价格行，不猜 ticker，不吞掉 provider 或数据库错误。
- 运行 repair plan、CLI 和相关 ingest tests。
