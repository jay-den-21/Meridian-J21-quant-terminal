<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

# Repository Governance

This public repository has three tracked sibling components with independent ownership:

- `database_system_cli/`: database ingestion, validation, repair, and research read layer.
- `database_system_cli_cn/`: independently runnable Chinese Tushare compatibility product; it preserves the legacy getter/runtime surface while targeting the externally owned `a_share` schema.
- `database_app/`: local EODHD API code generator and API playground.

`playground/`, `quant/`, `personal_site/`, `j21_terminal/`, and
`research_terminal/` are user-owned local-only roots.
They are intentionally ignored as whole directories and are not repository
components. Do not add, force-add, move, or copy their contents into tracked
paths. Their files, environments, private data, generated output, and local Git
state must remain on the user's machine unless the user explicitly changes this
boundary in a later task.

Do not put new app work into `database_system_cli/` unless the user explicitly asks to extend the database CLI. Do not let `database_app/` write database schemas, migrations, or ingestion data.
Do not import `database_system_cli_cn` from `database_system_cli`. Inside the CN product,
`src/fdp_cn` may invoke preserved getters only through its explicit compatibility worker;
do not treat append-plus-cleanup as equivalent to the direct transactional upsert path.
Do not run two A-share writers concurrently unless a later task explicitly qualifies that
operating mode.
Do not place personal-profile or terminal frontend code under `database_app/`. Cross-product navigation must use links rather than embedding one product's views or assets inside another.
Do not let `research_terminal/` execute ingest/repair/migration or arbitrary SQL; it may only read canonical/audit data and display inert CLI suggestions.

## Scoped Context Routing

Instructions are cumulative. Before editing a path, read this file, the subproject
`AGENTS.md`, and the nearest deeper `AGENTS.md`. A deeper file adds local ownership
rules; it never overrides repository boundaries or secret-handling rules.

| Working path | Required context |
| --- | --- |
| `database_system_cli/**` | `database_system_cli/AGENTS.md` and its scoped routing table |
| `database_system_cli_cn/**` | this file |
| `database_app/**` | `database_app/AGENTS.md` |
| `j21_terminal/**`, `research_terminal/**` | local-only; this file and any local scoped instructions; never add to Git |
| `playground/**`, `quant/**`, `personal_site/**` | local-only; this file; never add to Git |
| `.trellis/**`, `.agents/**`, `.codex/**` | this file and `.trellis/workflow.md` |

The current CLI code-flow and path ownership map live in
`database_system_cli/docs/architecture.md` with a paired human-readable HTML file.
Do not infer cross-layer behavior from directory names alone; trace the implementation
from that map and verify changed call sites in code.

## Source Of Truth

Long-term project truth lives in Markdown governance:

- `AGENTS.md`: rules, boundaries, and workflow.
- `PROJECT.md` / `PROJECT.html`: durable product and architecture specification.
- `PROGRESS.md`: milestone progress and next step.
- `docs/`: research, design notes, runbooks, endpoint evidence, and release notes.

Trellis manages task execution history. Trellis task artifacts (`prd.md`, `design.md`, `implement.md`) do not replace `PROJECT.md`, `PROGRESS.md`, or `AGENTS.md`. If they conflict, the Markdown governance files win.

When a Trellis task changes product capability, architecture, operation, release status, or workflow rules, update the relevant `PROJECT.md`, paired `PROJECT.html`, and `PROGRESS.md` before finishing the task.

## Trellis Usage

Use Trellis for large work:

- new features
- architecture changes
- releases
- complex bug fixes
- evaluator/fix-loop work

Skip Trellis for small conversations, status checks, simple command output, or trivial doc fixes unless the user explicitly asks for a task.

Trellis task lifecycle:

```text
create task -> prd.md -> design.md -> implement.md -> start -> work -> check -> sync docs -> commit/tag -> archive
```

Evaluator policy:

- P0 blockers must be fixed.
- P1 issues should be fixed when practical or explicitly deferred.
- P2 items go to roadmap.

## Git Hygiene

Original public project code uses MIT. Preserve third-party notices. The source
license grants no provider data access or redistribution rights. Public releases
must not include private projects, purchased reference PDFs, data dumps, or raw
security/recovery reports. Historical private task/spec records remain local;
new shared task records must contain only public implementation context.

After a history-sanitized release, old local clones, branches, stashes, and backups
are recovery-only. Never merge or push their unfiltered history into the public
repository. Use a fresh clone or sanitized refs for subsequent work.

Commit shared workflow infrastructure such as `.trellis/workflow.md`, `.trellis/spec/`, `.trellis/tasks/`, `.trellis/scripts/`, `.agents/skills/`, and project-scoped `.codex/` helpers when they are part of the repo workflow.

Never commit local state or secrets:

- `.env`
- API keys, tokens, passwords, private keys
- `.trellis/.developer`
- `.trellis/.runtime/`
- `.trellis/workspace/`
- caches, bytecode, generated build output

## User-Operated Data Ingest

For `database_system_cli/`, small smoke tests, diagnostics, dry-runs, and read-only
database verification may be run by the agent. Large API-consuming ingest should
default to user-operated CLI execution so the user keeps direct visibility and
control over API budget. The agent should provide exact commands, date windows,
estimated API cost, target tables, and expected output before the user runs them.
After the user runs the command, the agent should verify database/log state and
explain exactly what was checked. The agent may run large real ingest only after
the user explicitly asks the agent to do so.

## Simple Workflow

```text
读AGENTS
看PROJECT
查PROGRESS
开Trellis
写PRD
写Design
写Plan
开始做
跑测试
狠评审
修P0
尽修P1
同步MD
提交Git
打Tag
归档Task
```
