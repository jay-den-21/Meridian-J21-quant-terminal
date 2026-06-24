# financial-data-platform 项目设计文档

本文档主要给 Codex/AI 执行使用，其次给人阅读。说明文字使用中文；目录、命令、schema、表名、字段名、函数名使用英文并保持稳定。

## 1. 项目目标

`financial-data-platform` 不是一个单纯下载行情数据的脚本集合，而是一个可追踪、可验证、可扩展的金融数据库系统。

第一阶段先建立数据基础设施，并完整打通美股股票+ETF 日频量价数据：

- 数据源：EODHD paid API
- 市场：`US`
- 数据范围：当前活跃股票+ETF；可额外保存常用市场指数作为 benchmark time series；不包含退市标的
- 历史深度：近 20 年
- 数据粒度：一个标的一天一行
- 数据库：本机 MySQL
- schema：`us_share`、`a_share`、`system`

长期方向是支持策略研究和策略交易平台，但第一阶段只建设可信数据内核，不实现实盘交易、复杂前端、多数据源兜底或自动猜测式修复。

## 2. 第一阶段范围

必须完成的能力：

- 从 EODHD 获取 US 市场股票+ETF 的 `instrument` 清单。
- 按 ticker 回填近 20 年历史日频 OHLCV。
- 按 provider symbol 拉取常用市场指数的历史日频 OHLCV，用于 benchmark/market regime 研究。
- 使用 EODHD Bulk EOD 做每日盘后增量更新。
- 将结构化数据写入 MySQL。
- 使用唯一键 upsert 防止重复写入。
- 将任务运行状态、API 调用摘要、质量检查结果写入 `system` schema。
- 提供 Python 查询函数，默认从数据库读取，不直接请求 EODHD。
- 提供 CLI 命令用于 `ingest`、`validate`、`repair`。

明确不做的事情：

- 不做实盘下单。
- 不做多数据源 fallback。
- 不做复杂 app 前端。
- 不保存全量 raw API response。
- 不自动修正价格。
- 不给缺失交易日插入空价格行。
- 不包含退市股票；后续单独设计 survivorship bias / delisted instrument 模块。

## 3. 技术栈

第一版使用：

- Python
- Poetry
- MySQL
- SQLAlchemy Core
- Alembic
- Typer
- pytest
- YAML + `.env`

依赖管理使用 Poetry。敏感配置只放 `.env`，仓库只提交 `.env.example`。

数据库 schema 变更必须通过 Alembic migration 管理。可以把 Alembic 粗略理解为“数据库表结构的版本管理”，它记录建表、加字段、加索引等 schema 变化。

## 4. 目录建议

第一阶段推荐目录：

```text
financial-data-platform/
  AGENTS.md
  PROJECT.md
  pyproject.toml
  .env.example
  config/
    default.yaml
  alembic/
    versions/
  src/
    fdp/
      cli.py
      config.py
      sources/
        eodhd/
      storage/
      quality/
      repair/
      research/
  tests/
```

说明：

- `sources/eodhd/` 只负责 EODHD API client、字段解析、数据源语义。
- `storage/` 负责 MySQL 连接、SQLAlchemy Core table definitions、upsert。
- `quality/` 负责重复、缺失、OHLCV 合法性、空值等检查。
- `repair/` 负责生成和执行人工确认后的 backfill plan。
- `research/` 负责 Python/notebook/backtest 读取接口，例如 `DailyPriceReader.get_daily_prices(...)`。
- `cli.py` 暴露 `fdp ingest`、`fdp validate`、`fdp repair`、`fdp research`。

## 5. 数据模型

### 5.1 Schema

第一版使用同一个 MySQL server 下的多个 schema：

- `us_share`：美股业务数据
- `a_share`：A 股业务数据，第一阶段预留，后续使用 Tushare
- `system`：任务状态、质量报告、API 调用摘要、修复计划

备注：旧的本地 A 股程序/数据库名叫 `qtdb_pro`。本项目的新 schema 名称仍统一使用 `a_share`，不要同时创建 `qtdb_pro` 和 `a_share` 两套 A 股 schema。

测试必须使用独立 schema，例如：

- `test_us_share`
- `test_a_share`
- `test_system`

测试不得污染真实数据。

### 5.2 `us_share.instrument`

`instrument` 是标的主表，不是字段名称表。

一行代表一个金融标的，例如 Apple、Microsoft、SPY ETF。它回答“这个东西是谁”。

