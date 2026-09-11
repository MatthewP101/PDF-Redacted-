# Secure PDF Redactor

A local Windows desktop redaction app based on the supplied VBA detection rules.

## What it detects

- Email addresses
- Australian phone numbers matching the original `+61...` / `0...` rule
- Numeric dates in `dd/mm/yy`, `dd-mm-yyyy`, `dd.mm.yyyy`, etc.
- `MNI` followed by a 6–12 digit number
- Other standalone 6–12 digit identifiers

The MNI-specific hit takes precedence over a nested generic identifier so the same digits are not listed twice.

## Security design

1. The app makes no network requests and writes no logs containing detected values.
2. The original PDF is never overwritten.
3. Matching uses PyMuPDF character-level bounding boxes, not only plain-text search.
4. Redaction uses PDF redaction annotations followed by `apply_redactions()`, so content is removed rather than covered by a cosmetic rectangle.
5. After redaction, selected values are checked again against the source document's extractable text.
6. The redacted pages are rendered in memory and inserted into a brand-new PDF. This deliberately removes the original PDF object structure, hidden text, forms, annotations, JavaScript, attachments, metadata, layers, and revision history from the returned copy.
7. The flattened output is reopened and verified to contain the expected number of pages and no extractable text.
8. A SHA-256 hash of the returned PDF is shown on completion.
9. Pages that appear image-only/scanned or badly encoded are blocked from export because the current build has no OCR. This is intentional fail-safe behaviour.
10. Interactive PDF form fields are also blocked because their values are not reliably covered by the page-text regex scan.
11. Source annotations/comments are not rendered into the flattened output.

## Important limitation

Automatic regex detection is not the same as a complete privacy review. This version only detects the categories above. It does **not** detect names, street addresses, Medicare numbers, account numbers with separators, free-form case notes, faces, signatures, or arbitrary sensitive content unless they happen to match one of the configured rules.

A scanned page may visually contain sensitive information while exposing no machine-readable text. The app therefore blocks suspicious scanned/image-only pages instead of claiming they are safe.

## Run from source

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

PyMuPDF currently supports Python 3.14 on Windows.

## Build a standalone Windows app

From PowerShell in this folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

The build is created at:

```text
dist\SecurePDFRedactor\SecurePDFRedactor.exe
```

Distribute the entire `SecurePDFRedactor` folder. The target computer does not need Python installed.

`onedir` is used deliberately instead of PyInstaller `onefile`. One-file bundles extract their embedded runtime to a temporary directory when launched; `onedir` is simpler to inspect and avoids that extraction step.

## Production hardening before organisation-wide deployment

- Build on a clean, patched Windows machine or CI runner.
- Pin and verify dependency hashes in your build pipeline.
- Virus-scan the final distribution.
- Authenticode-sign the EXE and installer with your organisation's signing certificate.
- Keep the application non-admin; it does not require elevation.
- Restrict write permissions on the installed application directory.
- Add local OCR only if scanned PDFs are a requirement; do not use a cloud OCR/API for confidential documents unless the data handling arrangement explicitly permits it.
- Add a manual rectangle-redaction mode if users must redact names, addresses, signatures, or other free-form content.

## Licensing note

PyMuPDF / MuPDF is AGPL-licensed with commercial licensing available. If this app will be distributed as proprietary software or deployed by an organisation, review the licence obligations before rollout.

## Create a professional Windows installer

For distribution to another user, do **not** send the `dist` folder manually.
Build a single Windows installer instead:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_release.ps1
```

The first time you run it, the script will offer to install **Inno Setup 6** with
`winget` if the Inno compiler is not already installed.

The finished file is placed in:

```text
release\SecurePDFRedactor-Setup-1.0.0.exe
```

That is the only file you need to give the recipient. The installer installs the
application under the current user's local Programs directory, adds a Start Menu
shortcut, offers an optional desktop shortcut, and provides a normal Windows
uninstaller. The recipient does not need Python, VS Code, the source code, or the
PyInstaller build folder.

A SHA-256 checksum is also written to the `release` directory for release
verification.

### Windows trust / code signing

The installer is functional without a digital signature, but Windows may show an
"Unknown publisher" or SmartScreen warning for an unsigned installer. For wider
workplace distribution, sign both the application executable and the installer
with an Authenticode code-signing certificate. Do not tell recipients to disable
Windows security controls to bypass warnings.

### Licensing note

This project currently uses PyMuPDF. Review its licensing before distributing the
application within an organisation or as a closed-source product. If the intended
distribution is not compatible with the library licence, obtain the appropriate
commercial licence or replace the PDF backend with one whose licence fits the
project.
