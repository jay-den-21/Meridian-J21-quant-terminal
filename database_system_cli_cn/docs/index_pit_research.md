# 指数接口与 PIT 落库研究

更新日期：2026-08-24

本文记录 `database_system_cli_cn` 中 8 个历史 `idx` getter 与 J21 database 指数 PIT 流程的长期业务约定、接口证据和真实验收结果。它不是某次运行日志的替代品；行数会随数据源更新而变化，变更前应重新核验官方页面和实际返回。

## 1. 结论

- 8 个历史 getter 继续保留，作为可独立运行的兼容入口、字段映射和旧框架行为参考。
- 新的指数历史/PIT 主流程统一由 `j21 ingest index-pit` 驱动。来源刷新、断点、分页、逐页事务、失败继续和 PIT 发布由同一个 Job 管理。
- 申万日频 PIT 不能只靠当前成分。SW2014 使用 `index_member` 的扁平成员区间，SW2021 使用 `index_member_all` 的 L1/L2/L3 成员区间；`out_date` 按包含当日处理。
- `index_weight` 是月度成分权重快照。必须保存数据源返回的真实 `trade_date`，不得把一张月度快照复制或插值成每天的数据。
- “单页上限”必须注明证据来源。官方页面未公布数值时，J21 探测值只能作为客户端保护值，不能写成官方承诺。

## 2. 八个历史 getter 审计

| 历史脚本 | Tushare API | 目标表 | 业务键 | getter 分页值 | 分页值依据 | 新 PIT phase / 现状 |
| --- | --- | --- | --- | ---: | --- | --- |
| `Get_idx_1min.py` | 旧 `pro_bar(freq='1min')`；现行接口为 `idx_mins` | `hq_idx_1min` | `trade_date, trade_time, ts_code` | 8,000 | 现行 `idx_mins` 官方页面明确 8,000，但 getter 仍是旧调用；分钟权限需单独购买 | 不属于 `index-pit`；保留 legacy getter，direct catalog 尚未实现 |
| `Get_idx_basic.py` | `index_basic` | `hq_idx_basic` | `ts_code` | 8,000 | 当前官方页面明确 8,000 | `basic`；dedicated Job 可执行 |
| `Get_idx_daily.py` | `index_daily` | `hq_idx_daily` | `trade_date, ts_code` | 8,000 | 历史 getter/回归契约；当前页面确认按代码和日期循环，未在本次审计中取得明确数字页限 | 不属于 `index-pit`；保留 legacy getter，direct catalog 尚未实现 |
| `Get_idx_daily_basic.py` | `index_dailybasic` | `hq_idx_daily_basic` | `trade_date, ts_code` | 3,000 | 当前官方页面明确 3,000 | 不属于 `index-pit`；保留 legacy getter，direct catalog 尚未实现 |
| `Get_idx_sw_classify.py` | `index_classify` | `hq_idx_sw_classify` | `src, level, index_code` | 50,000（getter 继承默认） | 历史 getter 默认值，不是官方页限；新 PIT 另用 10,000 的 **J21 探测值** | `classify`；按 SW2014/SW2021 × L1/L2/L3 六个单元执行 |
| `Get_idx_sw_daily.py` | `sw_daily` | `hq_idx_sw_daily` | `trade_date, ts_code` | 4,000 | 当前官方页面明确 4,000 | `sw-daily`；按自然月切分并继续 offset 分页 |
| `Get_idx_sw_member.py` | `index_member` | `hq_idx_sw_member` | `index_code, con_code, in_date` | 2,000 | **legacy getter + live-verified contract**；旧 doc_id=182 当前返回 404，不作为现行官方证据 | `sw-members` 的 SW2014 来源；每个行业代码分别抓 `is_new=N/Y` |
| `Get_idx_sw_member_all.py` | `index_member_all` | `hq_idx_sw_member_all` | `ts_code, l1_code, l2_code, l3_code, in_date` | 2,000 | 当前官方页面明确 2,000 | `sw-members` 的 SW2021 来源；每个 L1 代码分别抓 `is_new=N/Y` |

