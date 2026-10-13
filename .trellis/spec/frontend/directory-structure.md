# Frontend Directory Structure

The public frontend belongs to `database_app/`:

- `src/eodhd_codegen_app/static/`: the served API playground UI.
- `site/`: the Code Generator product and download page.
- `site/downloads/`: ignored, locally generated installer output.

The two surfaces own their assets and do not import private sibling applications.
Keep server routes, endpoint validation, generated code, and export contracts in
the application package. Private personal/terminal frontends are not prerequisites
for public installation or tests.

Preview the static page with `python3 -m http.server 8766 --directory database_app/site`.
Run `eodhd-app` from the application's isolated environment for the actual tool.
