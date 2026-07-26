# database_app 项目设计文档

本文档描述 `financial-data-platform/database_app/` 子项目。`PROJECT.md` 是项目规格文字源文件；`PROJECT.html` 是同步生成的浏览器友好版，用于快速检查项目范围、架构和运行方式。

`database_app` 与 `database_system_cli` 平级。它是一个轻量 EODHD API Code Generator App 和 API playground，不是数据库 ingestion 主线的一部分。

## 1. 项目目标

`database_app` 面向小规模 equity research / sell-side research 查询。用户在页面中选择 asset、endpoint、symbol / provider symbol、日期范围、period、format 和 endpoint-specific 参数后，App 自动生成：

- direct URL
- Python `requests` 代码
- curl 命令
- JavaScript `fetch` 示例

App 也可以用 Login / Config 中保存的本地 token 实际调用 EODHD API，在页面下方展示 preview table，并支持 CSV 导出。`EODHD_API_KEY` 只作为 scripted run fallback。

设计灵感来自 Wind API 工具形态：先选择数据域和函数/endpoint，再填参数，最后生成可复制代码并展示结果预览。Wind 只作为工作流参考；endpoint 行为、套餐权限和参数依据以 EODHD 官方文档为准。

v0.2 增加股票选择工作流：用户可以先从交易所 symbol list 或 EODHD Filtered Pools 加载股票池，勾选股票，或粘贴逗号/换行分隔的 symbol 自动匹配。选中股票后再进入正常 endpoint 参数筛选，例如日期、period、format 和 endpoint-specific options。

v0.4 把产品形态从普通 web form 推向本地桌面工具：主窗口使用 Wind 风格 ribbon，WSD/WSS/WST/WSET/TDays 作为快捷入口；页面内部用 task tab 和 MDI-like child window 承载不同工作区；代码区和输出结果保持像 Wind 代码生成器一样的上下文并列关系。当前仍由本地 HTTP server 驱动，但用户入口以 `.app` wrapper / 本地桌面 review 为主。

v0.5 把前端交互从“大块 endpoint 工作区”收敛为 single workspace：主屏只保留中英双语 function toolbar、已确认请求摘要、code generation 区域和 Execute API result 区域。所有 endpoint-specific 配置、股票池、ticker import、日期和输出格式都进入 3-step floating wizard。Wizard 内的 draft request 不会影响主屏；只有 Confirm 后才更新 codegen 和 Execute 使用的 confirmed request。

v0.6 把 Stocks wizard 的候选加载从 EODHD API 改成 read-only MySQL pool browser。Pool browser 只读 `database_system_cli/.env` 中的 `FDP_DATABASE_URL` 或 `FDP_DB_*` 配置，并查询现有 `us_share.instrument`，不写数据库、不新增 schema、不消耗 EODHD API call。EODHD token 只用于 Execute API 和 Instrument Lookup。

v1.1 加入本地 Mac 分发打包和 CodeGen 下载入口。`scripts/package_macos_app.sh` 会生成 `.app`、`.dmg`、`.pkg`，并把 DMG/PKG 复制到 `site/downloads/`，使 `site/index.html` 可以继续提供本地构建产物下载。当前是 local developer distribution：可用于本机安装和个人测试，但公开分发仍需要 Apple Developer ID signing 和 notarization。

v1.2 曾将个人首页、Meridian landing 和 terminal prototype 合并到 `database_app/site/`。v1.3 已完成边界拆分：`database_app/site/` 恢复为 CodeGen-only 产品/下载页；个人首页和 J21 Terminal 分别迁移到仓库顶层 sibling `personal_site/` 与 `j21_terminal/`，通过相对 URL 跳转，不再共享页面路由、CSS、JavaScript 或产品资源。

Wind 学习依据：

- 用户提供的 `Wind_API接口说明_2025_.pdf`，文档日期 2025-04-10。
- 用户提供的 Wind client 文档链接：`https://www.kancloud.cn/stratorway/wind-client/1457552`。
- PDF 中 Wind API 数据函数包括 WSD、WSS、WST、WSI、WSQ、WSET、EDB；代码生成器定位是通过导航逐步选择参数、生成取数代码，并同步展示取数结果。
- PDF 中日期函数包括 `tdays`、`tdaysOffset`、`tdayscount`，日期宏支持 `-5D`、`-10TD` 这类相对日期/交易日表达。因此本 App 的 v0.4 加入了 `Date helper: T+n`，把 anchor date 和 offset 转换为实际 `from` / `to` / `trade_date` 字段。

