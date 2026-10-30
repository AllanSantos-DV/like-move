# Pester 3.4 (vem com o Windows): powershell -NoProfile -Command "Invoke-Pester .\tests\HomeAwake.Tests.ps1"
Import-Module (Join-Path (Split-Path $PSScriptRoot -Parent) 'HomeAwake.psm1') -Force

$home_ = [pscustomobject]@{ Ssid = 'Casa'; AuthAlgorithm = 7; GatewayMac = 'aa:bb:cc:00:00:01'; Bssids = @('11:22:33:44:55:66', '11:22:33:44:55:67') }
function New-Identity([hashtable]$Change = @{}) {
    $id = @{ Ssid = 'Casa'; Bssid = '11:22:33:44:55:66'; AuthAlgorithm = 7; SecurityEnabled = $true; GatewayMac = 'AA-BB-CC-00-00-01' }
    foreach ($k in $Change.Keys) { $id[$k] = $Change[$k] }
    [pscustomobject]$id
}

Describe 'Test-HomeNetwork: só confia na rede de casa cadastrada' {
    It 'confia quando SSID, segurança, BSSID e MAC do roteador batem' {
        (Test-HomeNetwork (New-Identity) $home_).Trusted | Should Be $true
    }
    It 'confia num segundo BSSID cadastrado da mesma casa' {
        (Test-HomeNetwork (New-Identity @{ Bssid = '11:22:33:44:55:67' }) $home_).Trusted | Should Be $true
    }
    It 'não confia sem cadastro' {
        (Test-HomeNetwork (New-Identity) $null).Trusted | Should Be $false
    }
    It 'não confia sem Wi-Fi (cabo, Wi-Fi desligado, sem adaptador)' {
        (Test-HomeNetwork $null $home_).Trusted | Should Be $false
    }
    It 'não confia em outro SSID' {
        (Test-HomeNetwork (New-Identity @{ Ssid = 'Cafe' }) $home_).Trusted | Should Be $false
    }
    It 'diferencia maiúsculas no SSID' {
        (Test-HomeNetwork (New-Identity @{ Ssid = 'casa' }) $home_).Trusted | Should Be $false
    }
    It 'não confia em rede aberta com o mesmo nome (evil twin sem senha)' {
        (Test-HomeNetwork (New-Identity @{ AuthAlgorithm = 1; SecurityEnabled = $false }) $home_).Trusted | Should Be $false
    }
    It 'não confia em OWE (criptografada mas sem senha)' {
        (Test-HomeNetwork (New-Identity @{ AuthAlgorithm = 10 }) $home_).Trusted | Should Be $false
    }
    It 'não confia se o tipo de segurança mudou' {
        (Test-HomeNetwork (New-Identity @{ AuthAlgorithm = 9 }) $home_).Trusted | Should Be $false
    }
    It 'não confia em BSSID não cadastrado' {
        (Test-HomeNetwork (New-Identity @{ Bssid = 'de:ad:be:ef:00:00' }) $home_).Trusted | Should Be $false
    }
    It 'não confia com MAC do roteador diferente' {
        (Test-HomeNetwork (New-Identity @{ GatewayMac = 'aa:bb:cc:00:00:02' }) $home_).Trusted | Should Be $false
    }
    It 'não confia enquanto o MAC do roteador não pode ser lido' {
        (Test-HomeNetwork (New-Identity @{ GatewayMac = $null }) $home_).Trusted | Should Be $false
    }
}

Describe 'New-HomeNetworkEnrollment: cadastro explícito' {
    It 'recusa sem Wi-Fi' {
        { New-HomeNetworkEnrollment $null $null } | Should Throw 'Não há Wi-Fi conectado'
    }
    It 'recusa rede sem senha' {
        { New-HomeNetworkEnrollment (New-Identity @{ AuthAlgorithm = 1; SecurityEnabled = $false }) $null } | Should Throw 'não tem senha'
    }
    It 'recusa sem MAC do roteador' {
        { New-HomeNetworkEnrollment (New-Identity @{ GatewayMac = $null }) $null } | Should Throw 'MAC do roteador'
    }
    It 'normaliza o MAC do roteador' {
        (New-HomeNetworkEnrollment (New-Identity) $null).GatewayMac | Should Be 'aa:bb:cc:00:00:01'
    }
    It 'acrescenta BSSID quando é a mesma rede em outra banda' {
        $e = New-HomeNetworkEnrollment (New-Identity @{ Bssid = '11:22:33:44:55:99' }) $home_
        $e.Bssids.Count | Should Be 3
        $e.Replaced | Should Be $false
    }
    It 'substitui quando a rede é outra' {
        $e = New-HomeNetworkEnrollment (New-Identity @{ Ssid = 'Nova'; GatewayMac = 'aa:bb:cc:00:00:09' }) $home_
        @($e.Bssids).Count | Should Be 1
        $e.Replaced | Should Be $true
    }
}

