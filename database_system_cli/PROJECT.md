# database_system_cli 项目设计文档

本文档描述 `financial-data-platform/database_system_cli/` 子项目。`PROJECT.md` 主要给 Codex/AI 执行使用，是项目规格的文字源文件。`PROJECT.html` 是给人和 Codex/AI 同时阅读的看板版，适合浏览、检查和展示当前项目结构。说明文字使用中文；目录、命令、schema、表名、字段名、函数名使用英文并保持稳定。

## 1. 项目目标

`database_system_cli` 不是一个单纯下载行情数据的脚本集合，而是 `financial-data-platform` 仓库里的可追踪、可验证、可扩展的金融数据库系统子项目。

第一阶段先建立数据基础设施，并完整打通美股股票、ETF、Fund 日频量价数据：

- 数据源：EODHD paid API
- 市场：`US`
- 数据范围：当前与退市/非活跃股票、ETF、Fund；生命周期保存在 instrument/lifecycle；常用市场指数作为 benchmark time series
- 历史深度：近 20 年
- 数据粒度：一个标的一天一行
- 数据库：本机 MySQL
- schema：`us_share`、`a_share`、`system`、`app_log`

长期方向是支持策略研究和策略交易平台。数据库 CLI 只建设可信数据内核；平级 Terminal
提供只读可视化，但仍不实现实盘交易、多数据源兜底或自动猜测式修复。

## 2. 第一阶段范围

必须完成的能力：

- 从 EODHD 获取 US 市场股票、ETF、Fund 的 `instrument` 清单。
- 按 ticker 回填近 20 年历史日频 OHLCV。
- 按 provider symbol 拉取常用市场指数的历史日频 OHLCV，用于 benchmark/market regime 研究。
- 使用 EODHD Bulk EOD 做每日盘后增量更新。
- 拉取 EODHD delisted/inactive stock+ETF+Fund universe，并把生命周期状态写入 `instrument` 和 `instrument_lifecycle_event`。
- 将结构化数据写入 MySQL。
- 使用唯一键 upsert 防止重复写入。
- 将任务运行状态、API 调用摘要、质量检查结果写入 `system` schema。
- 提供 Python 查询函数，默认从数据库读取，不直接请求 EODHD。
- 提供 CLI 命令用于 `ingest`、`validate`、`repair`。

明确不做的事情：

- 不做实盘下单。
- 不做多数据源 fallback。
- database CLI 不拥有 app 前端；平级 `research_terminal/` 已提供 localhost-only 只读可视化。
- 不保存全量 raw API response。
- 不自动修正价格。
- 不给缺失交易日插入空价格行。
- 不在每日价格表物理保存 `is_active` / `delisted_date`；这些字段从 `instrument` 或读取层 join 暴露。
- 不在本阶段全量回填所有 delisted 标的历史价格；delisted 历史价格先通过 `--include-inactive` 做小样本集成验证，后续单独扩展。
- Bulk EOD 中无法匹配当前 instrument 的 rows 不再视为垃圾；它们先进入 `system.bulk_unmatched_daily_price_observation`，后续通过分类和严格匹配 workflow 再决定是否转入正式价格表。
- 大规模真实拉数默认由用户亲自执行 CLI；Codex/AI 负责准备命令、说明 API 预算和风险，并在执行后做数据库验证和结果解释。

## 3. 技术栈

第一版使用：

- Python
- Poetry
- MySQL
- SQLAlchemy Core
- Alembic
- Typer
- Questionary
- tqdm
- pytest
- YAML + `.env`

依赖管理使用 Poetry。敏感配置只放 `.env`，仓库只提交 `.env.example`。

数据库 schema 变更必须通过 Alembic migration 管理。可以把 Alembic 粗略理解为“数据库表结构的版本管理”，它记录建表、加字段、加索引等 schema 变化。

## 4. 目录建议

第一阶段目录位于仓库的 `database_system_cli/` 子目录下：