审计中的“direct catalog 尚未实现”只描述新的通用 direct 执行层，不代表旧 getter 不能运行。不要因此删除旧脚本，也不要把 legacy append+cleanup 路径描述成 dedicated Job 的逐页事务 upsert。

## 3. `index-pit` phase 映射

| phase | 输入来源 | 写入/发布目标 | 工作单元与业务作用 |
| --- | --- | --- | --- |
| `basic` | `index_basic` | `a_share.hq_idx_basic` | 刷新指数元数据；风格指数的筛选严格使用 `category='风格指数'` |
| `classify` | `index_classify` | `a_share.hq_idx_sw_classify` | SW2014/SW2021 分别抓 L1、L2、L3，作为成员抓取代码空间 |
| `sw-daily` | `sw_daily` | `a_share.hq_idx_sw_daily` | 日期范围按自然月拆分；保留来源的合法空行情字段和来源数值 |
| `sw-members` | SW2014=`index_member`；SW2021=`index_member_all` | `a_share.hq_idx_sw_member`、`a_share.hq_idx_sw_member_all` | 同时抓 `is_new=N` 和 `Y`，保留完整纳入/剔除区间 |
| `sw-pit` | 两张成员区间表 + A 股交易日 | `a_share.idx_sw_member_pit` | 不调用 Tushare；按开市日展开区间，校验后通过原子换表发布 |
| `style` | `hq_idx_basic` 中精确等于“风格指数”的代码 + `index_weight` | `a_share.idx_style_member_pit` | 每个指数、每个完整自然月一个单元，保存月度快照原始日期 |
| `general` | 用户显式给出的非风格指数代码 + `index_weight` | `a_share.idx_member_pit` | 与 `style` 共用分页/事务/断点逻辑，但不会混入风格指数表 |
| `all` | 上述阶段 | 上述目标 | 依赖顺序为 basic → classify → sw-daily → sw-members → sw-pit → style；只有显式传入代码时才追加 general |

每个来源页成功后，业务写入、API 审计和断点推进在同一事务中完成。阶段异常会记录失败并尽量继续后续单元；断点恢复仍需把 provider 调用视为“至少一次”，具体限制见第 8 节。

使用“最近 N 个完整自然月”时，创建任务会把当次解析出的首月和末月写入不可变断点。后续跨月恢复仍使用原范围；不能根据恢复当天日期或最后一个仍有效的指数月份重新推算，否则中途到期的指数会被误判为断点缺月。

## 4. SW2014 与 SW2021 的权威来源差异

### SW2014

- 有效日频范围固定为 **2014-02-21 至 2021-12-10（含首尾）**。
- 行业空间来自 `index_classify(src='SW2014')` 的 L1/L2/L3。
- 成员区间权威来源是 `index_member`：按单个 `index_code` 返回扁平的 `index_code/con_code/in_date/out_date/is_new`。
- PIT 展开时，每个 L1、L2、L3 行业分别根据自身成员区间生成日频成员。

### SW2021

- 有效日频范围从 **2021-12-13** 开始。
- 行业空间来自 `index_classify(src='SW2021')` 的 L1/L2/L3。
- 成员区间权威来源是 `index_member_all`：按 L1 请求，单行同时携带 L1/L2/L3 和股票代码，因此三个层级从同一条分级关系展开。

两个版本都以区间成员为权威事实，`in_date` 为首个有效日，非空 `out_date` 为最后一个有效日。`is_new=Y` 只表示当前状态，不能替代历史区间；因此来源刷新同时抓取 `N` 和 `Y`。版本切换之间的周末不生成行，实际展开只落 A 股开市日。

`index_weight` 可用于抽样交叉检查某月某指数的成分，但它的业务含义是月度快照，不应反过来覆盖申万成员区间，也不能用来虚构逐日调仓。

## 5. 分页限额：官方公布值与 J21 探测值

客户端统一按 `limit + offset` 取满页后继续翻页，但“客户端采用的数字”不一定等于“官方公布上限”。