Describe 'Invoke-HomeAwakeLoop: acordado só na rede de casa, sempre liberado ao sair' {
    function Invoke-Scenario($identities) {
        $script:calls = New-Object System.Collections.Generic.List[bool]
        $script:queue = New-Object System.Collections.Queue (, $identities)
        Invoke-HomeAwakeLoop -Enrolled $home_ `
            -GetIdentity { $x = $script:queue.Dequeue(); if ($x -is [string] -and $x -eq 'throw') { throw 'falha simulada' }; $x } `
            -SetAwake { param($on) $script:calls.Add($on) } `
            -WaitForSignal { if ($script:queue.Count -eq 0) { 'stop' } else { 'change' } } `
            -Log { param($m) }
        , $script:calls.ToArray()
    }
    It 'liga em casa e libera ao parar' {
        Invoke-Scenario @((New-Identity)) | Should Be @($true, $false)
    }
    It 'desliga ao trocar para outra rede' {
        Invoke-Scenario @((New-Identity), (New-Identity @{ Ssid = 'Cafe' })) | Should Be @($true, $false, $false)
    }
    It 'desliga quando o Wi-Fi cai' {
        Invoke-Scenario @((New-Identity), $null) | Should Be @($true, $false, $false)
    }
    It 'erro ao ler a rede conta como fora de casa' {
        Invoke-Scenario @((New-Identity), 'throw') | Should Be @($true, $false, $false)
    }
    It 'libera mesmo se o loop morrer com exceção' {
        $script:released = $false
        { Invoke-HomeAwakeLoop -Enrolled $home_ -GetIdentity { New-Identity } `
            -SetAwake { param($on) if (-not $on) { $script:released = $true } } `
            -WaitForSignal { throw 'morreu' } -Log { param($m) } } | Should Throw 'morreu'
        $script:released | Should Be $true
    }
}

$base = [pscustomobject]@{
    InactivityTimeoutSecs = $null; ScreenSaverActive = 1; ScreenSaverSecure = $null; ScreenSaverTimeoutSecs = $null
    ScreenSaverExe = $null; VideoIdleAc = 0; VideoIdleDc = 0; StandbyIdleAc = 0; StandbyIdleDc = 0
    ConsoleLockAc = $null; ConsoleLockDc = $null; SlideshowAutoLock = $null; LockScreenAutoLock = $null
    DynamicLock = $null; HasBattery = $true; ModernStandby = $false
}
function New-Settings([hashtable]$Change) {
    $s = $base.PSObject.Copy()
    foreach ($k in $Change.Keys) { $s.$k = $Change[$k] }
    $s
}

