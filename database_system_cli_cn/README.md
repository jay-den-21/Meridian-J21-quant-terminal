# database_system_cli_cn

`database_system_cli_cn` 是独立运行的中文 Tushare 数据产品，目标数据库固定为
`a_share`。它不再依赖 `qtdb_pro_rep`，也不把 Tushare 逻辑放进兄弟项目
`database_system_cli`。项目目录和 Python 包名保持不变，运行日志中的产品展示名为
`J21 database`。

## 目录结构

项目名只出现一次；Python 包使用较短且不会与 `fdp` 冲突的 `fdp_cn`：

```text
database_system_cli_cn/
├── src/fdp_cn/                  # 新 CLI、中文 Menu、接口清单和 direct Job
├── basis/                       # 保留的复刻框架
├── get_ph_data_from_ts/         # 保留的历史 getter
├── get_rt_data_from_ts/         # 保留的实时 getter
├── deal_data/                   # 保留的去重/缺失处理
├── 主控程序/                     # 原有脚本入口
└── tests/
```

没有 `database_system_cli_cn/src/database_system_cli_cn` 这一层。

## 两种执行后端

CLI 和 Menu 使用同一个 `IngestService`，但不会假装 93 个旧接口已经全部重写：

- `direct`：首批 8 个已审查接口，使用独立 HTTPS client、字段检查、分页、页面事务、
  upsert、API 记录和断点。包括交易日历、股票基础信息、全量股票基础信息、申万分类、
  指数基础信息、股票日线、申万日线和筹码分布。
- `legacy_compat`：其余历史接口在独立子进程中调用本项目原有 getter。单个接口异常会
  记录失败并继续下一个接口，不会让整批 Python 进程直接退出。

两种后端都写 `a_share`，但写入语义不同。`legacy_compat` 保留原来的 append 后清理；
`direct` 使用事务 upsert。不要同时运行两个写入任务。

## 安装和命令

```bash
cd "/Users/boqingxin/tandon MSCS/My_Own/financial-data-platform/database_system_cli_cn"
/Users/boqingxin/.local/bin/poetry install
```

列出全部 93 个接口：

```bash
poetry run j21 ingest list
```

默认都是 dry-run，只显示计划，不调用 API、不写数据库：

```bash
poetry run j21 ingest init --from 2026-08-01 --to 2026-08-19
poetry run j21 ingest all --from 2026-08-01 --to 2026-08-19
poetry run j21 ingest tushare \
  --endpoint daily \
  --from 2026-08-01 \
  --to 2026-08-19
```

真实执行必须同时给出两个开关：

```bash
poetry run j21 ingest init \
  --from 2026-08-01 --to 2026-08-19 \
  --execute --yes

poetry run j21 ingest all \
  --from 2026-08-01 --to 2026-08-19 \
  --execute --yes
```

`init` 目前按顺序运行 15 个基础/依赖 getter，并建立 `system_cn` 运行记录表。
`all` 精确运行 71 个经审查可用于 10000 积分档的历史接口，排除 17 个单独开通、
3 个外部实时和 2 个已废弃/无有效映射的接口。CLI 和 Menu 都从同一 catalog 生成计划；
71 个接口均可用稳定 key 或唯一 getter 短名逐个选择。完整清单见
`docs/tushare_10000_point_catalog.md`。

积分档位与分页上限是两个字段：`points_tier=10000` 表示该接口已归入 10000 积分账号
清单，`page_limit` 只表示单次请求行数，不参与权限筛选。新闻联播、美股日线和美股
复权日线已按当前官方权限表归为单独开通，不会再误入 `all`。

批量没有显式 `--codes` 时，`cyq_chips` 会使用保留 getter 从股票基础表解析代码；显式
提供代码时才走 direct。代码只传给需要代码范围的接口，不会再传给 `trade_cal` 等不
接受代码的接口。CLI 和 Menu 都支持纯代码列表以及代码+日期段两类 getter；兼容子进程
超时、非零退出、启动失败或调度异常都会记为当前接口失败并继续。单接口参数错误会记录
为部分失败，鉴权和数据库错误仍停止批次。