```text
financial-data-platform/
  database_system_cli/
    AGENTS.md
    PROJECT.md
    PROJECT.html
    PROGRESS.md
    README.md
    pyproject.toml
    .env.example
    config/
      default.yaml
    alembic/
      AGENTS.md
      versions/
    docs/
      AGENTS.md
      architecture.md
    src/
      fdp/
        cli.py
        bulk_unmatched.py
        config.py
        get_data/
          AGENTS.md
          historical/
          bulk/
          instruments/
          reconcile/
        menu/
          AGENTS.md
        sources/
          eodhd/
            AGENTS.md
        storage/
          AGENTS.md
        quality/
          AGENTS.md
        repair/
          AGENTS.md
        quarantine/
          AGENTS.md
        research/
          AGENTS.md
    tests/
  research_terminal/
    AGENTS.md
    PROJECT.md
    PROGRESS.md
    src/j21_terminal/
    frontend/
```

说明：

- `sources/eodhd/` 只负责 EODHD API client、字段解析、数据源语义。
- `storage/` 负责 MySQL 连接、SQLAlchemy Core table definitions、upsert。
- `quality/` 负责重复、缺失、OHLCV 合法性、空值等检查。
- `repair/` 负责生成和执行人工确认后的 backfill plan。
- `research/` 负责 Python/notebook/backtest 读取、本地技术指标和小预算 provider 口径抽验。
- `get_data/` 是 CLI、terminal menu 和 Python 调用共用的 Job 层，负责参数解析、preflight、执行和结构化结果。
- `menu/` 只负责中英文 prompts、确认页和 `tqdm` 展示，不复制 provider/storage 业务逻辑，也不 shell out 到 CLI。
- `bulk_unmatched.py` 是 staging row 的严格分类和 route domain service，由 `get_data/reconcile/` 和 CLI adapter 调用。
- `docs/architecture.md` 是当前可执行代码的总入口：它逐层追踪 CLI/menu/Python Job、EODHD provider、storage、quality、repair/quarantine、research 和平级只读 Terminal。
- `cli.py` 暴露 `j21 menu`、`j21 ingest`、`j21 validate`、`j21 repair`、`j21 research`；`fdp` 暂时保留为兼容 alias。
- 局部 `AGENTS.md` 只放在真实职责边界。规则从 repo root 到子项目再到最近局部文件累积；修改跨层功能时必须读取所有相关局部文件，并按 `docs/architecture.md` 检查上下游。

## 5. 数据模型

### 5.1 Schema

第一版使用同一个 MySQL server 下的多个 schema：

- `us_share`：美股业务数据
- `a_share`：A 股业务数据，第一阶段预留，后续使用 Tushare
- `system`：任务状态、质量报告、API 调用摘要、修复计划
- `app_log`：API playground、search、screener、quote、live/websocket snapshot 等临时查询响应和未来 app 日志

备注：旧的本地 A 股程序/数据库名叫 `qtdb_pro`。本项目的新 schema 名称仍统一使用 `a_share`，不要同时创建 `qtdb_pro` 和 `a_share` 两套 A 股 schema。

测试必须使用独立 schema，例如：

- `test_us_share`
- `test_a_share`
- `test_system`

测试不得污染真实数据。

### 5.2 `us_share.instrument`

`instrument` 是标的主表，不是字段名称表。

一行代表一个金融标的，例如 Apple、SPY ETF、VFINX Fund。它回答“这个东西是谁”。

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
- canonical `asset_type` 固定为 `stock/etf/fund/index/forex/crypto`，不增加临时 subtype。
- active instrument 清单纳入当前活跃 stock/ETF/Fund；delisted/inactive 通过独立 workflow 幂等写入。
- 常用市场指数可作为 `asset_type = "index"` 的手动 provider-symbol 集合写入。

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

当前使用“身份统一，按 canonical asset type 价格拆表”的结构：

- `us_share.instrument` 是唯一可写 identity master。
- `stock_instrument`、`etf_instrument`、`fund_instrument`、`index_instrument` 是只读 view。
- `stock/etf/fund/index/forex/crypto_daily_price` 是六张明确的日频表。
- 旧 `us_share.daily_price` 已退出运行模型；有效行迁入 canonical split tables 后已删除 legacy 表。

