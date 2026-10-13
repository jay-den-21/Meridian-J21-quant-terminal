# Backend Quality

- Test from a checkout without private configuration, datasets, or sibling apps.
- US: pytest, Ruff, CLI help, and docs-staleness checks.
- CN: unittest discovery, catalog/Menu agreement, explicit execute confirmation.
- API App: pytest, Ruff, tokenless startup, request generation, safe CSV exports.
- Credentials remain server-side and must be redacted from errors, logs, and exports.
- Do not hide failures with demo data, placeholder database connections, or silent fallback.
- Keep state/checkpoint changes in their documented transactions; never download
  provider responses while holding a database write transaction.
- Distinguish dry-run planning from operations that need local database metadata.
- Public documentation checks own their component only; optional private tools
  must not be required for baseline tests or installation.

Large live API/DB tests remain opt-in and require explicit user authorization.
