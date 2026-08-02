# EODHD Tool References

This folder stores EODHD-related agent/tool material for future Finance Agent or MCP integration.

Stored snapshot:

- `vendor/eodhd-claude-skills/`: upstream EODHD Claude Skills repository snapshot.
- `FUTURE_AGENT_USAGE.md`: project policy for how a future Finance Agent/MCP
  integration should use this snapshot.
- `SOURCE.md`: upstream URL, commit, license, and local import policy.

Why this is useful:

- It gives a future Finance Agent a structured map of EODHD endpoints, workflows, and example MCP/client patterns.
- It can speed up endpoint discovery and reduce repeated manual reading of EODHD docs.
- It is a good reference layer for prompt design and tool-routing design.
- It includes an upstream `.mcp.json` example for EODHD's hosted MCP server, which is useful as an integration reference.

Limits:

- This is not an authoritative runtime whitelist for `database_app`.
- It does not replace `database_app/docs/OFFICIAL_ENDPOINTS.md`.
- It may include endpoints outside the user's current EODHD subscription.
- Vendored scripts are not trusted production code until reviewed and tested.
- It must not be treated as active Codex instruction just because it contains `CLAUDE.md` or `SKILL.md` files.
- It must not become the credential path for future agents; tokens should come
  from environment variables, a secret manager, or reviewed OAuth/MCP auth.

Better long-term path:

1. Keep this snapshot as reference material.
2. Build a small internal endpoint registry from official EODHD docs and subscription evidence.
3. Expose that registry through a controlled Finance Agent MCP server.
4. Let the Finance Agent call reviewed wrapper functions with logging, token redaction, request limits, and subscription gating.
5. Use EODHD's hosted MCP server for exploration only until its behavior and auth model are reviewed.

Quick judgment:

- Useful as a research and prompt/tool-routing reference.
- Not enough as a production integration by itself.
- Best future path is a project-owned MCP wrapper backed by reviewed endpoint
  metadata and explicit subscription gating.
- Direct EODHD MCP can be useful for exploratory analysis, but production
  database or investment workflows should go through project-owned wrappers.
