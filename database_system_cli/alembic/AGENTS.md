# Alembic Migration Context

本文件适用于 `database_system_cli/alembic`，并继承上级 `AGENTS.md`。

## 本目录拥有

- MySQL 物理 schema 的有序 revision 历史、upgrade 和可行时的 downgrade。
- schema/data migration 的可审计步骤。

## 本目录不拥有

- 运行时 SQLAlchemy metadata、provider parser 或业务 CLI。
- 绕过 revision history 的手工数据库变更。

## 开工前读取

- `../src/fdp/storage/AGENTS.md`
- `../PROJECT.md` 对应数据模型章节
- 当前 `versions/` 链、`alembic heads` 和 `alembic current`

## 迁移流程

```text
批准的数据模型变化 -> 新 revision -> upgrade 验证 -> metadata/tests/docs 同步
```

## 修改检查

- 不修改已发布 revision 来伪造历史；新增 revision 或明确 merge revision。
- `down_revision` 必须可定位，最终默认保持单一 head。
- MySQL DDL 非事务性；多步迁移要考虑中途失败、幂等保护和数据 count 校验。
- copy/drop 类迁移先复制并验证，再删除旧对象；不要静默丢数据。
- migration、`src/fdp/storage/tables.py`、upsert、tests、PROJECT 必须描述同一 schema。
- 运行 `poetry run alembic heads`；有数据库连接时再运行 upgrade/current smoke。