筹码分布的 direct 入口按“每只股票一个日期段”执行，单页 `limit=6000`，然后使用
`offset=0,6000,12000,...` 分页；不是按每天、每只股票各调用一次。

## 指数历史与 PIT

查看指数任务计划：

```bash
poetry run j21 ingest index-pit --phase basic
poetry run j21 ingest index-pit --phase sw-daily \
  --from 2013-01-01 --to 2026-08-24
poetry run j21 ingest index-pit --phase style --months 6
poetry run j21 ingest index-pit \
  --phase general --codes 000300.SH --months 60
```

和其他入口一样，以上命令默认不调用 API、不写库。执行时补 `--execute --yes`；长任务
建议同时设置 `--max-api-calls`，中断后通过 `--resume-run-id RUN_ID` 续跑。

这个流程会刷新指数基础表、两版申万分类、申万日线和两张申万成员区间来源表，并生成：

- `idx_sw_member_pit`：按真实 A 股开市日展开的 SW2014/SW2021 L1/L2/L3 成员。
- `idx_style_member_pit`：精确 `category='风格指数'` 的月度权重快照。
- `idx_member_pit`：显式选择的非风格指数月度权重快照。

月度权重不会被伪造成每天的数据。SW2014 使用 `index_member`，SW2021 使用
`index_member_all`，两个来源都抓 `is_new=N/Y`。完整接口审计、分页依据、版本切换和
真实数据库验收结果见 `docs/index_pit_research.md`。

## 中文 Menu

```bash
poetry run j21 menu
```

Menu 默认简体中文，可切换英文，并可按单接口、类别、初始化或普通积分全集生成计划。
它与 CLI 共用同一计划和执行服务；确认默认为取消，取消不会构造 provider client 或
写数据库。

## 一句话数据初始化方案

面向最终用户的目标命令与 provider 抓取明确分离：

```bash
j21 init cn --years 5
j21 init us --years 5
j21 init all --years 5
```

这里的 `init` 安装从清洗数据库生成并签名的 J21 Data Bundle，不读取 Tushare/EODHD
密钥，也不调用 getter；`all` 表示 CN + US，不表示执行全部接口。当前两个子项目都注册
了 `j21`，最终由仓库级唯一 launcher 路由两个独立市场产品，二者不互相 import。

数据包 manifest、分片校验、断点、staging/发布、PIT 边界、MySQL 上云步骤和数据授权
门槛见 `docs/one_command_data_delivery.md`。在取得明确再分发授权前，只能发布可再分发
demo 数据包或用户自有许可下的私有数据包，不能把个人 Tushare 权限产出的清洗库公开
转售。

## 配置与安全边界

- 私有配置：`config/ts2db_config.yaml`，已被 Git 忽略。
- 示例配置：`config/ts2db_config.example.yaml`。
- 可选环境变量：`FDP_CN_DATABASE_URL`、`TUSHARE_TOKEN`。
- 无论使用 YAML 还是环境变量，数据库名必须精确为 `a_share`。
- CN 自己的任务、断点和 API 记录放在 `system_cn`；业务表放在 `a_share`。
- 不再提供 `qtdb_pro_rep -> a_share` 历史搬库工具。

## 快速测试

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
/Users/boqingxin/.local/bin/poetry check --lock
```

当前回归覆盖 93/92 目录与物理 getter、71 项积分清单、日线、申万日线、股票基础表、
筹码 6000 分页、财报兼容子进程、失败后继续、CLI dry-run、中文 Menu、指数分页/断点、
申万版本切换、月度权重路由和 staging 发布保护。真实 API/数据库执行仍应先从单接口、
小日期窗口开始。
