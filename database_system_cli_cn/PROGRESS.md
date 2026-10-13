# Progress

## 当前状态

- 2026-10-13 公开源码准备：原创代码及旧声明统一为 MIT，保留全部 getter 和兼容层；
  配置、token、数据和第三方数据再分发权不包含在源码中。新环境离线测试使用合成配置，
  `index-pit --phase basic` dry-run 不再提前加载私人数据库配置。CN 仍独立安装。
- 2026-10-13 已公开干净源码仓库，109 项离线测试通过；匿名克隆验证通过，旧仓库保持私有。

CN 产品可独立安装运行，旧 getter/controller 与新的 CLI/Menu 共存；业务数据固定写入
`a_share`，控制状态写入 `system_cn`，日志产品名统一为 `J21 database`。

已完成：

- 原版 `basis`、getter、去重模块和中文主控入口保留在项目根目录。
- 新包使用 `src/fdp_cn`，没有重复的 `src/database_system_cli_cn`。
- `poetry run j21`、93 个接口变体、88 张目标表、direct/legacy_compat 两种后端已接通。
- 93 个变体已封闭划分为 71 个 10000 积分可执行接口、17 个单独开通接口、3 个外部
  实时接口和 2 个退役/无正确映射接口；92 个物理 getter 全部有 catalog 对应项。
- CLI 和 Menu 共用同一 `IngestService`；71 个接口均可单独选择，纯代码列表、
  代码+日期段和无代码接口按各自作用域路由。兼容子进程的超时、非零退出、启动失败或
  调度异常均形成 `partial_failed` 并继续后续接口。
- 主控接口列表脚本会先加入自己的项目根路径，从任意当前工作目录直接运行都能导入
  `basis`。
- `IndexPitJob`、`j21 ingest index-pit` 和中文 Menu 指数向导已加入；支持 dry-run、
  显式执行确认、API 预算、断点续跑、逐页事务和可审计部分失败。
- Menu 的 `style/general` 同时支持最近 N 个完整自然月和精确完整自然月日期范围。
- 8 个历史指数 getter、官方页面、实际代码和 MySQL 结果已完成审计，见
  `docs/index_pit_research.md`。
- 一句话初始化与云演进方案已经形成，目标命令为
  `j21 init <cn|us|all> --years N`；它安装清洗数据库生成的签名数据包，不调用 provider。
  当前完成的是可落地契约，不虚称仓库级 launcher/数据包安装器已经实现。

## 真实指数验收（2026-08-24）

- `hq_idx_basic`：12,599 条不同指数。
- `hq_idx_sw_classify`：SW2014 359 条，SW2021 511 条。
- `hq_idx_sw_daily`：1,776,557 行、689 个代码、3,311 个日期，覆盖
  2013-01-04 至 2026-08-21，业务键重复 0。
- 两张申万成员来源已按所有版本/层级和 `is_new=N/Y` 刷新。
- `idx_sw_member_pit`：37,638,259 行、3,043 个开市日，覆盖 2014-02-21 至
  2026-08-24；版本越界、错误层级、坏键、非开市日和重复业务键均为 0。
- `idx_sw_member_pit` 实际大小 2,987,393,024 bytes，仅保留日期优先复合主键，满足
  单表小于 5 GB 的要求。
- 风格指数近 6 个完整月已先行验证：203 个计划代码中 178 个至少成功一次，落库
  244,271 行；168 个指数/月单元为可审计 `no_data`。
- 风格指数五年扩展 run 13 已完成：7,008 个计划单元中 6,932 个成功、76 个
  `no_data`，写入 1,390,942 行。与先行 6 个月合并后覆盖 2021-08 至 2026-07
  共 60 个月、178 个代码、1,635,213 行，重复键和 99.5–100.5 之外的权重合计均为 0。
- 非风格控制 `000300.SH` 已覆盖 2021-08 至 2026-07 共 60 个月、18,000 行；缺月、
  重复键和错放风格类别均为 0，月度权重合计范围 99.988–100.010。
- SW2014/SW2021 六个 L1/L2/L3 `index_weight` 样本均返回 `no_data`；成员区间继续以
  `index_member`/`index_member_all` 为准。切换边界样本与两版成员区间完全一致。

## 最终代码验证（2026-08-30）

- CN 全量离线测试：107/107 通过。
- `compileall` 通过；`poetry check --lock` 通过，仅有 Poetry 旧字段弃用警告。
- 实际 `poetry run j21 ingest list --output json` 返回 93 项；实际
  `poetry run j21 ingest all --from 2026-08-01 --to 2026-08-02 --output json`
  返回 71 个唯一、全部 `points_tier=10000` 的 dry-run 项。
- 实际中文 Menu 普通积分路径显示同样 71 项，并在确认处取消，未调用 API、未写库。
- 实际 `index-pit --phase all` dry-run 生成 10,719 个工作单元、预计 10,567 次 API
  调用和 7 张目标表；没有发出 provider 请求。
- 主控接口列表从 `/private/tmp` 直接运行退出码为 0，可正常导入 `basis`。
- focused index PIT、CLI/Menu、权限、物理 getter、失败隔离、断点、分页、路由和
  staging 契约均有回归覆盖。
- 真实写入始终串行执行，没有并发运行第二个 `a_share` writer。

## 下一步

1. 按 `docs/one_command_data_delivery.md` 实现仓库级唯一 launcher、Bundle verifier、
   断点下载和 staging installer；在取得再分发权前仅使用 demo/BYO 私有频道。
2. 后续硬化 PIT validator：显式校验交易日日集合双向相等、来源 anti-join，以及每月
   单快照/权重和范围；这些不影响当前已验收的成品表。