## 2. 与 database_system_cli 的边界

硬边界：

- 不修改 `database_system_cli` 源码。
- 不修改 `database_system_cli` Poetry 环境。
- 不修改 MySQL schema。
- 不新增 Alembic migration。
- 不写入数据库。
- 不 import `database_system_cli` 内部模块。
- 不提交真实 `.env`、API key、token。

允许的只读边界：

- `database_app` 可以读取 `database_system_cli/.env` 中的 DB 连接配置，作为本地 pool browser 的 fallback。
- `database_app` 可以只读查询现有 `us_share.instrument` 字段：`provider_symbol`、`symbol`、`name`、`exchange`、`asset_type`、`is_active`、`market`、`provider`。
- 如果 DB 配置缺失、连接失败或 schema 不可用，App 必须显示 explicit unavailable，不得 silent fallback 到 EODHD API。

设计原因：

- `database_system_cli` 是可追踪、可验证的数据库 ingestion / validation / research read layer。
- `database_app` 是 API playground / code generator，生命周期和风险边界不同。
- 当前实现避免复杂 import path 和跨项目隐式耦合。

未来如果两边都稳定复用 EODHD endpoint/url/validation 逻辑，应抽成独立 shared package，而不是让 `database_app` 直接依赖 `database_system_cli`。

## 3. 功能范围

当前实现股票 / equity 查询工作流。前端预留 Bonds、Funds、Indices 按钮，但这些资产仍是 roadmap。

已实现：

- Endpoint registry / endpoint specs。
- Dynamic UI form renderer。
- Single-workspace frontend with a compact function toolbar。
- P0 function cards: Historical Price / 历史行情、Bulk Last-Day EOD / 批量日终行情、Latest Snapshot / 最新快照、Intraday Bars / 分钟线、Instrument Lookup / 证券搜索。
- 3-step floating wizard: Stocks / 选股、Parameters / 参数、Review / 确认。
- Read-only MySQL pool browser for stock candidates, backed by existing `us_share.instrument`。
- Pool Resources categories: Preset Pools、Exchange、Asset Type、Index Assets、Sectors disabled。
- Default pool: active US common stocks on NYSE/NASDAQ/AMEX/ARCA/NYSE ARCA/BATS。
- Index Assets shows index instruments only, not index constituents。
- Sectors is disabled until a sector/industry taxonomy or membership source exists。
- Advanced Filter modal for DB-supported filters: active-only、exclude OTC/PINK、preset pool、asset type、exchange、text search。
- Left candidate list and right selected list with checkbox, double-click, and Command/Ctrl-click selection semantics。
- CSV/TXT and pasted-text ticker import, parsed locally in the browser without uploading files。
- Draft request vs confirmed request state separation; Execute API only uses the confirmed request。
- Previous Execute result is retained and marked as previous/stale after a new Confirm。
- Imported ticker validation resolves against active DB `symbol` or `provider_symbol` exact matches, case-insensitively; unknown or guessed aliases are rejected。
- `Date helper: T+n` for business-day or calendar-day offsets into date fields。
- Program language selector that switches generated code tabs。
- Login / Config token dialog backed by server-side token store。
- Request validation and normalization。
- Direct URL generation。
- Python `requests` generation。
- curl generation。
- JavaScript `fetch` generation。
- Real EODHD API execution through stored local token, with `EODHD_API_KEY` as fallback。
- JSON / CSV response parsing。
- Data preview table。
- Browser CSV export。
- API key redaction。

不做：

- 大规模批量下载器。
- 数据库写入。
- 用户登录和权限系统。
- 请求模板持久化。
- Excel `.xlsx` 导出。
- C++ 代码生成。
- 多资产完整支持。
- 官方指数成分股 universe，除非订阅/官方证据明确支持并有 membership source。
- sector/industry member pools，除非新增官方/授权 taxonomy source。
- 在 P0 中不展示申万、S&P/MSCI、券商行业指数等“知名行业指数池”；除非有官方/授权成分股来源。Sector/industry pools 当前禁用，不得冒充指数成分股或官方行业成员池。

