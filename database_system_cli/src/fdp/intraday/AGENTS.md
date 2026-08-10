# Intraday Data Context

本文件适用于 `fdp.intraday`，并继承上级 `AGENTS.md`。

## 本层拥有

- 1 分钟 bar 的 provider-neutral 数据模型、UTC/New York session 口径和 PyArrow schema。
- repo 外 Parquet 路径、内容校验、checksum、幂等发布及 MySQL manifest 登记协议。

## 本层不拥有

- EODHD URL、HTTP/retry 或 payload 字段名；这些属于 `fdp.sources.eodhd`。
- Typer/Menu 输入输出；这些只能调用 `fdp.get_data.intraday` Job。
- PIT universe、Massive provider、生产级全市场回填或调度。

## 数据流

```text
validated 1m bars -> deterministic schema/order -> temporary Parquet
                  -> file verification -> atomic filesystem publish
                  -> short manifest transaction
```

## 修改检查

- `J21_INTRADAY_DATA_ROOT` 缺失、相对路径、repo 内路径和危险根路径必须在写文件前失败。
- 时间戳保存 UTC；`trade_date/session` 使用 `America/New_York`，覆盖 DST 测试。
- 自然键固定为 `(source, instrument_id, timestamp_utc, interval)`；重复、乱序和异常 OHLCV 不得发布。
- 同身份同内容重跑必须幂等；不同内容不得覆盖，必须返回 conflict/held。
- 文件系统与 MySQL 不是分布式事务；实现必须支持失败清理与同内容孤儿文件恢复，禁止宣称绝对原子。
- 测试只能用 fixture/mock 和临时目录，真实 intraday API calls 必须为 0。
