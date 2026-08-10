# J21 Terminal Menu

`j21 menu` 是给人操作的数据拉取入口；`j21 ingest` 是给 AI、脚本和熟悉命令行的用户使用的确定性入口。两者调用同一组 `fdp.get_data` Jobs，因此参数校验、API 调用、写库和失败处理不会出现两套口径。

## 启动

```bash
cd database_system_cli
poetry install
poetry run j21 menu
```

菜单需要真实交互式 terminal。管道、CI 或 agent automation 应改用：

```bash
poetry run j21 ingest --help
```

## 操作流程

```text
选择语言
-> 选择数据任务
-> 黄色提示同范围未完成任务
-> Continue续跑 / New新任务
-> 填必需参数
-> 可选高级参数
-> Auto自动处理 / Manual人工后处理
-> 查看 preflight
-> 查看等价 CLI
-> 一次最终确认（默认No）
-> tqdm 进度
-> 自动classify / route / validate
-> 彩色最终摘要
```

Bulk `daily` / `daily-range` 默认使用完整自动流程：

```text
读取任务fingerprint
-> 完全相同且未完成：自动续跑
-> 完全相同且已完成：0次provider调用，返回原结果
-> 重叠范围：只复用已验证日期
-> 拉取剩余日期并逐日提交
-> 本地classify
-> route dry-run + route
-> daily-price质量检查
-> 最终报告和待处理样例
```

任务页和确认页同时提供中文/英文标签。`Continue / 继续` 是默认行为；只有明确选择
`New / 新任务` 才等价于 CLI 的 `--new-run`。`Auto / 自动处理` 是默认行为；选择
`Manual / 人工后处理` 才等价于 `--manual`，跳过本次自动 classify/route/validate。

统计、classify、route 和 status 只读取/修改本地 MySQL，EODHD API cost 固定为 0。
用户只在 provider/write 执行前确认一次，默认 `No`；取消不会丢掉此前已经提交的日期或
checkpoint。独立进入 Reference / reconcile 处理旧 backlog 时，仍按该工具自己的 preview
和确认边界执行。

确认默认是 `No`。在确认之前，Job 只读取本地配置和数据库做 preflight，不读取 API key、不调用 EODHD、不写业务表。

Preflight 会显示：

- Job module
- target tables
- resolved parameters
- 每个参数来自 menu 还是 Python Job default
- work units
- estimated API calls / rows / storage
- missing symbols 和 warnings
- equivalent CLI command

## 当前菜单任务

Instrument master：

- active instruments + symbol-change history
- delisted/inactive instruments

Historical EOD：

- stock daily
- ETF daily
- Fund daily
- benchmark index daily

Corporate actions：

- dividend history
- split history

Bulk EOD：

- one trading day
- guarded date range

Reference / reconcile：

- US market calendar
- Security ID Mapping：US exchange full sync 或少量 provider symbols
- Bulk unmatched guided workflow：新建或按 `run_id` 继续

Validation：

- EODHD active US stock 1m Parquet 小样本验证

除这个明确的 1m validation wizard 外，daily-price validate、repair、quarantine 和普通
research 查询仍保留为 CLI-only；它们不会在菜单中显示成不可用按钮。

### Intraday 1m Validation

中英文菜单均提供 `Validation -> EODHD stock 1m Parquet validation`。它要求明确输入少量
stock symbols 和日期范围，并从环境变量 `J21_INTRADAY_DATA_ROOT` 读取 repo 外绝对路径。
高级参数只允许把 weighted API hard cap 调低，不能超过 200。确认页明确标注
validation-only、目标 manifest、120 天分窗、预计 units 和等价 `j21 validate intraday` 命令；
最终确认默认 `No`。

执行时保留 pre/core/after 1m 原始行，分钟 bar 写 Parquet，MySQL 只写
`system.intraday_file_manifest` 和现有 run/API audit。Menu 不提供 Massive、PIT、全市场回填、
定时任务或独立 5/15/30m 下载入口。

### Security ID Mapping

菜单里的 ID Mapping wizard 提供两个互斥 scope：

- `US exchange`：按 `page[limit]` / `page[offset]` 分页同步全市场。
- `Provider symbols`：只查询 `AAPL.US,MSFT.US` 这类少量明确标的。

高级参数可设置 page size、resume offset、hard API-call budget 和每分钟请求上限。
确认页会显示等价的 `j21 ingest id-mappings` 命令。预算耗尽时已提交 page 保留，结果中的
`next_offset` 用于续跑。返回数据没有有效期，因此是 undated crosswalk aliases，不是
current-only 或 PIT history；同一 instrument/type 的多个 validated values 会全部保留。
若分页已完成但仍有 unmatched/invalid 行，结果为 `partial_failed` 且 `next_offset` 为空；
这表示后续需要 reconcile，不需要重复拉取整套分页。

### Dividends And Splits

Corporate Actions wizard 可以选择：

- 全部本地 stock scope，或少量明确 stock symbols/provider symbols。
- `dividend`、`split`，或两者。
- `active`、`inactive/delisted`、`all`。
- 可选 action date range；留空表示供应商可返回的最大历史。