建议字段：

```text
instrument_id
market
symbol
provider
provider_symbol
name
exchange
asset_type
currency
is_active
listed_date
delisted_date
created_at
updated_at
```

示例：

```text
instrument_id | market | symbol | provider | provider_symbol | name       | exchange | asset_type | currency | is_active
1             | US     | AAPL   | EODHD    | AAPL.US         | Apple Inc. | NASDAQ   | stock      | USD      | 1
2             | US     | SPY    | EODHD    | SPY.US          | SPDR S&P...| NYSEARCA | etf        | USD      | 1
```

约束：

- 必须保留 `provider_symbol`，例如 `AAPL.US`。
- 必须保留标准 `symbol`，例如 `AAPL`。
- 必须保留 `market`、`exchange`、`asset_type`、`currency`。
- 第一阶段 instrument 清单只纳入 active stock/ETF；常用市场指数可作为 `asset_type = "index"` 的手动 provider-symbol 集合写入。

### 5.3 `us_share.instrument_identifier_history`

`instrument_identifier_history` 记录一个标的历史上使用过的标识符。它解决 `FB -> META` 这类 ticker/provider symbol 变化导致同一家公司被写成多个 `instrument_id` 的问题。

建议字段：

```text
identifier_history_id
instrument_id
id_type
id_value
valid_from
valid_to
source
created_at
updated_at
```

示例：

```text
instrument_id | id_type         | id_value | valid_from | valid_to   | source
1             | ticker          | FB       | null       | 2022-06-08 | EODHD_SYMBOL_CHANGE_HISTORY
1             | provider_symbol | FB.US    | null       | 2022-06-08 | EODHD_SYMBOL_CHANGE_HISTORY
1             | ticker          | META     | 2022-06-09 | null       | EODHD_SYMBOL_CHANGE_HISTORY
1             | provider_symbol | META.US  | 2022-06-09 | null       | EODHD_SYMBOL_CHANGE_HISTORY
```

规则：

- `ticker` 和 `provider_symbol` 变化必须写入本表。
- 后续可扩展保存 `cusip`、`isin`、`figi`、`lei`、`cik` 等 ID mapping 校验结果。
- `instrument` ingestion 必须优先使用 EODHD `symbol-change-history` 做显式 rename reconcile，不能主要靠猜 candidate。
- 如果 rename 后的新 `provider_symbol` 已经对应另一个 `instrument_id`，不得 silent merge；后续应作为质量问题处理。

### 5.4 日频价格表和 instrument views

v0.1 使用“身份统一，价格拆表”的结构：

- `us_share.instrument` 是唯一可写 identity master。
- `us_share.stock_instrument`、`us_share.etf_instrument`、`us_share.index_instrument` 是只读 view，按 `asset_type` 从 `instrument` 过滤出来。
- `us_share.stock_daily_price`、`us_share.etf_daily_price`、`us_share.index_daily_price` 是真实日频量价表。
- 旧 `us_share.daily_price` 暂时保留为 legacy 过渡表，不作为 v0.1 新 ingest 的主要写入目标。

这样做的原因：

- ticker rename、provider symbol 变化、identifier history 只维护一套 `instrument_id`。
- 查询和质量检查时，股票、ETF、指数的价格表不再混在一个物理表里。
- 后续做 point-in-time universe、delisted instrument、corporate action 时，身份链路仍然集中。

建议字段：

```text
{asset}_daily_price_id
instrument_id
symbol
provider_symbol
trade_date
open
high
low
close
adjusted_close
volume
currency
source
source_updated_at
created_at
updated_at
```

唯一键：

```text
unique(instrument_id, trade_date)
```

写入规则：

- 必须使用 MySQL upsert：`INSERT ... ON DUPLICATE KEY UPDATE`。
- 不允许同一个 `instrument_id + trade_date` 产生多行。
- `symbol` 和 `provider_symbol` 保存当日有效标识符，用于直接查表、审计和排查；身份连续性仍以 `instrument_id` 为准。
- 原始 OHLCV 和 `adjusted_close` 同时保留。
- 不在入库时只保留 adjusted price。
- stock 数据写 `stock_daily_price`。
- ETF 数据写 `etf_daily_price`。
- benchmark index 数据写 `index_daily_price`。
- `fdp ingest history` 用于历史回填，按 provider symbol 逐个调用历史 EOD API。
- `fdp ingest daily` 用于每日增量，调用 EODHD Bulk EOD API 后写入 stock/ETF split tables。

