<#
.SYNOPSIS
    Build like-move.exe using PyInstaller.

.DESCRIPTION
    Installs PyInstaller (if missing), runs the spec file, and reports
    the size of the resulting executable.

.EXAMPLE
    .\build.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Push-Location $PSScriptRoot

try {
    # 1. Ensure PyInstaller is installed
    python -m PyInstaller --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[build] Installing PyInstaller...' -ForegroundColor Cyan
        pip install --user pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install PyInstaller' }
    } else {
        Write-Host '[build] PyInstaller already installed.' -ForegroundColor Green
    }

    # 2. Clean previous build artifacts
    if (Test-Path 'dist') { Remove-Item -Recurse -Force 'dist' }
    if (Test-Path 'build') { Remove-Item -Recurse -Force 'build' }

    # 3. Run PyInstaller
    Write-Host '[build] Running PyInstaller...' -ForegroundColor Cyan
    python -m PyInstaller like-move.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

    # 4. Report result
    $exe = 'dist\like-move.exe'
    if (Test-Path $exe) {
        $size = (Get-Item $exe).Length
        $sizeMB = [math]::Round($size / 1MB, 2)
        Write-Host ""
        Write-Host "[build] SUCCESS: $exe ($sizeMB MB)" -ForegroundColor Green
    } else {
        throw "Expected output not found: $exe"
    }
} finally {
    Pop-Location
}