该 workflow 的 asset type 固定为 `stock`，Menu 不提供 ETF/Fund 选择，也不会向它们发出
dividend/split 请求。

高级参数包含 instrument limit、并发、workers、checkpoint batch size、每分钟请求上限和
hard API-call budget。该预算包含 User API preflight 和重试；确认页显示真正的总预计成本，
默认仍为取消。每个 instrument 独立提交，坏 provider row 进入 data quality issue，批次完成
后保存 checkpoint。Menu 与 `j21 ingest corporate-actions` 调用同一个 Job。

### Bulk Unmatched Guided Reconcile

菜单默认处理 `unresolved + needs_instrument + unknown`。`ambiguous` 和
`non_price_asset` 只有在高级选项中主动勾选后才会重新分类。超过 100,000 行时 preflight
会醒目警告，但确认一次后可以按 checkpoint 持续跑完，不需要每批确认。

Classifier 默认每批 5,000 observations；router 默认每批 1,000 个完整
`(instrument_id, trade_date)` 组合。每批数据修改和 checkpoint 在同一 transaction 提交。
按 `Ctrl+C` 或遇到失败时，本批回滚、先前批次保留；下一次进入 Reference / reconcile，
选择 Resume 并输入 `run_id` 即可从最后安全位置继续。

Route preview 不写数据。执行 route 后，Menu 自动运行现有 daily-price checks，最终显示：

- routed / shadowed / route_failed 计数
- identity audit 和 quality issue 计数
- checkpoint phase
- 剩余 unresolved/ambiguous/needs_instrument/unknown 样例

全量 backlog 仍由用户本人在 Menu 中确认启动。小规模 smoke、dry-run 和只读验库可由
agent 执行。

### Daily 任务续跑

Menu 顶部读取 `system.ingestion_task_run` 与逐日 work-unit ledger。发现未完成 Daily 任务时，
以黄色提示显示 `run_id`、日期范围、phase、剩余日期和 lease 状态。相同 scope 选择 Continue
后只处理 `pending/failed/cancelled/held` 日期；已验证日期不再消耗 API。若另一个进程仍持有
有效 lease，Menu 必须拒绝 Continue/New，不允许同时写同一任务。

`held` 表示供应商响应明显偏薄或需要人工复核：当次调用可以正常结束，但该日期不会成为
可复用完成证据，下一次 Continue 仍会重新获取。按 `Ctrl+C` 时，已启动请求会被收集，已提交
日期保留，未完成日期下次自动继续。

## Symbol 和日期规则

Stock/ETF history 同时接受 canonical symbol 和 provider symbol：

```text
AAPL
AAPL.US
```

两者都通过 `us_share.instrument` 解析，不会直接给输入盲目追加 `.US`。未知 symbol 会进入该次 Job 的结构化 failure 结果，不会写入 Bulk unmatched staging。

Stock/ETF history 的 symbol list 不能为空。要做全市场、长日期范围回填，应使用 Bulk `daily` / `daily-range`，避免按数万个 symbol 消耗 API calls。

Bulk Menu 的 lifecycle 默认值按场景区分：

- 不填日期的最新单日 `daily`：`active`。
- 显式历史日期的 `daily`：`all`，即 active + inactive。
- `daily-range`：`all`。

这里的 `instrument_status` 是本地 instrument 匹配范围，不是 EODHD Bulk response 的字段。

参数优先级：

```text
menu/CLI explicit value > Python Job module default > ValueError
```

Python 默认值位于对应的人类可管理模块，例如：

```text
src/fdp/get_data/historical/get_stk_daily.py
src/fdp/get_data/historical/get_etf_daily.py
src/fdp/get_data/historical/get_index_daily.py
```

## 进度与失败

普通 ingest 和 Daily 自动流程使用 `tqdm` 动态进度条；独立 Guided Reconcile 使用 Rich
Live 显示真实批次、速度、ETA、checkpoint 和计数。普通 CLI 使用稳定的逐行 progress event，便于日志
和 AI 读取。Rich reporter 在非 TTY 环境自动退回普通文本，不输出动画控制字符。

Historical history 的每个 symbol 使用独立 transaction，但共享一个 aggregate `ingestion_task_run`：

- 已完成 symbol 不会因后续 symbol 失败而回滚。
- 单个 404/no-data 会记录后继续。
- 401/402/403 会立即停止。
- 数据库/解析异常会停止并正确关闭父 run。
- 连续全局 transient failures 达到阈值后停止未执行 work units。
- `Ctrl+C` 保留已提交 symbol，并把 run 标记为 cancelled/partial failure。

## 给 AI 和脚本的 JSON

需要稳定机器输出时使用：

```bash
poetry run j21 ingest daily \
  --market US \
  --date 2026-07-07 \
  --execute --yes \
  --output json
```

stdout 只输出一个带 `schema_version` 的 `JobResult` JSON。运行进度写 stderr；API key 不会进入命令预览、进度或 JSON。

## 大规模拉数

菜单只是让操作更直观，不会绕过 API-call/storage guard。大规模 `daily-range` 应由用户本人确认并执行；先审阅 preflight 中的日期、交易日数、API-call cost、estimated rows/GB 和 target tables，再开始写库。
