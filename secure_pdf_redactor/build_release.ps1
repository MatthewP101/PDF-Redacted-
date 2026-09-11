$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== Secure PDF Redactor release build ===" -ForegroundColor Cyan
Write-Host ""

# 1. Build the normal self-contained application directory.
& "$PSScriptRoot\build_windows.ps1"

if (-not (Test-Path "$PSScriptRoot\dist\SecurePDFRedactor\SecurePDFRedactor.exe")) {
    throw "PyInstaller build did not produce dist\SecurePDFRedactor\SecurePDFRedactor.exe"
}

# 2. Locate the Inno Setup compiler.
function Find-InnoCompiler {
    # Select-Object is used instead of indexing pipeline output because a single
    # PowerShell string indexed with [0] returns only its first character.
    $candidate = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

    if ($candidate) {
        return [string]$candidate
    }

    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return [string]$cmd.Source
    }

    return $null
}

$iscc = Find-InnoCompiler

if (-not $iscc) {
    Write-Host ""
    Write-Host "Inno Setup 6 is required to create the single installer file." -ForegroundColor Yellow
    Write-Host ""

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        $answer = Read-Host "Install Inno Setup 6 now using winget? [Y/N]"
        if ($answer -match '^[Yy]') {
            & winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
            $iscc = Find-InnoCompiler
        }
    }

    if (-not $iscc) {
        Write-Host ""
        Write-Host "Install Inno Setup 6, then run .\build_release.ps1 again." -ForegroundColor Red
        Write-Host "With winget:" -ForegroundColor Yellow
        Write-Host "  winget install --id JRSoftware.InnoSetup -e" -ForegroundColor White
        exit 1
    }
}

# 3. Compile the installer.
if (Test-Path "$PSScriptRoot\release") {
    Remove-Item "$PSScriptRoot\release\SecurePDFRedactor-Setup-*.exe" -Force -ErrorAction SilentlyContinue
    Remove-Item "$PSScriptRoot\release\SecurePDFRedactor-Setup-*.sha256.txt" -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path "$PSScriptRoot\release" | Out-Null
}

Write-Host ""
Write-Host "Building installer..." -ForegroundColor Cyan
Write-Host "Using Inno Setup compiler: $iscc" -ForegroundColor DarkGray
& $iscc "$PSScriptRoot\installer.iss"

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$setup = Get-ChildItem "$PSScriptRoot\release\SecurePDFRedactor-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $setup) {
    throw "Installer compilation completed but no setup EXE was found in the release folder."
}

# 4. Produce a checksum for your own release verification.
$hash = Get-FileHash -Algorithm SHA256 $setup.FullName
$hashFile = "$setup.FullName.sha256.txt"
"$($hash.Hash)  $($setup.Name)" | Set-Content -Encoding ASCII $hashFile

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "RELEASE COMPLETE" -ForegroundColor Green
Write-Host ""
Write-Host "Give coworkers ONLY this installer:" -ForegroundColor White
Write-Host "  $($setup.FullName)" -ForegroundColor Cyan
Write-Host ""
Write-Host "SHA-256:" -ForegroundColor White
Write-Host "  $($hash.Hash)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "The installer contains the Python runtime and all required app files." -ForegroundColor White
Write-Host "The person installing it does not need Python, VS Code, or your source files." -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
