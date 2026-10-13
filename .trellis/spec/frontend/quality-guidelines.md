# Frontend Quality

- `database_app/site/` is CodeGen-only; it must work without private sibling sites.
- The app's wizard edits a draft; only Confirm changes the generated/executable request.
- Tokens must never appear in HTML, generated examples, API errors, or exported rows.
- Preview limits do not truncate same-execution CSV exports. Formula-like cells
  and headers must be escaped for spreadsheet safety.
- Missing DB configuration shows an explicit unavailable instrument browser;
  it must not trigger an automatic provider call or break code generation.
- Run pytest, JS syntax checks, and root static-reference tests for changed files.
- For visual changes, check desktop/mobile in a real browser: no overflow,
  clipping, missing local assets, or focus traps.
- Local macOS installer artifacts are not part of the source release and must
  not be presented as signed/notarized public downloads.
