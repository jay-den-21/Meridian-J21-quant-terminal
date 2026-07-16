# Storage Context

本文件适用于 `fdp.storage`，并继承上级 `AGENTS.md`。

## 本层拥有

- SQLAlchemy Core metadata、canonical table/view contracts、schema guard 和 MySQL upsert。
- instrument identity、split daily price、system audit/quality workflow 的逻辑表定义。

## 本层不拥有

- Alembic revision 顺序本身；物理 schema 变化由 `../../../alembic/` 管理。
- EODHD payload 解析、UI、repair 业务决策或 app 临时 snapshot writer。

## 开工前读取

- `../../../PROJECT.md` 的数据模型章节
- `../../../alembic/AGENTS.md`
- `tables.py`、`upsert.py`、`schema.py`
- 涉及字段的 source、quality、repair/quarantine、research 调用方

## 数据流

```text
validated domain rows -> table contract/upsert builder -> MySQL unique-key upsert
runtime connection -> schema inspector -> explicit migration-required error
```

## 修改检查

- schema 变化必须同时修改 table definition、Alembic、upsert、tests 和文档。
- daily price identity 保持 `instrument_id + trade_date` 唯一；不以 ticker 作为身份主键。
- 批量写入使用唯一键 upsert，不把事后 dedupe 当主防线。
- `us_share` 只放 canonical market data/instrument master；临时 app response 属于
  `app_log`，系统运行记录属于 `system`。
- `ensure_runtime_schemas` 只检查必要 schema，不负责自动创建/迁移。
- 运行 storage/upsert tests，并检查 Alembic 单一 head。
