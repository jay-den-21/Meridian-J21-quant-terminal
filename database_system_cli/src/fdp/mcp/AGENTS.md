# MCP Adapter Context

This path exposes existing `fdp.get_data` Jobs to AI clients. It is an adapter,
not a second ingestion implementation.

- Reuse Job preflight/run contracts; never call EODHD or write SQL directly here.
- Read-only tools are the default.
- A write-capable tool must require both `J21_MCP_ENABLE_WRITES=1` and an explicit
  `confirm_execute=true` argument.
- Never return API keys, database URLs, environment dumps, or provider URLs that
  contain credentials.
- Keep stdio output protocol-clean. Diagnostics belong on stderr or in structured
  tool results.
- Every write tool needs tests for both denied and explicitly enabled paths.