读取层提供价格口径开关：

```python
DailyPriceReader(connection, date_from=start, date_to=end).get_daily_prices(
    symbols=symbols,
    adjusted=True,
)
```

第一阶段 `adjusted=True` 至少使用 `adjusted_close` 作为复权收盘价。完整 adjusted OHLC 可在后续通过明确算法扩展。

### 5.5 `us_share.market_calendar`

市场交易日历表，用于判断缺失交易日。

建议字段：

```text
calendar_id
calendar_date
is_trading_day
source
created_at
updated_at
```

规则：

- 日期按交易所本地日期保存。
- 第一阶段只做 US 日频 EOD，`calendar_date` 使用 US 交易日日期。
- 优先从 EODHD exchange details / holidays 能力构建。
- 如果 EODHD 日历覆盖不足，必须定义明确的交易日历生成算法，不能靠猜测式补丁。

### 5.6 `system.ingestion_task_run`

记录每一次数据拉取/入库任务。

建议字段：

```text
run_id
job_name
market
source
target_schema
target_table
status
date_from
date_to
started_at
finished_at
rows_fetched
rows_inserted
rows_updated
rows_rejected
api_calls
error_message
config_hash
code_version
```

`status` 建议值：

```text
pending
running
success
failed
partial_failed
cancelled
```

### 5.7 `system.api_call_log`

记录 API 调用摘要，不保存全量 raw response。

建议字段：

```text
api_call_id
run_id
source
endpoint
provider_symbol
date_from
date_to
status_code
success
retry_count
rows_returned
error_message
called_at
duration_ms
```

### 5.8 `system.data_quality_check_run`

记录每一次质量检查。

建议字段：

```text
check_run_id
market
target_schema
target_table
check_scope
status
started_at
finished_at
issues_found
error_message
```

### 5.9 `system.data_quality_issue`

记录具体质量问题。

建议字段：

```text
issue_id
check_run_id
market
target_schema
target_table
issue_type
severity
instrument_id
symbol
trade_date
details
status
created_at
resolved_at
```

`issue_type` 至少包括：

```text
duplicate_key
missing_trade_date
invalid_ohlcv
null_required_field
api_rejected_row
price_on_non_trading_day
```

异常值不得自动修正。缺失交易日不得插空价格行。

### 5.10 `system.repair_plan`

记录可人工确认执行的修复计划。

建议字段：

```text
repair_plan_id
issue_id
market
repair_type
symbol
provider_symbol
date_from
date_to
status
created_at
confirmed_at
executed_at
result_message
```

`repair_type` 第一阶段主要是：

```text
backfill_missing_daily_price
```

## 6. 数据流

### 6.1 Load instrument list

从 EODHD Exchange Symbols 获取 US 市场 symbol 列表。

处理规则：

- 先从 EODHD `symbol-change-history` 获取 US rename 历史。
- 对已存在的旧 `provider_symbol` 做显式 rename reconcile，例如 `FB.US -> META.US`。
- 将旧 ticker/provider symbol 和新 ticker/provider symbol 写入 `us_share.instrument_identifier_history`。
- 过滤当前活跃 stock/ETF。
- 保留 EODHD `provider_symbol`。
- 拆出标准 `symbol`。
- 写入 `us_share.instrument`。
- 使用 upsert，重复执行不得产生重复标的。

### 6.2 Historical backfill

首次建库按 ticker 回填近 20 年历史。

流程：

```text
select active instruments
for each provider_symbol:
  call EODHD historical EOD endpoint
  parse date/open/high/low/close/adjusted_close/volume
  validate required fields and OHLCV basics
  upsert into stock_daily_price / etf_daily_price / index_daily_price by asset_type
  write api_call_log
  update ingestion_task_run
```

回填必须可分批执行。推荐先用 20-50 个 symbol 验证，再扩大到全量股票+ETF。

### 6.3 Daily bulk update

历史建好后，每日盘后优先使用 EODHD Bulk EOD 更新 US 市场。

流程：

```text
call EODHD bulk endpoint for US/date
match rows to us_share.instrument
validate OHLCV
upsert into stock_daily_price / etf_daily_price by asset_type
write task state and api call summary
```

### 6.4 Validate quality

质量检查不应该隐藏在 ingest 内部。`validate` 必须可以独立运行。

第一阶段检查：

