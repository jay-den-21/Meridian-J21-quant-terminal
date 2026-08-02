# EODHD Future Agent Usage Policy

This folder is a reference archive for future Finance Agent and MCP work. It is
not active project instruction and must not be imported directly by production
code without review.

## Intended Use

- Use the vendored EODHD Claude Skills package as endpoint discovery material.
- Use it to draft Finance Agent prompts, routing rules, endpoint descriptions,
  parameter examples, and MCP wrapper ideas.
- Use `registry/capabilities.json` and the endpoint reference docs to compare
  candidate endpoints during future planning.
- Prefer the upstream EODHD MCP server only for exploratory agent workflows,
  not for database ingestion correctness.

## Do Not Use As

- Do not treat this snapshot as the authoritative subscription whitelist.
- Do not treat it as a replacement for official EODHD documentation.
- Do not let an agent execute arbitrary vendored scripts automatically.
- Do not store API keys or `.env` files in this directory.
- Do not make `database_app` or `database_system_cli` import code from
  `tools/eodhd/vendor/`.
- Do not ask users to paste EODHD tokens into chat as the normal auth path.
  Use environment variables, secret-manager injection, or reviewed OAuth/MCP
  auth. If a human pastes a token anyway, redact it from logs and outputs.

## Better Long-Term Design

The strongest design is:

1. Keep this vendored package as a research snapshot.
2. Build a project-owned endpoint registry from official EODHD docs and your
   subscription evidence.
3. Expose reviewed endpoint wrappers through an internal MCP server.
4. Let the Finance Agent call only those wrappers, with token redaction,
   request limits, logging, and subscription-aware endpoint gating.

This preserves the benefit of EODHD's structured skill docs while keeping your
actual data platform deterministic and auditable.

## Direct MCP vs Project-Owned MCP

Using the upstream EODHD MCP server directly is useful for ad hoc analyst
research because it exposes many tools quickly and can reduce endpoint/parameter
guessing. It is not the best default for production database workflows.

Preferred production path:

```text
official docs + subscription evidence
  -> project-owned endpoint registry
  -> reviewed Python/API wrappers
  -> internal MCP tools for Finance Agent
  -> logged, rate-limited, token-redacted execution
```

Use direct upstream MCP only when the task is exploratory, low-risk, and the
result will be verified before it changes database state or investment logic.

Reasons:

- Subscription coverage changes over time; the project registry should decide
  what is allowed for the user's current plan.
- Database ingestion needs deterministic schemas, logs, retries, and validation.
- A future Finance Agent should not be able to call arbitrary endpoints or run
  vendored helper scripts without project-level review.
- Credentials must remain outside the agent prompt surface whenever possible.
- The existing `database_app` and `database_system_cli` should remain isolated
  from `tools/` until an integration is deliberately promoted into production
  code with tests.

## Current Snapshot

- Upstream article: https://eodhd.com/financial-apis/eodhd-claude-skills-teach-your-ai-assistant-the-entire-financial-api
- Upstream repository: https://github.com/EodHistoricalData/eodhd-claude-skills
- Local snapshot metadata: `SOURCE.md`
- Local vendor path: `vendor/eodhd-claude-skills/`
