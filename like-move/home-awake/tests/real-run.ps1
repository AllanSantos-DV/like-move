<#
Prova real, sem administrador, nesta máquina:
  A) fail-closed: o -Executar de verdade, sem a rede de casa, NÃO segura a tela (bit DISPLAY apagado),
     e o -Parar encerra o processo.
  B) mecanismo: com a rede de casa simulada, a API real liga o bit DISPLAY|SYSTEM; ao trocar de rede
     ele apaga; ao voltar acende; ao parar apaga.
  C) morte abrupta (Stop-Process -Force): o Windows libera o pedido sozinho.
  D) nenhuma configuração de bloqueio muda em nenhum momento (Get-LockSettings antes = durante = depois).
O estado é lido de OUTRO processo com CallNtPowerInformation(SystemExecutionState).
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $root 'HomeAwake.psm1') -Force
$DISPLAY = 2
$ps = (Get-Command powershell.exe).Source

function Show-State($label) {
    $s = Get-SystemExecutionState
    Write-Host ('{0,-48} SystemExecutionState=0x{1:X}  DISPLAY={2}' -f $label, $s, [bool]($s -band $DISPLAY))
    [bool]($s -band $DISPLAY)
}
function Assert($cond, $msg) { if (-not $cond) { throw "FALHA: $msg" } }
function Settings-Snapshot { (Get-LockSettings | ConvertTo-Json -Compress) }

$settingsBefore = Settings-Snapshot
Assert (-not (Show-State 'antes de tudo')) 'outro processo já segura a tela; feche-o e repita'

# --- A) fail-closed com o -Executar real -------------------------------------------------
$sandbox = Join-Path $env:TEMP ("home-awake-real-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path "$sandbox\like-move-home-awake" | Out-Null
@{ Ssid = 'Casa'; AuthAlgorithm = 7; GatewayMac = 'aa:bb:cc:00:00:01'; Bssids = @('11:22:33:44:55:66') } |
    ConvertTo-Json | Set-Content "$sandbox\like-move-home-awake\rede-de-casa.json" -Encoding UTF8
$realLocal = $env:LOCALAPPDATA
$env:LOCALAPPDATA = $sandbox   # cadastro e log do teste ficam no sandbox, não no perfil real
try {
    $runner = Start-Process $ps -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$root\home-awake.ps1`" -Executar" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 6
    Assert (-not $runner.HasExited) '-Executar saiu cedo'
    Assert (-not (Show-State 'A) -Executar real, sem a rede de casa')) 'segurou a tela fora de casa'
    $stopMsg = & $ps -NoProfile -ExecutionPolicy Bypass -File "$root\home-awake.ps1" -Parar
    "   -Parar: $stopMsg"
    Assert ($runner.WaitForExit(10000)) '-Executar não encerrou após -Parar'
    "   -Executar encerrou, exit code $($runner.ExitCode)"
    '   log do -Executar:'
    Get-Content "$sandbox\like-move-home-awake\home-awake.log" | ForEach-Object { "     $_" }
} finally {
    $env:LOCALAPPDATA = $realLocal
}
Assert ($settingsBefore -eq (Settings-Snapshot)) 'configuração de bloqueio mudou em A'

# --- B/C) API real com rede simulada --------------------------------------------------------
$flag = Join-Path $sandbox 'em-casa'
$stopFile = Join-Path $sandbox 'parar'
$child = Join-Path $sandbox 'child.ps1'
@"
Import-Module '$root\HomeAwake.psm1' -Force
`$enrolled = [pscustomobject]@{ Ssid = 'Casa'; AuthAlgorithm = 7; GatewayMac = 'aa:bb:cc:00:00:01'; Bssids = @('11:22:33:44:55:66') }
Invoke-HomeAwakeLoop -Enrolled `$enrolled ``
  -GetIdentity { `$ssid = if (Test-Path '$flag') { 'Casa' } else { 'Cafe' }
                 [pscustomobject]@{ Ssid = `$ssid; Bssid = '11:22:33:44:55:66'; AuthAlgorithm = 7; SecurityEnabled = `$true; GatewayMac = 'aa:bb:cc:00:00:01' } } ``
  -SetAwake { param(`$on) Set-KeepAwake `$on } ``
  -WaitForSignal { Start-Sleep -Milliseconds 500; if (Test-Path '$stopFile') { 'stop' } else { 'change' } } ``
  -Log { param(`$m) Add-Content '$sandbox\child.log' `$m }
"@ | Set-Content $child -Encoding UTF8

New-Item $flag -ItemType File | Out-Null
$p = Start-Process $ps -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$child`"" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
Assert ((Show-State 'B) rede de casa (simulada), API real')) 'não segurou a tela em casa'
$during = Settings-Snapshot
Remove-Item $flag; Start-Sleep -Seconds 3
Assert (-not (Show-State 'B) trocou para outra rede')) 'continuou segurando fora de casa'
New-Item $flag -ItemType File | Out-Null; Start-Sleep -Seconds 3
Assert ((Show-State 'B) voltou para a rede de casa')) 'não voltou a segurar em casa'
New-Item $stopFile -ItemType File | Out-Null
Assert ($p.WaitForExit(10000)) 'loop não parou'
Start-Sleep -Seconds 1
Assert (-not (Show-State 'B) parado normalmente')) 'pedido ficou após parar'
'   log do loop:'; Get-Content "$sandbox\child.log" | ForEach-Object { "     $_" }

Remove-Item $stopFile
$p = Start-Process $ps -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$child`"" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
Assert ((Show-State 'C) em casa, antes de matar o processo')) 'não segurou a tela em casa'
Stop-Process -Id $p.Id -Force
Start-Sleep -Seconds 2
Assert (-not (Show-State 'C) depois de Stop-Process -Force')) 'pedido ficou após morte abrupta'

# --- D) configurações intactas ------------------------------------------------------------------
$after = Settings-Snapshot
Assert ($settingsBefore -eq $during -and $during -eq $after) 'configuração de bloqueio mudou'
'D) configurações de bloqueio antes = durante = depois:'
"   $after"
Remove-Item $sandbox -Recurse -Force
'OK: A, B, C e D passaram'
