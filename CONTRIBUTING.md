# Contributing

Use a scoped branch and describe the changed behavior, tests, and any provider
cost. Start with `AGENTS.md` and the component's README and instructions.

- Keep US CLI, CN CLI, and API App dependencies separate.
- Reuse shared Job logic for CLI/Menu entrypoints; do not duplicate ingestion.
- US schema changes require an Alembic migration, table changes, and tests.
- Run the component's offline tests. Real provider/DB checks are opt-in and must
  never be necessary for a contributor's baseline test run.
- Keep Markdown and existing paired HTML in sync with the renderer in
  `database_system_cli/scripts/render_markdown_html.py`.
- Do not commit keys, `.env`, local databases, API response dumps, private projects,
  build products, or purchased documents. Use synthetic test fixtures.
- Do not distribute provider data without the necessary permission.

For a new capability or complex fix, use a Trellis task. Small documentation and
bug fixes do not need a large planning package. Keep task records free of private
machine paths, credentials, and copied private implementation.

Contributions to original project code are provided under the repository's MIT
license. Preserve upstream notices when adding third-party material.

The public repository uses sanitized history. Contributors with pre-publication
clones must clone again and port reviewed source changes only; do not merge or
push old refs, private recovery tags, or stashes into this repository.
