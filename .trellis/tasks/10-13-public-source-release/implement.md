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

Publication verified on 2026-10-13:

- All 16 selected branches and 3 historical tags were sanitized. Final pre-release
  inspection covered 69 reachable commits and 1,311 unique text blobs; no skipped
  binary files, LFS pointers, excluded roots, or custom credential matches remained.
- Gitleaks v8.30.1 reported no findings in the filtered history or public artifact.
- GitHub retained access to old excluded files after the first rewrite. With the
  user's explicit approval, the previous repository became a private archive and
  a distinct clean repository was created under the original name.
- The new repository is Public, defaults to main, reports MIT, and clones without
  credentials. Old excluded-file requests return 404, including anonymous checks.
- Local main matches the cleaned remote. Excluded local files, environments, and
  directories were preserved; original Git refs/stashes/reflogs remain in private
  recovery storage with pushing disabled.
- No database, provider subscription, or market-data ingestion was changed.

No package-registry upload, hosted app deployment, or new release tag was performed.
