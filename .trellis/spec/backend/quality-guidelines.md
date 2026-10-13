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

## Public Bootstrap Contract

### 1. Scope
Fresh-clone setup without provider keys, private YAML, or optional sibling apps.

### 2. Signatures
`j21 ingest index-pit --phase basic --output json` (CN);
`j21 validate docs-staleness` (US).

### 3. Contracts
CN basic dry-run returns a plan with zero API calls and never constructs an
environment-backed runtime. US docs checks own the six CLI Markdown/HTML pairs.

### 4. Validation And Errors
Execute mode and metadata-dependent preflights still require their real
configuration. A missing CLI-owned document remains an error.

### 5. Cases
Good: config-free basic planning. Base: explicit execute with configured runtime.
Bad: suppressing missing credentials with a fabricated live connection.

### 6. Required Tests
`test_public_bootstrap.py` patches runtime construction to fail in dry-run and
expects execute to retain configuration errors. `test_public_docs_scope.py`
checks both optional-sibling absence and required-document failure.

### 7. Wrong Versus Correct
Wrong: initialize DB/provider runtime before deciding whether it is needed.
Correct: resolve the basic dry-run first; initialize only for the dependent path.
