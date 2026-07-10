# Research Read-Layer Context

本文件适用于 `fdp.research`，并继承上级 `AGENTS.md`。

## 本层拥有

- 面向 Python/CLI 研究调用方的数据库只读查询和稳定结果形状。
- symbol/provider symbol/identifier history 解析，以及 instrument lifecycle join。

## 本层不拥有

- EODHD API 调用、数据补拉、schema mutation、quality issue resolution 或 UI state。
- 将当前 ticker 当作历史 identity 的唯一来源。

## 开工前读取

- `../../../PROJECT.md` 的 Query access 章节
- `../storage/AGENTS.md`
- `daily_prices.py` 及 CLI 中 `research` commands

## 数据流

```text
symbols + date range -> instrument/current+history identity resolution
                     -> asset price table join -> lifecycle-enriched read result
```

## 修改检查

- 研究层只使用 `engine.connect()`/SELECT，不调用 provider 或写表。
- 支持 canonical symbol、provider symbol 和有效 identifier history 的既有语义。
- lifecycle 字段从 instrument join 暴露，不复制进 daily price 表。
- adjusted/raw 口径必须显式且向后兼容；日期范围不完整时明确报错。
- 新返回字段同步 CLI rendering、tests 和 PROJECT query contract。
- 运行 research reader 和 CLI tests。
