# Migration Workflow Context

本文件适用于 `fdp.migrate`，并继承上级 `AGENTS.md`。

## 本层拥有

- 大数据量、可恢复、人工确认的数据搬运工作流。
- checkpoint、备份验证、copy/verify/finalize gate 和 rollback 信息。

## 本层不拥有

- Alembic revision 的 schema DDL、provider API 拉取、terminal UI 或研究查询。
- 绕过 migration head、备份、verify fingerprint 或 `--yes` 的快捷写入。

## 数据流

```text
Alembic expand -> metadata refresh -> backup -> chunk copy -> verify -> chunk delete
```

## 修改检查

- 大表 copy/delete 不放进 Alembic。
- 每个 chunk 与 checkpoint 必须同事务提交。
- destructive phase 必须重新验证备份和 verify fingerprint。
- 默认只读；copy/finalize 必须由 CLI 同时提供 `--execute --yes`。
- 不自动运行 `OPTIMIZE TABLE`。
