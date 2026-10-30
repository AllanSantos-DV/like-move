<#
.SYNOPSIS
    Build like-move (pasta onedir) e o zip de distribuição.

.DESCRIPTION
    Roda o spec do PyInstaller e empacota dist\like-move\ em dist\like-move-win64.zip.
    Também gera dist\home-awake.zip, pelo mesmo package-home-awake.ps1 que a CI usa.
    Com -CompileBootloader, reinstala o PyInstaller compilando o bootloader localmente
    (exige o compilador C do Visual Studio Build Tools): o bootloader pré-compilado é
    compartilhado por todo usuário de PyInstaller e aparece em listas de antivírus.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -CompileBootloader
#>
param([switch]$CompileBootloader)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Push-Location $PSScriptRoot

try {
    if ($CompileBootloader) {
        Write-Host '[build] Compilando o bootloader do PyInstaller...' -ForegroundColor Cyan
        $env:PYINSTALLER_COMPILE_BOOTLOADER = '1'
        python -m pip install --force-reinstall --no-binary pyinstaller pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o bootloader do PyInstaller' }
    } else {
        python -m PyInstaller --version 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller não instalado: pip install pyinstaller' }
    }

    if (Test-Path 'dist') { Remove-Item -Recurse -Force 'dist' }
    if (Test-Path 'build') { Remove-Item -Recurse -Force 'build' }

    Write-Host '[build] Rodando o PyInstaller...' -ForegroundColor Cyan
    python -m PyInstaller like-move.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

    $exe = 'dist\like-move\like-move.exe'
    if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

    $zip = 'dist\like-move-win64.zip'
    Compress-Archive -Path 'dist\like-move' -DestinationPath $zip
    $sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 2)
    $homeZip = & (Join-Path $PSScriptRoot 'package-home-awake.ps1')
    Write-Host ""
    Write-Host "[build] SUCCESS: $zip ($sizeMB MB) e $homeZip" -ForegroundColor Green
} finally {
    Pop-Location
}
