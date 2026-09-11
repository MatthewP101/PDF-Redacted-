$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -3.14 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt

# onedir avoids the onefile runtime extraction behaviour and is easier to audit.
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "SecurePDFRedactor" `
    app.py

Write-Host ""
Write-Host "Build complete: $PSScriptRoot\dist\SecurePDFRedactor\SecurePDFRedactor.exe"
Write-Host "Distribute the entire SecurePDFRedactor folder, not only the EXE."