这样做的原因：

- ticker rename、provider symbol 变化、identifier history 只维护一套 `instrument_id`。
- 查询和质量检查时，不同 canonical asset type 不混在一个物理表里。
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
- Fund/Mutual Fund 数据写 `fund_daily_price`；`etf_instrument` 不再包含 Fund。
- benchmark index 数据写 `index_daily_price`。
- forex 与 crypto 分别写 `forex_daily_price`、`crypto_daily_price`。
- `j21 ingest history` 用于历史回填，按 provider symbol 逐个调用历史 EOD API。
- `j21 ingest history --instrument-status active|inactive|all` 控制历史回填匹配 active、inactive 或全部 instrument；旧 `--include-inactive` 保留为兼容入口，等价于 `--instrument-status all`。
- `j21 ingest daily` 用于每日增量；`--instrument-status active|all` 控制当前或包含 inactive 的严格 identity map，无法匹配的 rows 写入 unmatched staging。
- 历史 Bulk 依次使用 source-date identifier history、current provider symbol、可用时的 EODHD type compatibility；同一 natural key 出现旧/新 alias 时，唯一 dated-history row 胜出，其余保留为 `shadowed`。
- instrument metadata 之后若纠正 `asset_type`，quality 会报告 `asset_type_mismatch`；
  `j21 migrate daily-price-asset-types --phase plan|execute` 按当前 instrument master 把旧表行
  copy 到目标表、逐字段验证后才删除 source，目标同日 payload 冲突时整块回滚。

读取层提供价格口径开关：

```python
DailyPriceReader(connection, date_from=start, date_to=end).get_daily_prices(
    symbols=symbols,
    adjusted=True,
)
```

`adjusted=True` 使用 `adjusted_close / close` 因子同步缩放 OHLC；`adjusted=False` 保留 raw OHLC。

ETF/Fund 物理拆分使用 operator-controlled expand/backfill/contract，不在 Alembic 内复制
数千万行。`j21 migrate fund-daily-price --phase plan|copy|verify|finalize` 保存 checkpoint、
备份路径/hash 和 conservation/checksum；finalize 只有在 current verification 成功后才允许。
真实 split 最终为 ETF `7,100,821`、Fund `56,464,163`，总数守恒且跨表污染为 0；未运行
`OPTIMIZE TABLE`。

2026-07-11 终检发现 metadata 更正后遗留 `stock -> etf` 的 22 个 instrument、871 行；通用
reconcile 先以 100-row chunk 实测，再搬迁剩余 771 行，最终 mismatch plan 为 0。

### 5.5 `us_share.instrument_lifecycle_event`

`instrument_lifecycle_event` 记录标的生命周期事件，例如 delisting。它不是价格表，也不是手工备注表，而是用来保留 survivorship-bias 相关事实。

建议字段：

```text
lifecycle_event_id
instrument_id
event_type
event_date
symbol
provider_symbol
source
event_key
details
created_at
updated_at
```

规则：

- `event_type = "delisted"` 表示标的已经退市或变为 inactive。
- `event_key` 必须唯一，确保 delisted universe 重跑不会重复写事件。
- delisted workflow 更新 `instrument.is_active = false`；只有当数据源提供可靠日期时才更新 `instrument.delisted_date`。当前 EODHD `exchange-symbol-list?delisted=1` 返回字段不含 delisting date，因此该列可能保持 `NULL`。
- 每日价格表不加 `is_active` / `delisted_date` 物理列；读取层通过 join 暴露。

### 5.5b `system.bulk_unmatched_daily_price_observation`

`bulk_unmatched_daily_price_observation` 保存 EODHD Bulk EOD 返回、但在快速 ingest 阶段无法匹配当前 instrument universe 的原始日频观测。它是 staging/audit 表，不是正式价格表。

建议字段：

