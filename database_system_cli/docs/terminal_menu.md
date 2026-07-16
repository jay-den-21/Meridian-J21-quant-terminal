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
-> 填必需参数
-> 可选高级参数
-> 查看 preflight
-> 查看等价 CLI
-> 人工确认
-> tqdm 进度
-> 结果摘要
```

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
- benchmark index daily

Bulk EOD：

- one trading day
- guarded date range

Reference / reconcile：

- US market calendar
- Security ID Mapping：US exchange full sync 或少量 provider symbols
- Bulk unmatched summary -> classify -> route dry-run -> route execute

Validate、repair、quarantine 和普通 research 查询暂时保留为 CLI-only；它们不会在菜单中显示成不可用按钮。

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

## Symbol 和日期规则

Stock/ETF history 同时接受 canonical symbol 和 provider symbol：

```text
AAPL
AAPL.US
```

两者都通过 `us_share.instrument` 解析，不会直接给输入盲目追加 `.US`。未知 symbol 会进入该次 Job 的结构化 failure 结果，不会写入 Bulk unmatched staging。

Stock/ETF history 的 symbol list 不能为空。要做全市场、长日期范围回填，应使用 Bulk `daily` / `daily-range`，避免按数万个 symbol 消耗 API calls。

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

菜单使用 `tqdm` 动态进度条；普通 CLI 使用稳定的逐行 progress event，便于日志和 AI 读取。

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
  --output json
```

stdout 只输出一个带 `schema_version` 的 `JobResult` JSON。运行进度写 stderr；API key 不会进入命令预览、进度或 JSON。

## 大规模拉数

菜单只是让操作更直观，不会绕过 API-call/storage guard。大规模 `daily-range` 应由用户本人确认并执行；先审阅 preflight 中的日期、交易日数、API-call cost、estimated rows/GB 和 target tables，再开始写库。
