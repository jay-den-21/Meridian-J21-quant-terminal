# Terminal Menu Context

本文件适用于 `fdp.menu`，并继承上级 `AGENTS.md`。

## 本层拥有

- 中英文、方向键驱动的人工输入。
- preflight/确认页、等价 CLI 展示和 `tqdm` progress rendering。
- TTY 检测、取消/返回行为和人类可读错误展示。

## 本层不拥有

- API 调用、SQL 写入、重试、预算计算或数据验证业务逻辑。
- 独立于 `fdp.get_data` 的默认值或第二套 ingestion 流程。

## 开工前读取

- `../get_data/AGENTS.md`
- `../../../docs/terminal_menu.md`
- `../get_data/registry.py`、`app.py`、`progress.py`、`prompts.py`

## 数据流

```text
TTY input -> Job registry/handler -> Job.preflight -> 默认取消确认
          -> Job.run(reporter) -> tqdm/summary
```

## 修改检查

- 菜单直接调用 Job，禁止 subprocess/shell 调用 `j21`。
- `INGEST_JOB_DEFINITIONS` 与 `JOB_HANDLERS` 必须一一对应。
- destructive/large ingest 的确认默认值必须是取消。
- progress bar 在成功、异常和取消路径都必须关闭。
- 不在屏幕、exception 或等价命令中输出 API key。
- 同步 `docs/terminal_menu.md/.html`，并运行 terminal-menu tests。
