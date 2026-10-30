<#
.SYNOPSIS
    Empacota o Home Awake em dist\home-awake.zip: só os scripts e o LEIA-ME.

.DESCRIPTION
    Usado pelo build.ps1 e pelo workflow de release, para o zip sair igual nos dois.
    Lista permitida em vez de lista de exclusão: cadastro.txt e diagnostico.txt (rede e roteador de quem
    rodou o programa aqui), tests\ e arquivos de editor não entram no zip nem por acidente.

.EXAMPLE
    .\package-home-awake.ps1
    .\package-home-awake.ps1 -OutDir C:\temp\saida
#>
param([string]$OutDir = (Join-Path $PSScriptRoot 'dist'))

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'home-awake'
$files = @(Get-ChildItem $source -File | Where-Object {
        $_.Extension -in '.cmd', '.ps1', '.psm1' -or $_.Name -eq 'LEIA-ME.txt'
    })
if ($files.Count -eq 0) { throw "Nenhum arquivo para empacotar em $source" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir 'home-awake.zip'
if (Test-Path $zip) { Remove-Item $zip }
$files | Compress-Archive -DestinationPath $zip
$zip
