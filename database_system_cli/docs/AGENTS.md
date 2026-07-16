# Documentation Context

本文件适用于 `database_system_cli/docs/`。它继承仓库根目录和
`database_system_cli/AGENTS.md` 的全部规则。

## 本目录拥有

- 面向人和 agent 的架构、CLI、操作手册和研究文档。
- Markdown 源文件及其同名 HTML 阅读版。
- 当前代码路径的解释，但不定义新的运行时行为。

## 本目录不拥有

- Python 业务逻辑、CLI 参数、数据库 schema 或 migration。
- 未经代码、测试或官方来源确认的“当前实现”结论。
- `PROJECT.md` 和 `PROGRESS.md` 已经承担的长期规格或里程碑真相。

## 开工前读取

- `../PROJECT.md`
- `../PROGRESS.md`
- `architecture.md`
- 若涉及命令，再读 `cli_commands.md` 和 `terminal_menu.md`

## 文档流程

```text
代码/测试/官方证据 -> Markdown 源文件 -> render_markdown_html.py -> HTML 阅读版
                    -> 必要时同步 PROJECT / PROGRESS
```

## 修改检查

- 先用 `rg` 追踪实际函数、命令和表名，不凭目录名猜流程。
- 有同名 HTML 时必须运行 `../scripts/render_markdown_html.py` 重新生成。
- 架构事实变化时同步 `../PROJECT.md`、`../PROJECT.html`、`../PROGRESS.md`。
- Mermaid 节点名称保持简短；含括号或标点的 label 使用引号。
- 不写真实 token、连接串、密码、个人绝对路径或未经脱敏的日志。
- CLI 文档完成后对照 `poetry run j21 --help` 及相关子命令 `--help` 核对真实 Typer tree。
