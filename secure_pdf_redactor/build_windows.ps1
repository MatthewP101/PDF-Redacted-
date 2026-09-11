$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -3.14 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt

# onedir avoids the onefile runtime extraction behaviour. The installer then
# packages this directory so end users receive a single setup EXE.
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "SecurePDFRedactor" `
    app.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Application build complete:" -ForegroundColor Green
Write-Host "  $PSScriptRoot\dist\SecurePDFRedactor\SecurePDFRedactor.exe"
Write-Host ""
Write-Host "For a professional single-file installer, run:" -ForegroundColor Yellow
Write-Host "  .\build_release.ps1"
