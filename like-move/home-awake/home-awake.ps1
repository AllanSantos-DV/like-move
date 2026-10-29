<#
.SYNOPSIS
    Home Awake: a tela não bloqueia por inatividade SOMENTE na rede Wi-Fi de casa cadastrada.
.DESCRIPTION
    -Diagnosticar  lê (sem alterar nada) o que bloqueia a tela e grava diagnostico.txt ao lado do script
    -Cadastrar     cadastra o Wi-Fi conectado agora como rede de casa e grava cadastro.txt
    -Executar      fica rodando (sem janela) e só mantém a tela acordada na rede de casa
    -Parar         pede ao -Executar para encerrar; o Windows volta a bloquear normalmente
    -Esquecer      apaga o cadastro da rede de casa
#>
param(
    [switch]$Diagnosticar,
    [switch]$Cadastrar,
    [switch]$Executar,
    [switch]$Parar,
    [switch]$Esquecer
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'HomeAwake.psm1') -Force

if ($Diagnosticar) {
    $settings = Get-LockSettings
    $report = Format-LockDiagnosis -Settings $settings -Causes (Get-LockDiagnosis $settings) `
        -Identity (Get-NetworkIdentity) -Enrolled (Get-HomeNetwork)
    $out = Join-Path $PSScriptRoot 'diagnostico.txt'
    $report | Set-Content -Path $out -Encoding UTF8
    $report
    "`nSalvo em: $out"
}
elseif ($Cadastrar) {
    $out = Join-Path $PSScriptRoot 'cadastro.txt'
    try {
        $e = Register-HomeNetwork
        $msg = @(
            "Rede de casa cadastrada: '$($e.Ssid)'"
            "  MAC do roteador: $($e.GatewayMac)"
            "  Pontos de acesso (BSSID): $($e.Bssids -join ', ')"
        )
        if ($e.Replaced) { $msg += '  (substituiu o cadastro anterior, que era de outra rede)' }
        $msg += 'Se a casa tem outro ponto de acesso/banda (2,4 e 5 GHz), conecte nele e cadastre de novo para acrescentar.'
    } catch {
        $msg = @("CADASTRO NÃO FEITO: $($_.Exception.Message)")
        $msg | Set-Content -Path $out -Encoding UTF8
        $msg
        exit 1
    }
    $msg | Set-Content -Path $out -Encoding UTF8
    $msg
}
elseif ($Executar) {
    Start-HomeAwake
}
elseif ($Parar) {
    if (Stop-HomeAwake) { 'Pedido de parada enviado. O Windows volta a bloquear normalmente.' }
    else { 'O Home Awake não estava rodando.' }
}
elseif ($Esquecer) {
    if (Unregister-HomeNetwork) { 'Cadastro da rede de casa apagado.' } else { 'Não havia rede cadastrada.' }
}
else {
    Get-Help $PSCommandPath -Detailed
}
