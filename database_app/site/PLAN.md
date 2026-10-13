# CodeGen Product Download Plan

This directory is the first static product page for the EODHD Code Generator Mac app.

## Goal

Create a CodeGen product page that lets a user download a local Mac installer and understand the local security model before installing it.

## Current MVP

- Static page: `site/index.html`
- Download buttons:
  - `site/downloads/EODHD-Code-Generator-1.0.0.dmg`
  - `site/downloads/EODHD-Code-Generator-1.0.0.pkg`
  - `site/downloads/SHA256SUMS.txt`
- Build command:
  - `cd database_app && ./scripts/package_macos_app.sh`
- Artifact behavior:
  - Builds `dist/EODHD Code Generator.app`
  - Builds `dist/EODHD-Code-Generator-1.0.0.dmg`
  - Builds `dist/EODHD-Code-Generator-1.0.0.pkg`
  - Builds `dist/SHA256SUMS.txt`
  - Copies DMG, PKG, and checksums into `site/downloads/`

## Website Sections

1. Hero
   - Product name as the first-viewport signal.
   - Short explanation: local EODHD code generation and small research execution.
   - Primary download button for DMG.
   - Secondary download button for PKG.

2. Install Locally
   - Download DMG.
   - Drag app into Applications, or install PKG.
   - Launch app and save the EODHD token through Login / Config.

3. Local Security Model
   - The app runs a loopback server bound to `127.0.0.1`.
   - API token stays in local app config.
   - Direct launch scripts unset `EODHD_API_KEY`, so normal desktop launch uses the Login / Config token.

4. Production Release Boundary
   - Current local build is unsigned and not notarized.
   - Public distribution should use Apple Developer ID signing and notarization.
   - Publish checksums next to the download link.

## Production Release Checklist

- Build the app on a clean Mac runner.
- Sign the `.app` and `.pkg` with a Developer ID certificate.
- Submit the release archive to Apple's notarization service.
- Staple the notarization ticket to the app or installer.
- Generate SHA-256 checksums for the DMG and PKG.
- Upload immutable release artifacts to a stable host, such as GitHub Releases, S3, R2, or a personal CDN.
- Update `site/index.html` download URLs to the hosted release assets.
- Add a short install FAQ for Gatekeeper warnings, Python 3.11+ requirement, and token storage.

## Hosting Options

- GitHub Pages:
  - Simple for a static product page.
  - Pair downloads with GitHub Releases instead of committing binary files.
- Cloudflare Pages:
  - Good default if the product site already uses Cloudflare.
  - Pair downloads with R2 for immutable release files.
- S3 plus CloudFront:
  - More operational control and checksum-friendly release storage.

## Known Limits Of The MVP Installer

- It does not bundle the Python runtime.
- It expects Python 3.11+ on the Mac, or `PYTHON_BIN` pointing to a compatible Python.
- It bundles pure Python dependencies used by the app: SQLAlchemy, PyMySQL, and typing_extensions.
- It is suitable for local developer distribution and personal use, not public Gatekeeper-clean distribution.