- 重复键：理论上应被唯一约束防住，但仍需检查。
- 缺失交易日：active instrument 在 trading day 缺少对应 asset daily price row。
- 日历对齐：price row 不应落在 `market_calendar.is_trading_day = 0` 的日期。
- OHLCV 合法性：`high >= low`、`high >= open/close`、`low <= open/close`。
- 负数检查：价格和 volume 不得为负。
- 空值检查：关键字段不得为空。
- 行数异常：某天全市场返回行数明显异常时记录 issue。

检查结果必须写入 `system.data_quality_check_run` 和 `system.data_quality_issue`。

### 6.5 Repair plan

缺失数据不自动插入空行。正确流程是生成 repair plan。

```text
validate finds missing data
create system.repair_plan
CLI lists plan impact
user confirms
repair task calls EODHD again
valid rows are upserted
issue status is updated
```

CLI 必须先列出将补哪些 `symbol/date range`，再要求人工输入确认。

### 6.6 Query access

研究和未来 app 不直接读 EODHD，而是通过数据库读取。

第一阶段目标接口：

```python
get_daily_prices(symbols, start, end, adjusted=True)
```

要求：

- 支持一个或多个 symbol。
- 支持日期范围。
- 默认返回 adjusted 口径。
- `adjusted=False` 返回 raw OHLCV。
- 查询前可选检查目标范围是否存在 open quality issue。

## 7. CLI 语义

命令入口建议为 `fdp`。

术语：

- `ingest`：拉取并入库。
- `validate`：检查数据质量。
- `repair`：执行人工确认后的补数/修复。

示例命令：

```bash
poetry run fdp ingest instruments --market US --source eodhd
poetry run fdp ingest history --market US --years 20 --symbols AAPL,MSFT,SPY
poetry run fdp ingest daily --market US --date 2026-05-20
poetry run fdp validate daily-price --market US --from 2024-01-01 --to 2024-12-31
poetry run fdp repair list --market US
poetry run fdp repair run --plan-id 123
```

## 8. 错误处理原则

允许有限重试，但禁止不忠实的兜底。

允许：

- 网络/API/数据库临时失败最多重试 3 次。
- 重试间隔必须明确配置。
- 每次失败写入日志和任务状态。

禁止：

- silent fallback。
- degradation handling that hides wrong data。
- hacks / heuristics / local stabilizations。
- post-processing bandages that make bad data look successful。
- 自动猜测价格。
- 自动修正异常 OHLCV。
- 为缺失交易日插入空价格行。

异常价格处理：

```text
detect invalid row
retry source call up to 3 times
if still invalid:
  reject row
  write data_quality_issue
  mark task as failed or partial_failed
```

## 9. 测试要求

第一阶段必须覆盖：

- `instrument` 解析：`AAPL.US` 能拆成 `symbol=AAPL`、`market=US`、`provider_symbol=AAPL.US`。
- EODHD 日线响应解析：识别 `date/open/high/low/close/adjusted_close/volume`。
- MySQL upsert：同一 `instrument_id + trade_date` 重复写入不会产生重复行。
- 重复键检查。
- 缺失交易日检查。
- `high < low` 检查。
- 负价格、负成交量检查。
- 关键字段空值检查。
- 异常行重拉 3 次仍失败后不得入库，并写入 `data_quality_issue`。
- repair CLI 列出 plan 后要求人工确认。
- `get_daily_prices(..., adjusted=True/False)` 返回不同价格口径。

测试数据库必须使用独立 schema，例如 `test_us_share`、`test_system`。

## 10. 美股市场结构说明

美股和 A 股市场结构不同。

A 股通常按上交所、深交所、北交所，以及主板、科创板、创业板等板块理解。美股更常见的是按交易所/交易场所理解，例如：

- NYSE
- NASDAQ
- AMEX / NYSE American
- Cboe / BATS
- NYSE Arca

ETF 与普通股票都可以在交易所上市。第一阶段覆盖当前活跃股票+ETF。

指数例如 S&P 500、Nasdaq 100、Russell 2000 不是交易所。指数暂不作为第一阶段核心数据，但架构必须保留扩展空间。

## 11. 官方参考资料

- EODHD Historical / Market Data: https://eodhd.com/
- EODHD Trading Hours and Holidays: https://eodhd.com/financial-apis/exchanges-api-trading-hours-and-stock-market-holidays
- EODHD OpenAPI: https://github.com/EodHistoricalData/eodhd-openapi