```text
observation_id
run_id
market
exchange
provider_symbol
symbol
trade_date
name
eodhd_type
open/high/low/close/adjusted_close/volume
currency
raw_payload
classification_status
classified_asset_type
matched_instrument_id
reason
source
first_seen_at
last_seen_at
created_at
updated_at
```

规则：

- 唯一键是 `source + provider_symbol + trade_date`。
- Bulk 重跑时只能刷新 raw payload、价格字段、`run_id` 和 `last_seen_at`，不能把已分类状态重置成 `unresolved`。
- `classification_status = unresolved` 表示尚未处理。
- `classification_status = matched` 表示严格 identity 匹配到已入库 stock/ETF/Fund/index instrument，可由 gated route 命令转入正式价格表。
- `classification_status = needs_instrument` 表示 EODHD type 看起来像 canonical price asset，但本库还没有可严格匹配的 instrument。
- `classification_status = shadowed` 表示同一 instrument/date 的低优先级 old/current alias，原始行保留但不覆盖 dated winner。
- `classification_status = ambiguous` 表示多个 identity owner 或无法唯一选出 dated winner。
- `classification_status = invalid_price` 表示 identity 可判定但 OHLCV 不合法，不能写 canonical 表。
- `classification_status = resolved` 表示该 observation 后续已严格匹配并写入 canonical 表；作为审计历史继续保留，不代表仍待处理。
- `classification_status = non_price_asset` 表示 preferred、notes、bond、warrant 等当前没有 canonical price table 的资产；Fund 已有正式表，不属于此类。
- `classification_status = routed` 表示已转入对应 split daily price table。
- `classification_status = route_failed` 表示转写时 OHLCV 校验失败或字段不足。
- `COUNT(*)` 统计的是全部历史 observations，可能包含大量 `resolved` rows；统计当前 backlog 必须显式过滤 `classification_status`。

### 5.5c `app_log` snapshot tables

`app_log` 是 app/API 查询响应日志层，不是 canonical market data schema。`us_share` 只保留 `instrument`、identifier history、market calendar、lifecycle event 和正式价格表；API playground、instrument search、screener、quote、live OHLCV、websocket event 这类临时查询产物不继续放在 `us_share`。

当前 `app_log` 通过 Alembic 管理以下表：

```text
app_request_run
instrument_search_snapshot
instrument_search_result
screener_snapshot
screener_snapshot_member
quote_snapshot
live_ohlcv_snapshot
websocket_event
```

规则：

- `app_log` 与 `us_share` / `system` 在同一个 MySQL instance 下，用独立 schema 隔离。
- 从旧 `us_share` snapshot 表迁出的少量 legacy rows 先复制进 `app_log`，验证 count 一致后再删除旧表。
- `quote_snapshot`、`live_ohlcv_snapshot`、`websocket_event` 可以保留 `instrument_id` 作为 denormalized reference，但不再对 `us_share.instrument` 建硬 FK。
- `database_app` 当前仍只读 `us_share.instrument` 作为 pool browser，不写 `app_log`；未来如果需要 app-side logging，应单独增加 `APP_LOG_DATABASE_URL` 或同等明确配置，不得 silent fallback 写回 `us_share`。

### 5.6 `us_share.market_calendar`

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
- EODHD 历史 holiday payload 若漏掉交易所已证实休市，使用带一手来源、US-only 的显式
  closure override。当前覆盖 Nasdaq 已确认的 `2012-01-02` observed holiday，以及 SEC/NYSE
  Arca 已确认的 Sandy `2012-10-29/30` 全市场休市；source 写
  `NASDAQ_SEC_US_CLOSURE`，不得用低行数启发式自动判休市。

### 5.7 `system.ingestion_task_run`

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

### 5.8 `system.api_call_log`

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

### 5.9 `system.data_quality_check_run`

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

### 5.10 `system.data_quality_issue`

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

### 5.11 `system.repair_plan`

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

### 6.0 Shared ingest orchestration

人类菜单和确定性 CLI 是两个输入界面，不是两套 ingestion 实现。

```text
Typer CLI -----\
                -> fdp.get_data Job -> EODHD source -> validation -> storage
Terminal menu -/
```