## 4. 技术栈

当前实现使用 Python 标准库和原生前端：

- Python `http.server.ThreadingHTTPServer`
- Python `urllib.request`
- Python `csv`
- SQLAlchemy Core read-only queries for pool browser
- PyMySQL for MySQL connectivity
- 原生 HTML / CSS / JavaScript
- macOS `.app` wrapper + DMG/PKG build script
- static CodeGen product/download page under `site/`
- pytest 测试
- ruff 静态检查

仍然不引入 FastAPI/Jinja2/Uvicorn/React。新增 `sqlalchemy>=2.0` 和 `pymysql>=1.1` 的原因是 pool browser 需要快速、只读、安全地查询现有 MySQL `instrument` 表，避免每次打开股票池都调用 EODHD API。FastAPI + Jinja2 迁移可以作为 P1/P2，在依赖边界稳定后执行。

## 5. 目录结构

```text
financial-data-platform/
  database_system_cli/
  personal_site/
  j21_terminal/
  database_app/
    .gitignore
    pyproject.toml
    README.md
    PROJECT.md
    PROJECT.html
    PROGRESS.md
    docs/
      OFFICIAL_ENDPOINTS.md
      TECHNICAL_DESIGN.md
    site/
      index.html
      styles.css
      PLAN.md
      assets/
        app-preview.svg
      downloads/
        .gitignore
    src/
      eodhd_codegen_app/
        __init__.py
        __main__.py
        client.py
        codegen.py
        cost.py
        endpoints.py
        request_model.py
        server.py
        token_store.py
        universe.py
        universe_db.py
        static/
          index.html
          styles.css
          app.js
    tests/
      test_client.py
      test_codegen.py
      test_cost.py
      test_endpoint_registry.py
      test_request_model.py
      test_server_security.py
      test_token_store.py
      test_universe.py
      test_universe_db.py
      test_static_app.py
    scripts/
      run_local.command
      package_macos_app.sh
```

模块职责：

- `endpoints.py`：endpoint registry、参数 spec、官方文档链接、套餐依据说明、inventory-only 状态。
- `request_model.py`：请求参数校验和 normalization。
- `codegen.py`：生成 direct URL、Python、curl、JavaScript。
- `cost.py`：估算 endpoint API call cost，Bulk 请求需要后端确认。
- `client.py`：服务器端真实 EODHD HTTP 调用、JSON/CSV 解析、token redaction、preview rows。
- `token_store.py`：环境变量 / 本地 app config token 状态、保存、删除；Keychain 是可选路径，不作为默认阻塞保存路径。
- `universe.py`：DB-backed pool menu/load contract、preset pool 和 disabled taxonomy/index-constituent 边界。
- `universe_db.py`：读取 DB env、建立 SQLAlchemy engine、只读查询 `us_share.instrument`。
- `server.py`：HTTP route、静态文件、API response、本机请求 guard。
- `static/`：single workspace、function toolbar、3-step request wizard、T+n date helper、代码区、结果区、样式和浏览器端交互。
- `tests/`：验证参数边界、代码生成、执行解析、token redaction、registry 完整性、DB pool 查询边界和前端 pool state 回归点。

## 6. 运行方式

从仓库根目录进入 `database_app`：

```bash
cd "/Users/boqingxin/tandon MSCS/My_Own/financial-data-platform/database_app"
```

仅生成代码不需要 API key；真实执行 API 建议在页面右上角 `Login / Config` 保存 EODHD API token。保存后的 token 优先于 shell 里的 `EODHD_API_KEY`。

Stocks wizard 的候选池不需要 EODHD token，但需要可读的数据库连接配置。App 会先读当前进程环境变量，再只读 fallback 到 sibling `database_system_cli/.env`：

```text
FDP_DATABASE_URL
或 FDP_DB_HOST / FDP_DB_PORT / FDP_DB_USER / FDP_DB_PASSWORD / FDP_DB_NAME
```

