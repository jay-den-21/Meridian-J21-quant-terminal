# EODHD Claude Skills Source

Snapshot date: 2026-07-01

Upstream sources:

- Article: https://eodhd.com/financial-apis/eodhd-claude-skills-teach-your-ai-assistant-the-entire-financial-api
- Repository: https://github.com/EodHistoricalData/eodhd-claude-skills
- Hosted MCP reference from upstream `.mcp.json`: `https://mcp.eodhd.com/v2/mcp`

Snapshot metadata:

- Commit: `ab3034f8eb4a84dbff2c2d19fbfc3e4b1f24bff2`
- Commit date: `2026-06-22 21:11:11 +0300`
- Commit subject: `chore: release 0.6.0 (#24)`
- License: MIT License, retained in `vendor/eodhd-claude-skills/LICENSE`

Local storage:

- `tools/eodhd/vendor/eodhd-claude-skills/`

Import policy:

- Excluded upstream `.git/`, `.github/`, and `tests/`.
- Retained upstream docs, adapters, registry, skills, agent prompt, templates, scripts, plugin metadata, `.mcp.json`, and license.
- Replaced fake token-like examples with `<YOUR_EODHD_API_TOKEN>` to avoid future secret-scan false positives, including the authentication guide token-format sample.
- These files are inert references. They are not active Codex instructions and are not imported by application code.

Official page notes:

- EODHD describes this package as an open-source skill adapter library for Claude/Codex-style agents.
- The article says it covers 72 documented endpoints, 28 reference guides, a lightweight Python client, analysis templates, and subscription plan guides.
- The GitHub README describes an OAuth MCP server, workflow skills, a financial analyst agent, slash commands, endpoint docs, and a stdlib-only Python client.