每个 Job 必须提供同一组稳定能力：

- 解析参数，记录参数来自 CLI/menu 还是 Python Job default。
- 在 API 调用和数据库写入前执行只读 preflight。
- 返回目标表、work units、API-call/storage 估算和 warning。
- 通过 UI-neutral progress event 报告进度；CLI 显示稳定文本，菜单使用 `tqdm`。
- 返回带 `schema_version` 的 `JobResult`；`--output json` 供未来 AI skill/automation 使用。

参数优先级固定为：

```text
CLI/menu explicit value > Python Job module default > ValueError
```

历史 stock/ETF/Fund pull 通过 instrument master 同时解析 canonical/provider symbol，不能盲目拼接 `.US`。每个 symbol 使用独立 transaction，共用一个 aggregate `ingestion_task_run`；单个无数据/404 可以继续，401/402/403、数据库错误或连续全局 transient failure 必须停止后续 work units。

### 6.1 Load instrument list

从 EODHD Exchange Symbols 获取 US 市场 symbol 列表。

处理规则：

- 先从 EODHD `symbol-change-history` 获取 US rename 历史。
- 对已存在的旧 `provider_symbol` 做显式 rename reconcile，例如 `FB.US -> META.US`。
- 将旧 ticker/provider symbol 和新 ticker/provider symbol 写入 `us_share.instrument_identifier_history`。
- 规范 EODHD Common Stock/Stock、ETF、Fund/Mutual Fund 到 `stock/etf/fund`。
- 保留 EODHD `provider_symbol`。
- 拆出标准 `symbol`。
- 写入 `us_share.instrument`。
- 使用 upsert，重复执行不得产生重复标的。

### 6.2 Delisted instrument lifecycle

退市标的不是通过 ticker 猜测合并，而是从 EODHD delisted symbol list 拉取。

流程：

```text
call EODHD exchange-symbol-list with delisted=1
parse inactive stock/ETF/Fund rows
upsert into us_share.instrument with is_active=false
upsert delisted lifecycle event by event_key
write task state and api call summary
```

该 workflow 必须幂等。重跑可以更新 `instrument` 当前生命周期状态，但不能重复制造 lifecycle event。

### 6.3 Historical backfill

首次建库按 ticker 回填近 20 年历史。

流程：

```text
select active/inactive/all instruments from explicit operator status
for each provider_symbol:
  call EODHD historical EOD endpoint
  parse date/open/high/low/close/adjusted_close/volume
  validate required fields and OHLCV basics
  upsert into the canonical asset-specific daily table
  write api_call_log
  update ingestion_task_run
```

回填必须可分批执行。推荐先用 20-50 个 symbol 验证，再扩大到目标 universe。

使用 `--instrument-status active|inactive|all` 明确 lifecycle 范围；旧
`--include-inactive` 只保留为 `all` 的兼容 alias。

### 6.4 Daily bulk update

历史建好后，每日盘后优先使用 EODHD Bulk EOD 更新 US 市场。

流程：

```text
call EODHD bulk endpoint for US/date
match source-date identifier history, then current provider symbol and compatible type
matched rows validate OHLCV
matched rows upsert into stock/ETF/Fund/index daily table by asset_type
unmatched rows upsert into system.bulk_unmatched_daily_price_observation
write task state and api call summary
```

多日批量补数使用 `j21 ingest daily-range`。该命令默认只做 dry-run 估算，必须显式传入 `--execute --yes` 才会写库。写库时按交易日拆分，每个交易日独立 transaction；开启 `--parallel` 后只是并行处理多个交易日，不改变表结构和 upsert 语义。

EODHD 限额规则：

- paid plan 默认日 API-call budget 按 100000 控制。
- EODHD 官方 request rate ceiling 按 1000 requests/minute 控制。
- 本项目默认限速为 600 requests/minute，低于官方上限。
- Bulk EOD 全 exchange 一次请求按 100 API calls 估算。
- User API preflight 核对 remote allowance；thread-safe ledger 在每次 attempt 前扣 weighted units，retry 也计费。
- 超过 `--max-api-calls` 或 `--max-estimated-gb` 时，命令必须在调用 EODHD 之前拒绝执行。