缺少 DB 或连接失败时，App 仍可启动、生成代码和 Execute API；只是 Pool Resources 面板会显示 database pool source unavailable，不会自动改打 EODHD API。

启动本地 server：

```bash
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m eodhd_codegen_app --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

停止 server：

```text
在运行 server 的 Terminal 中按 Ctrl+C
```

桌面 review wrapper：

```bash
./scripts/run_local.command
```

生成本地 macOS 安装产物：

```bash
./scripts/package_macos_app.sh
open "dist/EODHD Code Generator.app"
open "dist/EODHD-Code-Generator-1.0.0.dmg"
```

该脚本会生成：

- `dist/EODHD Code Generator.app`
- `dist/EODHD-Code-Generator-1.0.0.dmg`
- `dist/EODHD-Code-Generator-1.0.0.pkg`
- `dist/SHA256SUMS.txt`
- `site/downloads/EODHD-Code-Generator-1.0.0.dmg`
- `site/downloads/EODHD-Code-Generator-1.0.0.pkg`
- `site/downloads/SHA256SUMS.txt`

CodeGen 静态产品 / 下载入口：

```bash
open site/index.html
```

`site/index.html` 只展示 EODHD Code Generator、安装说明、本地安全边界和由打包脚本生成的下载链接。该目录不包含个人主页、Meridian 或 terminal view，也不加载 GSAP。

个人站和 J21 Terminal 位于仓库 sibling 根目录。需要同时检查跨产品跳转时，从仓库根目录启动静态服务器：

```bash
python3 -m http.server 8766 --directory .
```

- `http://localhost:8766/personal_site/`：Jayden21 个人首页及项目外链。
- `http://localhost:8766/j21_terminal/`：Meridian landing；其真实 anchor 经现有动效进入单独启动在 `http://127.0.0.1:8765/` 的只读 Research Terminal。
- `http://localhost:8766/database_app/site/`：CodeGen 产品 / 下载页。

仓库根静态预览不得占用 `8765`；该端口保留给
`research_terminal/` 构建后的 React UI 与同源 GET-only API。

该 wrapper 会用随机本地端口绑定 `127.0.0.1` 并打开系统浏览器。生成的 `.app` 会复制 `database_app` 源码、文档和纯 Python 依赖到 bundle resources，移动 `.app` 后不再依赖当前 checkout 路径。它不是 Electron/Tauri/PyInstaller bundle，不会复制 Python runtime；目标是本机可安装、可下载、可 review。目标机器需要 Python 3.11+，或用 `PYTHON_BIN` 指向兼容 Python。

直接启动脚本会在启动 server 前 `unset EODHD_API_KEY`，因此桌面式启动路径只使用 `Login / Config` 中保存的 token。

公开下载边界：

- 当前 DMG/PKG 是 unsigned/not notarized developer artifacts。
- 对外发布前需要 Developer ID certificate、notarization、stapling 和 checksum。
- `site/PLAN.md` 记录 CodeGen 下载页上线计划、发布存储选项和 production checklist。

## 7. Endpoint 白名单

所有可执行 endpoint 必须有官方文档依据。完整依据记录在 `docs/OFFICIAL_ENDPOINTS.md`。

| Endpoint id | EODHD path | 用途 | 格式 | 状态 |
| --- | --- | --- | --- | --- |
| `historical_eod` | `/api/eod/{provider_symbol}` | 一个或少量 symbol 的历史 EOD OHLCV | JSON / CSV | implemented |
| `intraday` | `/api/intraday/{provider_symbol}` | 1m/5m/1h intraday bars | JSON / CSV | implemented |
| `live_ohlcv` | `/api/real-time/{provider_symbol}` | 最新 delayed OHLCV snapshot | JSON / CSV | implemented |
| `bulk_last_day_eod` | `/api/eod-bulk-last-day/{exchange}` | 小规模手动 bulk last-day 查询 | JSON / CSV | implemented |
| `dividends` | `/api/div/{provider_symbol}` | 历史分红 | JSON / CSV | implemented |
| `splits` | `/api/splits/{provider_symbol}` | 历史拆股 | JSON / CSV | implemented |
| `technical` | `/api/technical/{provider_symbol}` | 技术指标序列 | JSON / CSV | implemented |
| `screener` | `/api/screener` | 股票筛选器 | JSON | implemented |
| `exchange_symbol_list` | `/api/exchange-symbol-list/{exchange}` | 交易所 symbol list | JSON | implemented |
| `instrument_search` | `/api/search/{query_string}` | instrument lookup | JSON | implemented |
| `exchanges_list` | `/api/exchanges-list/` | EODHD 支持交易所列表 | JSON | implemented |
| `exchange_details` | `/api/v2/exchange-details/{exchange}` | 交易时间和休市日 | JSON | implemented |
| `symbol_change_history` | `/api/symbol-change-history` | US ticker rename history | JSON / CSV | implemented |
| `id_mapping` | `/api/id-mapping` | CUSIP/ISIN/FIGI/LEI/CIK/EODHD symbol mapping | JSON | implemented |

