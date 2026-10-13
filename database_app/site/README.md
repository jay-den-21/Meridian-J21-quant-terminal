# EODHD Code Generator Website

Static CodeGen product page for the Mac installer download.

Build release artifacts first:

```bash
cd database_app
./scripts/package_macos_app.sh
```

Then open the page locally:

```bash
open site/index.html
```

The packaging script copies the generated DMG and PKG into `site/downloads/`.
The download files are ignored by git; publish them through a release host for production distribution.
