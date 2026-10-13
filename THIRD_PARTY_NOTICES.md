# Third-Party Notices

The root MIT license covers original Meridian J21 application code. It does not
relicense independently distributed third-party material or provider data.

## Trellis Development Tooling

- Upstream: <https://github.com/mindfold-ai/Trellis/tree/v0.6.5>
- Copyright: Mindfold and the Trellis contributors.
- License: GNU Affero General Public License v3.0; full upstream text is preserved
  in [licenses/Trellis-AGPL-3.0.txt](licenses/Trellis-AGPL-3.0.txt).
- Scope: bundled Trellis workflow/scripts, Trellis-derived skill templates under
  `.agents/skills/trellis-*`, platform helpers under `.codex/`, and managed Trellis
  instruction templates. Project-specific specs and task content are separate.
- Local adaptations to workflow/platform helpers are distributed in source form
  in this repository under the upstream license. This tooling is optional for
  running the financial applications; it is not imported by their runtime packages.

Do not copy these third-party tools under the assumption that the root MIT license
applies to them. The referenced upstream release identifies its license as AGPL-3.0.

## Archived Agent References

These are inert references, not application runtime dependencies:

- `tools/finance/claude-skills-finance/`: upstream attribution and MIT license in
  [its LICENSE](tools/finance/claude-skills-finance/LICENSE).
- `tools/eodhd/vendor/eodhd-claude-skills/`: upstream attribution and MIT license in
  [its LICENSE](tools/eodhd/vendor/eodhd-claude-skills/LICENSE).

Their upstream URLs, revisions, and snapshot information remain in the archive's
own source metadata. Do not treat vendored agent instructions as project policy.

## Installed Dependencies And Data Providers

Python/JavaScript dependencies keep their own licenses. Dependency managers fetch
them separately; consult package metadata and license files before redistribution.

EODHD, Tushare, exchange/index data, and Wind reference material are not relicensed
by this project. Purchased reference PDFs, real API responses, and private datasets
are excluded from this source release. Users supply their own access and must
separately obtain any necessary data redistribution rights.
