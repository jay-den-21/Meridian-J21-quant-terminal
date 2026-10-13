# database_system_cli_cn

## 1. 产品定位

公开版本边界（2026-10-13）：本项目由作者确认为原创，源码按仓库根目录 MIT
许可证发布。Tushare 权限、配置、数据和再分发许可不包含在源码许可中。CN 使用
独立 Python 3.11.3 环境；不能与 US CLI 的 SQLAlchemy 2 环境混用。

`database_system_cli_cn` 是仓库内独立的中文 Tushare 数据产品。它负责把 A 股及
相关市场数据写入 MySQL `a_share`，不依赖兄弟项目 `database_system_cli`。

## 2. 原版保留层

下列目录继续保留既有版本的类名、getter 调用方式、字段映射和运行入口：

- `basis/`
- `deal_data/`
- `get_ph_data_from_ts/`
- `get_rt_data_from_ts/`
- `主控程序/`

这些目录没有被移动到 `src`。主控脚本只补项目根路径，使它可以从任意当前工作目录
直接运行；框架日志中的产品展示名统一为 `J21 database`。

## 3. 新适配层

新代码位于 `src/fdp_cn/`。不存在
`src/database_system_cli_cn/`，因此项目名不会在路径中重复。

CLI 和 Menu 共用 `IngestService`：

- 8 个已审查接口使用 direct client、分页、字段检查、事务 upsert 和断点。
- 其余可运行历史接口通过独立子进程调用原版 getter；单接口失败后批次继续。
- 93 个接口变体、88 张目标表均可在清单中查看。

## 4. 命令

项目本地命令为：

```bash
poetry run j21 ingest list
poetry run j21 ingest init --from 2026-08-01 --to 2026-08-19
poetry run j21 ingest all --from 2026-08-01 --to 2026-08-19
poetry run j21 ingest tushare --endpoint daily --from 2026-08-01 --to 2026-08-19
poetry run j21 menu
```

默认只生成计划。真实调用 API 和写数据库必须同时提供 `--execute --yes`。

## 5. 数据边界

- 业务表：`a_share.hq_*`
- 新 CLI 的任务、API 记录和断点：`system_cn`
- 私有配置：`config/ts2db_config.yaml`，不进入 Git
- 示例配置：`config/ts2db_config.example.yaml`

direct 与原版兼容 writer 不得同时写同一张表。`database_system_cli` 不得导入本项目，
也不得写入或删除 `a_share`。

## 6. 当前范围

首批 direct 接口是交易日历、上市股票基础表、全状态股票基础表、指数基础信息、
申万行业分类、A 股日线、申万日线和筹码分布。筹码分布按“一只股票 + 整个日期段”请求，每页上限
6,000 行并推进 offset。其余历史 getter 先保留原逻辑，逐个审查后才能迁入 direct。

## 7. 指数历史与 PIT

指数历史使用独立的 `IndexPitJob`，从命令行和中文 Menu 进入同一套执行逻辑：

```bash
poetry run j21 ingest index-pit --phase basic
poetry run j21 ingest index-pit --phase sw-daily --from 2013-01-01 --to 2026-08-24
poetry run j21 ingest index-pit --phase style --months 6
poetry run j21 ingest index-pit --phase general --codes 000300.SH --months 60
```

默认仍为 dry-run；真实执行需要 `--execute --yes`。大范围任务还可以使用
`--max-api-calls` 限制整次运行的 API 调用预算，并用 `--resume-run-id` 从已提交断点继续。

来源和目标：

- `index_basic` 刷新 `hq_idx_basic`。
- `index_classify` 同时保存 SW2014/SW2021 的 L1/L2/L3。
- `sw_daily` 从 2013 年起按自然月分页刷新 `hq_idx_sw_daily`。
- SW2014 成员以 `index_member` 的历史区间为准；SW2021 以 `index_member_all` 的分级历史区间为准，两者都抓取 `is_new=N/Y`。
- `idx_sw_member_pit` 只按 A 股开市日展开：SW2014 为 2014-02-21 至 2021-12-10，SW2021 从 2021-12-13 开始，`out_date` 包含当日。
- 精确 `category='风格指数'` 的 `index_weight` 月度快照写入 `idx_style_member_pit`；显式指定的非风格指数写入 `idx_member_pit`。

`index_weight` 是月度快照，不会被复制成日频权重。申万 PIT 的成员区间是权威来源，
申万 `index_weight` 只作非阻断交叉检查。实测申万 PIT 为 37,638,259 行、
2,987,393,024 bytes，只保留日期优先的复合主键，使单表体积保持在 5 GB 以内；
发布使用 staging 校验和原子换表。

真实月度验收已覆盖 2021-08 至 2026-07：风格表为 178 个成功代码、1,635,213 行，
一般指数控制 `000300.SH` 为 60 个月、18,000 行。两表业务键均无重复，所有快照权重
合计均在 99.5 至 100.5；来源明确返回的 `no_data` 被记录为部分失败并继续后续单元。

每个来源页成功后，业务写入、API 审计和断点在同一事务中提交。单个无数据、权限或
耗尽重试的来源单元会留下可审计失败并继续后续单元；鉴权、预算和数据库契约错误停止
运行。详细接口审计和真实落库结果见 `docs/index_pit_research.md`。

## 8. 10000 积分 CLI/Menu 清单

93 个 catalog 变体与 92 个物理 getter 的权限分组为：71 个 10000 积分档历史接口、
17 个单独开通接口、3 个外部实时接口、2 个退役或无正确映射接口。CLI 和 Menu 从同一
`IngestService` 生成清单、单接口、类别和 `all` 计划。

`AccessSpec.points_tier` 表示 J21 已验证/归类的账号档位，不冒充每个接口的精确最低
积分。`PaginationSpec.page_limit` 只表示每次请求的行数，绝不参与积分筛选。当前官方
权限表将分钟数据、美股日线和新闻资讯列为独立权限，因此 `cctv_news`、`us_daily` 和
`us_daily_adj` 不进入默认 `all`。

批量执行按接口解析作用域。无代码时，唯一需要显式股票范围的 direct `cyq_chips` 回退
到保留 getter 自动解析股票表；有代码时使用 direct。候选代码不会传给不接受代码的
接口；纯代码列表和代码+日期段 getter 在 CLI/Menu 使用相同作用域。兼容子进程超时、
非零退出、启动或调度失败均记录当前接口后继续；鉴权和存储完整性错误全局停止。完整
71 项清单及覆盖证据见 `docs/tushare_10000_point_catalog.md`。

## 9. 一句话数据交付与云边界

最终公开入口是仓库级唯一 `j21`：

```bash
j21 init <cn|us|all> --years 5
```

该命令安装从清洗数据库生成的签名 J21 Data Bundle，不读取 provider 密钥、不调用
getter。`all` 表示 CN + US 市场产品。provider 操作保留为高级 `source cn` 工作流；
CN 和 US 不互相 import，也不写对方 schema。

数据包按 manifest + detached signature + DDL + 独立校验分片 + 质量/lineage 证据发布；
断点身份为 `release_id + dataset_key + partition + sha256`。安装顺序为验权/验签、续传、
staging 导入、业务键/PIT 验证、原子发布。MySQL 先继续承担查询和任务账本，随后把不可变
数据包放入对象存储、把服务状态迁到 TLS 托管 MySQL，并由无状态 worker 运行同一 Job。

个人 Tushare 服务许可不能推导出再分发权。公开数据频道必须先取得明确再分发授权；
此前只支持可再分发 demo 或用户自有许可的私有频道。完整契约见
`docs/one_command_data_delivery.md`。