| API | 当前采用值 | 证据分类 | 使用约束 |
| --- | ---: | --- | --- |
| `index_basic` | 8,000 | 官方公布 | 满页继续 offset |
| `index_dailybasic` | 3,000 | 官方公布 | 满页继续 offset |
| `sw_daily` | 4,000 | 官方公布 | 按自然月切片后仍允许分页 |
| `index_member_all` | 2,000 | 官方公布 | 每个 L1、每个 `is_new` 独立分页 |
| `index_member` | 2,000 | legacy getter + 实际调用验证 | doc_id=182 已失效，不能写成现行官方值 |
| `index_classify` | 10,000 | J21 探测值 | 官方只确认 `limit/offset`；该数值是实现保护值，不是服务保证 |
| `index_weight` | 5,000 | J21 探测值 | 官方建议每次请求一个完整自然月，但未公布数字页限；仍按满页 offset 防截断 |
| `index_daily` / `pro_bar(1min)` | 8,000 | 历史 getter/回归契约 | 在重新确认当前官方数字页限前，不标注为现行官方承诺 |

探测值发生变化时，应先用小范围真实请求验证返回、offset 和重复页行为，再修改契约与测试。不要仅根据旧注释提高或降低生产页长。

## 6. 当前真实验收结果

以下结果来自 2026-08-24 的真实 Tushare/API 与 `a_share` 数据库验收。

### 来源表

- `hq_idx_basic`：**12,599** 条不同指数记录。
- `hq_idx_sw_classify`：SW2014 **359** 条，SW2021 **511** 条。
- `hq_idx_sw_daily`：**1,776,557** 行，**689** 个代码，**3,311** 个交易日期，范围 **2013-01-04 至 2026-08-21**；业务键重复为 **0**。

`sw_daily` 的来源历史中存在合法的空报价/估值字段，也存在来源自身保留的 OHLC 数值异常。当前清洗保证代码、日期、名称、数值类型和非负字段等基本契约，不擅自“修正”官方历史数值。

### 申万日频 PIT

- `idx_sw_member_pit`：**37,638,259** 行。
- 日期范围：**2014-02-21 至 2026-08-24**，共 **3,043** 个开市日。
- SW2014：L1 **6,277,753**；L2 **6,277,842**；L3 **6,277,842**。
- SW2021：L1/L2/L3 各 **6,268,274**。
- 版本切换越界、层级错误、坏键、非开市日行均为 **0**。
- 表大小：**2,987,393,024 bytes**，只有按日期优先的复合 `PRIMARY KEY`，没有额外二级索引。

分类表条数与 PIT 中实际有成员的行业数不是同一指标：分类可以存在但指定历史段没有成员区间，不能为了对齐分类条数而制造 PIT 行。

### 风格指数月度快照

- 近 6 个完整自然月按 `category='风格指数'` 精确筛出 **203** 个计划代码。
- 其中 **178** 个代码至少成功返回过数据，共入库 **244,271** 行。
- **168** 个“指数 × 月份”单元返回 `no_data`；这是可审计结果，不应补假数据，也不应让一个单元阻断剩余接口。
- 五年扩展 run 13 对上述 178 个成功代码补跑此前 54 个完整自然月：计划
  **7,008** 个有效期重叠单元，**6,932** 个成功、**76** 个 `no_data`，调用
  **7,008** 次并写入 **1,390,942** 行；断点完整，暂存残留为 0。
- 合并先行 6 个月后，表中覆盖 **2021-08 至 2026-07** 共 60 个完整自然月、
  **178** 个代码、**7,982** 个成功指数/月单元和 **1,635,213** 行；业务键重复、
  坏键、负权重、类别错放、有效期越界均为 **0**。
- 共 **7,982** 个快照的权重合计范围为 **99.979 至 100.022**，没有一个超出
  99.5 至 100.5。两阶段共记录 **244** 个 `no_data` 单元，均继续执行后续单元。

### 一般指数月度快照