截至 `2026-07-12`，近期因子研究优先窗口 `2022-08-08..2026-07-06` 已完成
`instrument-status=all` Bulk recovery：980/980 个交易日、48,191,634 条 source rows、
46,958,823 条 matched rows、98,000 weighted API units、0 failed days、0 retries。
数据库逐日验收确认 Stock/ETF/Fund canonical 与 unmatched staging 在 980 天均有数据，
三个价格表的 table/master mismatch 为 0，并保留唯一
`(instrument_id, trade_date)` 索引。当前物理行数为 Stock `17,063,497`、ETF
`4,127,506`、Fund `25,587,451`、staging `1,550,792`；尚待后续额度日恢复的
pre-staging 缺口此前是 `2014-09-18..2022-08-05` 共 1,985 个交易日。

截至 `2026-07-14`，该旧窗口又完成连续前缀 `2014-09-18..2018-08-08`：
980/980 个交易日、44,389,798 条 source rows、43,220,825 次 canonical upsert
effects、99,800 weighted API units。数据库物理验收为 Stock `14,226,096`、ETF
`1,767,338`、Fund `27,260,645`、staging `1,168,973`；三类表均覆盖全部
980 天，table/master mismatch 为 0，联合唯一索引仍有效。完成该批后，2,986 个
受影响交易日已恢复 1,981 个，剩余窗口为 `2018-08-09..2022-08-05` 共 1,005 天。

截至 `2026-07-15`，剩余窗口已分两批闭合。`2018-08-09..2022-03-30`
完成 917/917 天，run IDs `6009..6925`，取得 45,485,986 条 source rows、
44,146,515 次 canonical upsert effects；917 次成功请求加 7 次 retry 共消耗
92,400 weighted API units。`2022-03-31..2022-08-05` 完成 88/88 天，
run IDs `6927..7014`，取得 4,506,354 条 source rows、4,329,704 次 canonical
upsert effects 和 176,650 条 staging observations；88 次请求消耗 8,800 units，
0 retry、0 failed day。

最终审计确认：原先缺失 post-staging evidence 的 2,986/2,986 个交易日已全部重跑，
`system.bulk_unmatched_daily_price_observation` 也覆盖全部 2,986 天。每个批次均有
Stock、ETF、Fund 和 staging 数据；三张 canonical 表的 table/master mismatch 为 0，
并由 `(instrument_id, trade_date)` 联合唯一索引阻止重复自然键。

Bulk unmatched 后处理流程：

```text
j21 research bulk-unmatched summary/list
j21 research bulk-unmatched classify
j21 ingest bulk-unmatched-route --dry-run
j21 ingest bulk-unmatched-route --execute --yes
j21 validate daily-price
```

原则：

- daily ingest 主路径必须快，只做精确匹配、正式表 upsert、unmatched staging，不做复杂猜测。
- classifier 只允许严格 provider_symbol 匹配到已入库 `instrument_id`。
- 只有 high-confidence stock/ETF/Fund/index rows 才能 route 到正式 price table。
- preferred、notes、bond、warrant、unknown 暂无 canonical price table，保留在 staging。
- 不确定的 rows 保持 unresolved/needs_instrument/non_price_asset，等待 instrument 补全或人工确认。

### 6.5 Validate quality

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

### 6.6 Repair plan

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
确认和执行时必须重新校验 linked issue 仍为 open，且当前 `instrument.provider_symbol` 与 plan preview 一致；执行前将 plan 从 `confirmed` claim 到 `executing`，避免同一 plan 被两个 operator 同时运行。同一 `target_table + instrument_id + trade_date` 的重复 open issue 只能生成一个 active repair plan；补数成功后，同一缺口的 open issue 一起标记 resolved。

