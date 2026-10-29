<#
.SYNOPSIS
    Prova que keep_awake.pyw mantém a máquina acordada: o pedido aparece em
    `powercfg /requests` enquanto roda e some quando o processo termina.
    powercfg /requests exige PowerShell como administrador.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script = Join-Path (Split-Path $PSScriptRoot -Parent) 'keep_awake.pyw'
$pythonw = (Get-Command pythonw.exe).Source

function Get-Requests { (powercfg /requests) -join "`n" }
function Get-Section($text, $name) {
    [regex]::Match($text, "(?ms)^$name`:\s*\n(.*?)(?=^[A-Z]+:\s*$|\z)").Groups[1].Value
}

$before = Get-Requests
if ($before -notmatch '(?m)^DISPLAY:') {
    throw "powercfg /requests sem saída válida (precisa de PowerShell elevado):`n$before"
}
foreach ($s in 'DISPLAY', 'SYSTEM') {
    if ((Get-Section $before $s) -match 'pythonw\.exe') {
        throw "pré-condição: já existe pythonw.exe em $s antes do teste; feche-o e rode de novo"
    }
}

$proc = Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 3
    $during = Get-Requests
    Write-Host $during
    foreach ($s in 'DISPLAY', 'SYSTEM') {
        if ((Get-Section $during $s) -notmatch 'pythonw\.exe') {
            throw "FALHA: $s sem pythonw.exe durante a execução"
        }
    }
    Write-Host 'OK: DISPLAY e SYSTEM listam pythonw.exe enquanto roda'
} finally {
    Stop-Process -Id $proc.Id -Force
}

Start-Sleep -Seconds 2
$after = Get-Requests
foreach ($s in 'DISPLAY', 'SYSTEM') {
    if ((Get-Section $after $s) -match 'pythonw\.exe') { throw "FALHA: $s ainda lista pythonw.exe após encerrar" }
}
Write-Host 'OK: pedido removido após encerrar o processo'