Inventory-only，不在当前 29.99 Extended 白名单中执行：

| Endpoint group | 原因 |
| --- | --- |
| Fundamentals | Pricing 显示 Fundamentals Data Feed 是独立 59.99 plan。 |
| Calendar and news | Pricing 显示 Corporate Events Calendar & News API 是独立 marketplace 产品。 |
| Historical market cap | 官方页面归在 Fundamental & Economic Data；当前没有足够明确的 29.99 Extended 权限依据。 |
| Official index constituents | EODHD 官方指数成分股页面归 marketplace/Fundamental & Economic Data；当前不作为 29.99 Extended 白名单执行。 |

## 8. 请求校验规则

App 在生成 URL 或执行 API 前做参数校验：

- 只接受 registry 中 `implemented=True` 的 endpoint。
- asset 当前只接受 `equity`。
- symbol 和 exchange 只允许有限安全字符。
- 必填参数不能被 server 静默填入 UI default；API payload 必须显式带值。
- Historical EOD 必须提供 symbols、`date_from`、`date_to`。
- Historical EOD 最多 2000 个 symbols。
- Wizard ticker import 必须命中 active DB `symbol` 或 `provider_symbol`；例如 DB 存 `BRK-B` / `BRK-B.US` 时，`BRK.B` 不会被猜测接收。
- 已确认请求进入后端时，request validation 仍会校验 provider symbol 字符集和 endpoint 数量上限。
- 前端 selected rows、codegen payload、Execute API 使用同一批 confirmed DB provider symbols，避免 UI 显示一个 symbol 但生成 URL 使用另一个 symbol。
- Historical EOD 日期范围最多 3660 天。
- T+n helper 只做 UI 日期填充，不绕过后端日期范围校验；business-day 模式当前按周一到周五计算，不含交易所节假日。
- Intraday 支持 `1m`、`5m`、`1h`；如果提供 timestamp range，会按官方区间上限校验。
- Bulk EOD 默认必须提供 symbols；除非用户显式勾选 full exchange。
- Bulk EOD 默认最多 2000 个 symbols。
- Bulk EOD 支持 `trade_date` 或 `date_from`/`date_to`，日期范围最多 31 个 calendar days，会生成每个日期一个 bulk URL。
- Intraday / Technical / Live OHLCV 支持最多 2000 个 symbols 用于 code generation；Live OHLCV 会按 20 symbols 一组生成请求。
- Pool browser 每次最多返回 2000 rows，数据源是现有 MySQL `us_share.instrument`。
- Pool browser 不需要 stored token / `EODHD_API_KEY`，不会调用 EODHD API；缺少 DB、schema 不可读或 DB 查询失败时显示 explicit unavailable。
- Pool Browser 的前端加载使用 request sequence guard，避免慢的旧 pool 响应覆盖用户刚切换到的新 pool。
- Index Assets 只代表 DB 中 `asset_type=index` 的指数资产，不代表指数成分股。
- Sectors/industry pools 当前禁用，因为现有 DB schema 没有 sector/industry taxonomy 或 membership table。
- 前端 import 支持 `.csv` / `.txt` 和 pasted text；浏览器本地解析后调用本地 DB resolver，只接受 `us_share.instrument` 中 active instrument 的 `symbol` 或 `provider_symbol` exact match，大小写不敏感，命中后用 DB 名称进入 selected list；未命中的 token 会 rejected。
- Historical / Intraday / Dividends / Splits / Technical 这类 one-symbol-per-request 执行结果会补 `_provider_symbol`，避免多个 symbol 返回行混在一起时无法判断来源。
- 前端 selection 最多 2000 tickers；超过 100 tickers 时显示强提醒，但不阻止生成代码。
- Search query 最多 80 个字符。
- Screener filters 必须是 JSON array。
- Preview rows 限制在 1 到 500。
- JSON-only endpoint 不允许 CSV。
- Bulk/high-call execute 必须通过后端 cost confirmation；前端会弹出显式确认，未确认时后端拒绝执行。
- 本地 `Execute API` 硬限制最多 50 个 generated HTTP requests；超过上限只能生成代码，不由 preview UI 批量执行。