坏行或多余行不走 repair。`invalid_ohlcv`、`price_on_non_trading_day` 和 `duplicate_key` 这类已经存在于价格表里的问题行，必须先进入 `system.quarantine_plan`，人工确认时预览当前匹配源行，执行前 claim plan 并锁定源行，先写入 `system.quarantined_daily_price_row` 归档 payload/hash，再按源表主键删除源行。删除数量必须等于归档数量；删除后重新验证问题已消失，才能把 linked `data_quality_issue` 标记为 `resolved`。`duplicate_key` 的 action 是 `dedupe_daily_price_rows`，只自动处理 exact duplicate payload；如果重复组价格/volume/source payload 不一致，必须拒绝自动删除并转人工 review。如果 calendar 已变化导致 non-trading issue 变 stale，但源行仍存在，不允许静默 resolved，必须重新 validate 或人工处理。

### 6.7 Query access

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
- 返回 `instrument.is_active` 和 `instrument.delisted_date`，避免把生命周期字段复制到每日价格表。
- 查询前可选检查目标范围是否存在 open quality issue。

`calculate_daily_indicators(rows, adjusted=True)` 从本地 daily rows 计算 SMA20/50/200、
EMA20、Bollinger20/2、RSI14、MACD12/26/9、Volume SMA20 和 annualized 20-day
log-return volatility，不物化巨量指标表。`j21 research technical-validate` 使用固定
SMA20/EMA20/RSI14 matrix 与 weighted hard budget（最多 200 units）抽验 EODHD 口径，
只输出报告、不写库。2026-07-11 的 45-unit 实测结果见
[`docs/technical_indicator_parity_report.md`](docs/technical_indicator_parity_report.md)。

平级 `research_terminal/` 通过只读 FastAPI repository 消费这些查询和指标，提供 Overview、
Security Explorer、ETF/Fund、Data Health、CSV 和 PNG。网页没有 ingest/repair/migration
route；`current_active` 是当前状态，`price_observed` 不是 PIT universe。

## 7. CLI 语义

命令入口建议为 `j21`。`fdp` 暂时保留为兼容 alias，避免旧笔记和脚本立刻失效。

数据拉取有两个等价入口：

- `poetry run j21 ingest ...`：参数稳定、适合 AI/自动化，可用 `--output json` 获取机器可读结果。
- `poetry run j21 menu`：中英文方向键菜单，显示 Job module、参数来源、目标表、预算和等价 CLI，人工确认后才执行并显示进度条。

`j21 menu` 直接调用 `fdp.get_data` Job，不会通过 subprocess 调用 CLI。菜单当前只覆盖 ingest workflows；validate、repair、quarantine 和 research 仍使用确定性 CLI。

术语：

- `ingest`：拉取并入库。
- `validate`：检查数据质量。
- `repair`：执行人工确认后的补数/修复。

示例命令：

```bash
poetry run j21 menu
poetry run j21 ingest instruments --market US --source eodhd
poetry run j21 ingest history --market US --symbols AAPL,MSFT,SPY --asset-types stock,etf --from 2006-01-01 --to 2026-01-01
poetry run j21 ingest history --market US --symbols OLD.US --from 2020-01-01 --to 2020-01-31 --include-inactive
poetry run j21 ingest history --market US --symbols OLD.US --from 2020-01-01 --to 2020-01-31 --instrument-status inactive
poetry run j21 ingest delisted-instruments --market US
poetry run j21 ingest daily --market US --date 2026-05-20 --asset-types stock,etf,fund --instrument-status active
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --dry-run
poetry run j21 ingest daily-range --from 2024-01-01 --to 2024-01-31 --instrument-status all --execute --yes --parallel --workers 4
poetry run j21 migrate fund-daily-price --phase verify --run-id 1
poetry run j21 research bulk-unmatched summary --from 2024-01-01 --to 2024-01-31
poetry run j21 research bulk-unmatched list --from 2024-01-01 --to 2024-01-31 --status unresolved
poetry run j21 research bulk-unmatched classify --from 2024-01-01 --to 2024-01-31
poetry run j21 ingest bulk-unmatched-route --from 2024-01-01 --to 2024-01-31 --dry-run
poetry run j21 ingest bulk-unmatched-route --from 2024-01-01 --to 2024-01-31 --execute --yes
poetry run j21 validate daily-price --market US --from 2024-01-01 --to 2024-12-31
poetry run j21 repair plan-daily-price --market US --from 2024-01-01 --to 2024-12-31
poetry run j21 quarantine plan-daily-price --market US --from 2024-01-01 --to 2024-12-31 --issue-types duplicate_key,invalid_ohlcv,price_on_non_trading_day
poetry run j21 quarantine list --status pending_confirmation
poetry run j21 quarantine confirm --plan-id 456 --yes
poetry run j21 quarantine run --plan-id 456 --yes
poetry run j21 repair list --market US
poetry run j21 repair confirm --plan-id 123 --yes
poetry run j21 repair run --plan-id 123 --yes
poetry run j21 ingest daily --market US --date 2026-05-20 --output json
poetry run j21 research technical-validate --from 2024-01-01 --to 2024-03-31 --max-api-units 200
```

