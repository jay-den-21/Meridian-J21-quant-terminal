# Release Verification

Verified on 2026-10-13 in an isolated checkout without private configuration:

- US: 397 pytest tests; Ruff; compileall; Poetry lock validation; j21/fdp help;
  docs-staleness reports current with 38 documented/actual commands.
- App: 108 pytest tests; Ruff; JavaScript syntax; real localhost HTTP smoke for
  page/catalog, code generation, missing-token error, execution, and CSV download.
  Provider responses were synthetic; no paid API requests were made.
- CN: 109 unittest tests; compileall; Poetry lock validation; CLI help and basic
  index-PIT JSON dry-run. Fixed premature configuration initialization in dry-run
  and isolated test-only compatibility configuration.
- Public static site: 3 boundary/link tests; private sibling sites are not required.
- Changed Markdown product documents have regenerated HTML companions.
- Existing CN CRLF files retain their line endings; whitespace verification uses
  Git's `cr-at-eol` interpretation rather than normalizing unrelated lines.

Remote rewrite, remote exposure checks, and visibility verification are pending.
No publication claim is made until those gates are recorded as passed.