这些是 app-level guardrails，目的是保护交互式研究查询，不代表 EODHD 协议本身的全部限制。

## 9. API Key 和安全边界

真实 API key 只在服务器端使用，默认来自页面 `Login / Config` 保存的本地 token。环境变量只作为脚本化运行 fallback：

```text
EODHD_API_KEY
```

安全规则：

- 不提交真实 `.env`。
- 不把真实 token 写进代码。
- 不把真实 token 返回给浏览器。
- `Login / Config` 默认将 token 存入用户本地 app config 文件，权限为 `0600`。Keychain 支持保留为可选模块路径，但不作为默认保存路径，因为 macOS `security` 在本地 HTTP 请求中可能阻塞。
- 已保存 token 只能显示 configured/source 状态，不能查看，只能删除后重填。
- Direct URL 使用 `YOUR_EODHD_API_KEY` 占位符。
- Python 示例使用 `os.environ["EODHD_API_KEY"]`。
- curl 示例使用 `${EODHD_API_KEY}`。
- JavaScript 示例使用 `process.env.EODHD_API_KEY`。
- `Config token` 代码示例调用当前 localhost port 的本地 `/api/execute`，由本地 app 使用 Login / Config 中保存的 token，不把 token 明文塞进生成代码。
- upstream error 返回浏览器前会 redaction 当前 API key。
- 缺少 stored token 且没有 `EODHD_API_KEY` fallback 时，`Execute API` 返回显式错误；不会 silent fallback 到 demo key。
- 本地 side-effect routes 只接受 loopback `Host`/`Origin`，POST 必须是 `application/json`，以降低随机网页触发本机 API 消耗 token 的风险。

当前不实现复杂安全机制或认证层，因此只应在本机 `127.0.0.1` 开发环境使用。

## 10. 数据预览和导出

`/api/execute` 返回：

- normalized request
- parsed rows
- preview rows
- source row count
- returned row count
- request count
- status codes

前端展示 preview table，并允许把最近一次返回的 rows 导出为 CSV。

限制：

- server 返回 rows 最多 5000 行。
- `Execute API` 最多执行 50 个 generated HTTP requests；更大的 symbol list 只生成代码。
- preview table 使用用户选择的 preview limit。
- CSV 导出在浏览器端完成。
- CSV cell 会 quote；以 `=`, `+`, `-`, `@` 开头的值会加前缀，降低 spreadsheet formula injection 风险。
- Excel `.xlsx` 导出是 P1，不属于当前实现。

## 11. 错误处理

HTTP API 错误语义：

- `400`：用户请求参数非法。
- `404`：未知 route。
- `502`：EODHD upstream request 失败或缺少 stored token / `EODHD_API_KEY` fallback。

缺少 stored token 且没有 `EODHD_API_KEY` fallback 时，`Execute API` 返回显式错误；不会 silent fallback 到 demo key。

## 12. 测试

运行测试：

```bash
cd "/Users/boqingxin/tandon MSCS/My_Own/financial-data-platform/database_app"
PYTHONPATH=src ../database_system_cli/.venv/bin/python -m pytest
```

静态检查：

```bash
../database_system_cli/.venv/bin/ruff check src tests
```

当前覆盖：