## 8. 错误处理原则

允许有限重试，但禁止不忠实的兜底。

允许：

- 网络/API/数据库临时失败最多重试 5 次。
- EODHD 默认重试间隔为 61 秒，且必须明确配置。
- EODHD retry 输出必须显示原始 status/error，并提示人工等待重试。
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
retry source call up to 5 times
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
- `j21 ingest delisted-instruments` 幂等写入 inactive instruments 和 lifecycle events。
- `j21 ingest history --instrument-status inactive` 能只按 inactive symbol 写入对应 split daily table，避免重复请求 active instrument。
- Bulk EOD unmatched rows 能写入 staging 表，重跑不覆盖已分类状态。
- Bulk historical tests 覆盖 source-date identifier、FB/META reused ticker、missing Type、alias shadowing、inactive/all 和 ambiguity。
- Bulk unmatched classifier 只做严格 identity 匹配；Fund 可写 `fund_daily_price`，preferred/notes/bond/unknown 不自动写入正式 price table。
- Bulk unmatched route 必须先 dry-run；只有 `--execute --yes` 才能把 matched stock/ETF/Fund/index rows 写入正式 price table。
- Fund split verifier 覆盖 conservation、natural-key duplicate、cross-table type 和 sample checksum。
- 本地指标 fixture 与 EODHD Technical parity 覆盖 adjusted/raw、warm-up 和 weighted budget。
- 平级 Terminal 覆盖只读 SQL guard、无 write route、CSV injection、desktop/mobile overflow 和 canvas pixel。

测试数据库必须使用独立 schema，例如 `test_us_share`、`test_system`。

## 10. 美股市场结构说明

美股和 A 股市场结构不同。

A 股通常按上交所、深交所、北交所，以及主板、科创板、创业板等板块理解。美股更常见的是按交易所/交易场所理解，例如：

- NYSE
- NASDAQ
- AMEX / NYSE American
- Cboe / BATS
- NYSE Arca

ETF、Fund 与普通股票的 provider 类型不同，必须进入各自 instrument view 和物理 price table。
历史 backfill 使用 `instrument-status=all` 纳入 inactive identity，但 `price_observed` 仍不等于
point-in-time universe membership。

指数例如 S&P 500、Nasdaq 100、Russell 2000 不是交易所。指数暂不作为第一阶段核心数据，但架构必须保留扩展空间。

## 11. 官方参考资料

- EODHD Historical / Market Data: https://eodhd.com/
- EODHD Trading Hours and Holidays: https://eodhd.com/financial-apis/exchanges-api-trading-hours-and-stock-market-holidays
- EODHD OpenAPI: https://github.com/EodHistoricalData/eodhd-openapi
- Nasdaq 2012 Market Holiday Schedule: https://www.nasdaqtrader.com/TraderNews.aspx?id=dn2011-011
- SEC / NYSE Arca Superstorm Sandy closure record: https://www.sec.gov/rules/sro/nysearca/2013/34-70097.pdf
