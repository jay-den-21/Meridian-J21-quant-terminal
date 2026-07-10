# Quarantine Workflow Context

本文件适用于 `fdp.quarantine`，并继承上级 `AGENTS.md`。

## 本层拥有

- 对已存坏行创建、预览、确认、claim 和执行 quarantine/dedupe plan。
- 先归档 source payload/hash，再按锁定主键删除，最后验证 issue resolution。

## 本层不拥有

- missing-data backfill、provider API 调用或 speculative price correction。
- 自动处理 payload 不一致的 duplicate group。

## 开工前读取

- `../../../PROJECT.md` 的 Repair/quarantine 章节
- `../quality/AGENTS.md`、`../storage/AGENTS.md`
- `plans.py` 及 CLI 中 `quarantine` commands

## 数据流

```text
open bad-row issue -> plan/preview -> user confirm -> claim + lock source row
                   -> archive payload/hash -> exact delete -> revalidate -> resolve
```

## 修改检查

- 归档成功数量必须等于删除数量；顺序不得反转。
- 执行时重验 source row 与 preview/hash 一致，防止 stale plan 删除新数据。
- exact duplicate 才能自动 dedupe；冲突 payload 转人工 review。
- calendar 变化造成 stale issue 时不得仅凭 issue 旧描述静默 resolved。
- 所有 destructive 路径必须保持显式确认和原子 plan claim。
- 运行 quarantine tests、CLI tests 和受影响 quality checks。