- endpoint registry 结构和官方依据字段。
- request validation。
- endpoint boundary checks。
- token-safe code generation。
- Historical / intraday / technical / screener / ID mapping URL generation。
- JSON / CSV execution parsing。
- nested JSON preview flattening。
- CSV-mode Python/JavaScript snippet behavior。
- upstream token redaction。
- token store env/keychain behavior。
- local request guard against non-loopback origin/host and non-JSON POST。
- DB-backed universe menu/load contract。
- DB env parser precedence and no-secret public status。
- preset/exchange/asset_type/index asset pool query semantics。
- API cost estimation and bulk confirmation guard。
- frontend static smoke for single workspace, wizard import/confirm, stale-result boundary, and no-key execute error path。

`database_system_cli` 主线测试可单独在其目录运行，不依赖 `database_app`。

## 13. 文档

文档职责：

- `PROJECT.md`：项目规格源文件。
- `PROJECT.html`：与 `PROJECT.md` 同步生成的浏览器友好版。
- `README.md`：快速启动和使用说明。
- `PROGRESS.md`：实现进度看板。
- `docs/OFFICIAL_ENDPOINTS.md`：官方 endpoint、套餐依据、rate/cost 依据、Wind 研究笔记。
- `docs/TECHNICAL_DESIGN.md`：技术实现细节和维护说明。
- `docs/RELEASE_NOTES_v1.0.md`：v1.0 release notes 和发布验证摘要。

修改 `PROJECT.md` 时，应同步更新 `PROJECT.html`。

本项目现在采用 repo-level Trellis 工作流做大任务执行记录，但 `PROJECT.md`、`PROJECT.html`、`PROGRESS.md` 和 `docs/` 仍是长期项目事实来源。Trellis task artifacts 不替代本项目规格文档。

## 14. Roadmap

P1:

- Wind-like Python client package:
  - `pip install eodhd-codegen-app` 或未来拆出的 `eodhd-client`。
  - Python 中支持 `from eodhd_client import w`。
  - 第一次 `w.start()` 如果没有 token，打开本地 Login / Config 子窗口或 CLI prompt 保存 token；之后 `w.start()` 直接读取本地 token store。
  - `w.start()` 成功后打印 `EODHD is connected` 或返回连接状态，接近 WindPy 的 `w.start()` 使用心智。
  - `w.isconnected()` 返回本地 token 是否可用以及一次 lightweight endpoint probe 是否成功。
  - `w.wsd("AAPL.US", "close,volume", "2024-01-01", "2024-01-31")` 映射到 EODHD historical EOD；`w.wss()` 映射到 snapshot/search/fundamental-like safe subset；`w.wset()` 映射到 whitelist dataset/bulk/screener。
  - 不把真实 token 写入代码、不要求用户手动 export env；默认使用本地 app config 或系统 keyring。
- 迁移到 FastAPI + Jinja2，并保留当前 registry/service 分层。
- Excel `.xlsx` export。
- 保存 request templates，但不保存 API key。
- Server-side streaming export for large responses。
- 更清楚的 endpoint group/status 页面。
- 更完整的 ambiguity-aware paste matcher，例如 Bloomberg-style `AAPL US Equity` 和跨交易所重名处理。

P2:

- C++ code generation。
- 多资产完整支持。
- 抽取 shared EODHD URL/client/validation package。
- 可选本地审计日志，但不得写入 `database_system_cli` schema。
- 真正的 native webview/PyInstaller/Briefcase packaging。

## 15. 当前状态

`database_app` 已实现 registry-driven 产品化版本，支持 14 个官方确认可用于 29.99 Extended 研究工作流的 endpoint，并保留 inventory-only 区分不在当前白名单内的 endpoint group。v0.6 已完成 read-only MySQL pool browser，Stocks wizard 的候选加载不再调用 EODHD API；Index Assets 明确为指数资产而非成分股，Sectors 在 taxonomy source 加入前禁用。v1.0 release 收口将当前本地工具作为独立子项目发布，并采用 Trellis 作为未来大任务执行层。v1.3 已把个人首页和 J21 Terminal 从 `database_app/site/` 拆到仓库 sibling 根目录，`database_app/site/` 当前只负责 CodeGen 产品说明与安装产物下载。`database_system_cli` schema 和源码未被修改。