Describe 'Get-LockDiagnosis: aponta a causa do bloqueio de 30 s' {
    It 'nenhuma causa quando nada bloqueia' {
        @(Get-LockDiagnosis $base).Count | Should Be 0
    }
    It 'proteção de tela segura de 30 s: evitável' {
        $c = Get-LockDiagnosis (New-Settings @{ ScreenSaverSecure = 1; ScreenSaverTimeoutSecs = 30; ScreenSaverExe = 'scrnsave.scr' })
        $c[0].Segundos | Should Be 30
        $c[0].HomeAwakeEvita | Should Be $true
    }
    It 'proteção de tela sem "exibir tela de logon" não bloqueia' {
        @(Get-LockDiagnosis (New-Settings @{ ScreenSaverSecure = 0; ScreenSaverTimeoutSecs = 30; ScreenSaverExe = 'x.scr' })).Count | Should Be 0
    }
    It 'limite de inatividade por política: não evitável, e aparece primeiro' {
        $c = Get-LockDiagnosis (New-Settings @{ InactivityTimeoutSecs = 30; ScreenSaverSecure = 1; ScreenSaverTimeoutSecs = 600; ScreenSaverExe = 'x.scr' })
        $c[0].Causa | Should Match 'limite de inatividade'
        $c[0].HomeAwakeEvita | Should Be $false
    }
    It 'slideshow "mostrar tela de bloqueio em vez de desligar a tela" com tela em 30 s na bateria' {
        $c = Get-LockDiagnosis (New-Settings @{ SlideshowAutoLock = 1; VideoIdleDc = 30; VideoIdleAc = 300 })
        $c[0].Segundos | Should Be 30
        $c[0].Causa | Should Match 'na bateria'
        $c[0].HomeAwakeEvita | Should Be $true
    }
    It 'desligar a tela sem tela de bloqueio nem Modern Standby não bloqueia' {
        @(Get-LockDiagnosis (New-Settings @{ VideoIdleAc = 30; ConsoleLockAc = 1 })).Count | Should Be 0
    }
    It 'Modern Standby: desligar a tela bloqueia quando entrar ao acordar está ligado' {
        $c = Get-LockDiagnosis (New-Settings @{ ModernStandby = $true; VideoIdleAc = 60; ConsoleLockAc = 1 })
        $c[0].Segundos | Should Be 60
    }
    It 'suspensão na bateria em Modern Standby traz o aviso dos 5 min' {
        $c = Get-LockDiagnosis (New-Settings @{ ModernStandby = $true; StandbyIdleDc = 120; ConsoleLockDc = 1 })
        $c[0].OQueFazer | Should Match '5 min'
    }
    It 'suspensão sem exigência de entrar ao acordar não bloqueia' {
        @(Get-LockDiagnosis (New-Settings @{ StandbyIdleAc = 120; ConsoleLockAc = 0 })).Count | Should Be 0
    }
    It 'bloqueio dinâmico: listado por último e não evitável' {
        $c = Get-LockDiagnosis (New-Settings @{ DynamicLock = 1; ScreenSaverSecure = 1; ScreenSaverTimeoutSecs = 60; ScreenSaverExe = 'x.scr' })
        $c[-1].Causa | Should Match 'Bloqueio dinâmico'
        $c[-1].HomeAwakeEvita | Should Be $false
    }
}

Describe 'Format-LockDiagnosis: relatório em português' {
    It 'informa que não há causa quando nenhuma é encontrada' {
        $text = Format-LockDiagnosis -Settings $base -Causes (Get-LockDiagnosis $base) -Identity $null -Enrolled $null
        ($text -join "`n") | Should Match 'Nenhuma causa de bloqueio'
    }
    It 'destaca a causa que dispara primeiro' {
        $s = New-Settings @{ SlideshowAutoLock = 1; VideoIdleDc = 30; ScreenSaverSecure = 1; ScreenSaverTimeoutSecs = 600; ScreenSaverExe = 'x.scr' }
        $text = Format-LockDiagnosis -Settings $s -Causes (Get-LockDiagnosis $s) -Identity $null -Enrolled $null
        ($text -join "`n") | Should Match 'CAUSA QUE DISPARA PRIMEIRO \(em 30 s\)'
    }
}

Describe 'Get-SelfCheckThreshold: o limite a verificar é o primeiro que dispararia' {
    It 'menor tempo entre as causas' {
        $causes = @([pscustomobject]@{ Segundos = 600 }, [pscustomobject]@{ Segundos = 30 }, [pscustomobject]@{ Segundos = $null })
        Get-SelfCheckThreshold $causes | Should Be 30
    }
    It 'nenhuma causa: sem limite' {
        ($null -eq (Get-SelfCheckThreshold @())) | Should Be $true
    }
    It 'só causa sem tempo fixo (bloqueio dinâmico): sem limite' {
        ($null -eq (Get-SelfCheckThreshold @([pscustomobject]@{ Segundos = $null }))) | Should Be $true
    }
}