- 非风格控制 `000300.SH` 覆盖 **2021-08 至 2026-07** 共 **60** 个完整自然月，
  每月 300 行，共 **18,000** 行；60 个月连续且各只有一个快照日期。
- 业务键重复、坏代码、负权重和风格类别错放均为 **0**；每月权重合计范围为
  **99.988 至 100.010**。来源的小数差异按原精度保留，不做强制归一化。

### 申万月度权重交叉检查

- 对 SW2014 的 `801890.SI`、`801072.SI`、`850713.SI`（2021-11）以及
  SW2021 的 `801030.SI`、`801039.SI`、`850523.SI`（2022-01）分别调用
  `index_weight`，6 个样本均返回 `no_data`。
- 因此月度权重接口在这些申万样本上不可评价，不能据此否定或覆盖区间成员结果；
  `idx_sw_member_pit` 仍以 `index_member`/`index_member_all` 为准。
- 数据库样本 `301071.SZ` 在 2021-12-10 对应 SW2014 L1/L2/L3
  `801890.SI`/`801072.SI`/`850713.SI`，在 2021-12-13 正确切换为 SW2021
  `801030.SI`/`801039.SI`/`850523.SI`。`000001.SZ` 在 2014-02-20 为 0 层，
  在 2014-02-21、2021-12-10、2021-12-13 均为 3 层。

## 7. 官方资料

- [指数基本信息 `index_basic`（doc_id=94）](https://tushare.pro/document/2?doc_id=94)
- [指数日线行情 `index_daily`（doc_id=95）](https://tushare.pro/document/2?doc_id=95)
- [大盘指数每日指标 `index_dailybasic`（doc_id=128）](https://tushare.pro/document/2?doc_id=128)
- [指数历史分钟行情 `idx_mins`（doc_id=419）](https://tushare.pro/document/2?doc_id=419)
- [申万行业分类 `index_classify`（doc_id=181）](https://tushare.pro/document/2?doc_id=181)
- [申万行业日线 `sw_daily`（doc_id=327）](https://tushare.pro/document/2?doc_id=327)
- [申万行业成分 `index_member_all`（doc_id=335）](https://tushare.pro/document/2?doc_id=335)
- [指数成分和权重 `index_weight`（doc_id=96）](https://tushare.pro/document/2?doc_id=96)
- [积分与单独权限说明（doc_id=108）](https://tushare.pro/document/1?doc_id=108)

`index_member` 的旧链接 `doc_id=182` 在本次复核时返回 404，因此仅保留为失效链接的审计事实，不把它列为当前官方契约。该接口现用参数、字段和 2,000 页长来自 legacy getter 与 live 验证。

## 8. 已知限制与操作约束

1. `index_weight` 只表示来源返回的月度快照。数据库表名中的 PIT 表示“按来源日期可回看”，不表示拥有每天一张权重表。
2. provider 已返回响应、但逐页事务尚未提交时，如果进程被 `kill -9`，恢复后该页可能再次调用一次。数据库业务键和事务可防止重复落库，但无法撤销已经消耗的 provider 调用额度。
3. `no_data` 是终态证据。批量任务记录后继续下一单元，并以 `partial_failed` 暴露覆盖缺口；不能把空结果伪装为成功有数据。
4. 同一时刻不得运行两个写入 `a_share` 的任务。特别是 SW PIT 的 staging/原子发布和其他 A 股写入不能并发。
5. `hq_idx_basic` 是当前元数据，不是历史元数据 PIT。历史月份的名称、类别、发布方等不能仅凭当前基础表推断当时状态。
6. 申万 PIT 的最终表为控制总体积只保留复合主键。新增二级索引前必须以真实查询负载和容量预算验证，不能默认“索引越多越好”。

## 9. 后续复核清单

- 官方页面或权限规则变化时，重新确认积分、数字页限和接口参数，并同步 getter
  注释、endpoint spec、测试和本文。
- 扩大风格或一般指数范围时，继续按完整自然月串行执行，并在每次运行后核对断点、
  API 审计、重复键、类别路由和权重合计。