Describe 'Add-SelfCheckSample / Get-SelfCheckVerdict: só prova o que foi observado com o pedido em vigor' {
    $t0 = Get-Date '2026-10-30 10:00:00'
    # Cada amostra: segundo desde t0, ociosidade, e o que mudar do estado saudável em casa.
    function New-Sample([double]$At, [double]$Idle, [hashtable]$Change = @{}) {
        $s = @{ Now = $t0.AddSeconds($At); Trusted = $true; RequestHeld = $true; IdleSeconds = $Idle; ScreenSaverRunning = $false; Locked = $false }
        foreach ($k in $Change.Keys) { $s[$k] = $Change[$k] }
        if (-not $s.ContainsKey('AnyHeld')) { $s.AnyHeld = $s.RequestHeld }
        [pscustomobject]$s
    }
    function Invoke-Run($check, $samples) { foreach ($s in $samples) { Add-SelfCheckSample $check $s }; $check }

    It 'sem amostras: aguardando' {
        Get-SelfCheckVerdict (New-SelfCheck 30 'x') | Should Be 'Aguardando'
    }
    It 'sem limite de bloqueio nas configurações: nada a confirmar' {
        Get-SelfCheckVerdict (Invoke-Run (New-SelfCheck $null $null) @((New-Sample 0 0), (New-Sample 5 5))) | Should Be 'NaoAplicavel'
    }
    It 'continua aguardando abaixo do limite mais a margem' {
        $c = New-SelfCheck 30 'x'
        Get-SelfCheckVerdict (Invoke-Run $c (0..7 | ForEach-Object { New-Sample ($_ * 5) ($_ * 5) })) | Should Be 'Aguardando'   # 35 s
    }
    It 'ociosidade anterior ao início da observação não conta' {
        $c = New-SelfCheck 30 'x'
        # a máquina já estava há 500 s ociosa quando o programa começou a observar: só 10 s observados
        Get-SelfCheckVerdict (Invoke-Run $c @((New-Sample 0 500), (New-Sample 5 505), (New-Sample 10 510))) | Should Be 'Aguardando'
    }
    It 'ociosidade fora de casa não conta' {
        $c = New-SelfCheck 30 'x'
        $away = 0..9 | ForEach-Object { New-Sample ($_ * 5) ($_ * 5) @{ Trusted = $false } }
        $c = Invoke-Run $c $away
        Get-SelfCheckVerdict (Invoke-Run $c @((New-Sample 50 50), (New-Sample 55 55))) | Should Be 'Aguardando'
    }
    It 'confirmado: observou mais que limite + margem parado em casa' {
        $c = New-SelfCheck 30 'x'
        Get-SelfCheckVerdict (Invoke-Run $c (0..9 | ForEach-Object { New-Sample ($_ * 5) (100 + $_ * 5) })) | Should Be 'Confirmado'   # 45 s observados >= 40
    }
    It 'mexer no mouse zera a ociosidade medida, não o tempo observado' {
        $c = New-SelfCheck 30 'x'
        $samples = @((New-Sample 0 100), (New-Sample 5 105), (New-Sample 10 0), (New-Sample 15 5), (New-Sample 20 10))
        $c = Invoke-Run $c $samples
        $c.MaxIdleHeld | Should Be 10
        $c.HeldSeconds | Should Be 20
    }
    It 'proteção de tela iniciou com o pedido ativo: risco confirmado' {
        $c = New-SelfCheck 30 'x'
        $c = Invoke-Run $c @((New-Sample 0 0), (New-Sample 5 29), (New-Sample 10 34 @{ ScreenSaverRunning = $true }))
        Get-SelfCheckVerdict $c | Should Be 'Risco'
        $c.Events[0] | Should Match 'proteção de tela iniciou'
    }
    It 'proteção de tela disparada à mão (pouco ocioso) não é risco' {
        $c = New-SelfCheck 600 'x'
        Get-SelfCheckVerdict (Invoke-Run $c @((New-Sample 0 0), (New-Sample 5 3 @{ ScreenSaverRunning = $true }))) | Should Not Be 'Risco'
    }
    It 'tela bloqueou perto do limite com o pedido ativo: risco confirmado' {
        $c = New-SelfCheck 30 'x'
        $samples = @((New-Sample 0 0)) + (1..6 | ForEach-Object { New-Sample ($_ * 5) ($_ * 5) }) + @((New-Sample 35 35 @{ Locked = $true }))
        $c = Invoke-Run $c $samples
        Get-SelfCheckVerdict $c | Should Be 'Risco'
        $c.Events[0] | Should Match 'a tela bloqueou'
    }
    It 'bloqueio manual (Win+L) logo depois de mexer não é risco' {
        $c = New-SelfCheck 30 'x'
        Get-SelfCheckVerdict (Invoke-Run $c @((New-Sample 0 2), (New-Sample 5 3), (New-Sample 10 8 @{ Locked = $true }))) | Should Be 'Aguardando'
    }
    It 'pedido ausente em casa: falha, anotada uma vez' {
        $c = New-SelfCheck 30 'x'
        $c = Invoke-Run $c @((New-Sample 0 0), (New-Sample 5 5 @{ RequestHeld = $false }), (New-Sample 10 10 @{ RequestHeld = $false }))
        Get-SelfCheckVerdict $c | Should Be 'Falha'
        $c.Events.Count | Should Be 1
    }
    It 'fora de casa o pedido ausente é o esperado' {
        $c = New-SelfCheck 30 'x'
        Get-SelfCheckVerdict (Invoke-Run $c @((New-Sample 0 0 @{ Trusted = $false; RequestHeld = $false }))) | Should Be 'Aguardando'
    }
    It 'intervalo grande entre amostras (suspensão) não conta como tempo observado' {
        $c = New-SelfCheck 30 'x'
        $c = Invoke-Run $c @((New-Sample 0 0), (New-Sample 3600 3600))
        $c.HeldSeconds | Should Be 0
    }
    It 'outro programa segurando a tela quando o pedido estava solto: inconclusivo, não confirmado' {
        $c = New-SelfCheck 30 'x'
        $samples = @((New-Sample 0 0 @{ Trusted = $false })) + (1..10 | ForEach-Object { New-Sample ($_ * 5) (100 + $_ * 5) })
        Get-SelfCheckVerdict (Invoke-Run $c $samples) | Should Be 'Inconclusivo'
    }
    It 'tela livre quando o pedido estava solto: a confirmação vale' {
        $c = New-SelfCheck 30 'x'
        $samples = @((New-Sample 0 0 @{ Trusted = $false; RequestHeld = $false })) + (1..10 | ForEach-Object { New-Sample ($_ * 5) (100 + $_ * 5) })
        Get-SelfCheckVerdict (Invoke-Run $c $samples) | Should Be 'Confirmado'
    }
    It 'risco vence confirmado' {
        $c = New-SelfCheck 30 'x'
        $c = Invoke-Run $c ((0..9 | ForEach-Object { New-Sample ($_ * 5) (100 + $_ * 5) }) + @((New-Sample 50 150 @{ ScreenSaverRunning = $true })))
        Get-SelfCheckVerdict $c | Should Be 'Risco'
    }
}

Describe 'Update-SelfCheck: leitura real falha em voz alta e o relatório vai para o arquivo' {
    $path = Join-Path $env:TEMP ('selfcheck-test-' + [guid]::NewGuid().ToString('N') + '.txt')
    It 'erro de leitura é anotado uma vez e não conta como amostra boa' {
        $script:logged = New-Object System.Collections.Generic.List[string]
        $c = New-SelfCheck 30 'x'
        1..3 | ForEach-Object { Update-SelfCheck -Check $c -Trusted $true -Log { param($m) $script:logged.Add($m) } -ReadSession { throw 'sem acesso' } -Path $path }
        $script:logged.Count | Should Be 1
        $script:logged[0] | Should Match 'leitura falhou: sem acesso'
        ($null -eq $c.PrevTime) | Should Be $true
    }
    It 'grava o relatório na primeira amostra e anota a mudança de resultado' {
        $script:logged = New-Object System.Collections.Generic.List[string]
        $c = New-SelfCheck 30 'x'
        $now = Get-Date
        Update-SelfCheck -Check $c -Trusted $true -Log { param($m) $script:logged.Add($m) } -Path $path `
            -ReadSession { [pscustomobject]@{ Now = $now; RequestHeld = $false; AnyHeld = $false; IdleSeconds = 1; ScreenSaverRunning = $false; Locked = $false } }
        Test-Path $path | Should Be $true
        (Get-SelfCheckReport $path) -join "`n" | Should Match 'FALHA'
        ($script:logged -join "`n") | Should Match 'resultado Aguardando -> Falha'
        Remove-Item $path
    }
    It 'sem arquivo, o relatório explica o que fazer' {
        (Get-SelfCheckReport (Join-Path $env:TEMP 'nao-existe-selfcheck.txt')) | Should Match 'Ainda não há autoverificação'
    }
}

Describe 'Format-SelfCheck: relatório em português' {
    It 'confirmado cita a ociosidade e o limite' {
        $c = New-SelfCheck 30 'Proteção de tela'
        $c.MaxIdleHeld = 95; $c.HeldSeconds = 600
        ((Format-SelfCheck $c) -join "`n") | Should Match 'CONFIRMADO: ficou 95 s sem mouse nem teclado'
    }
    It 'risco lista os eventos' {
        $c = New-SelfCheck 30 'x'
        $c.Risks = 1; $c.Events.Add('RISCO CONFIRMADO: teste')
        ((Format-SelfCheck $c) -join "`n") | Should Match 'Eventos:[\s\S]*RISCO CONFIRMADO: teste'
    }
}
