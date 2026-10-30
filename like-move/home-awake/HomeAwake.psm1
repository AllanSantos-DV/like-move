<#
Home Awake — mantém a tela sem bloquear SOMENTE na rede Wi-Fi de casa cadastrada.

Mecanismo: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED).
Não simula mouse/teclado, não usa rede, não altera configuração de bloqueio: o pedido
pertence ao processo e o Windows o descarta quando o processo termina, então não há
nada a "restaurar" (ver docs/adr/0002).
#>
Set-StrictMode -Version Latest

Add-Type -TypeDefinition @'
using System;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Threading;

namespace LikeMoveHomeAwake
{
    public static class Power
    {
        public const uint ES_CONTINUOUS = 0x80000000;
        public const uint ES_SYSTEM_REQUIRED = 0x00000001;
        public const uint ES_DISPLAY_REQUIRED = 0x00000002;

        [DllImport("kernel32.dll")]
        public static extern uint SetThreadExecutionState(uint esFlags);

        [DllImport("powrprof.dll")]
        public static extern uint CallNtPowerInformation(int level, IntPtr inBuf, uint inLen, out uint outBuf, uint outLen);

        [DllImport("powrprof.dll", EntryPoint = "CallNtPowerInformation")]
        public static extern uint CallNtPowerInformationBytes(int level, IntPtr inBuf, uint inLen, byte[] outBuf, uint outLen);
    }

    // Estado da sessão do usuário, lido sem administrador e sem alterar nada.
    public static class Session
    {
        const uint SPI_GETSCREENSAVERRUNNING = 0x0072;
        const uint DESKTOP_SWITCHDESKTOP = 0x0100;

        [StructLayout(LayoutKind.Sequential)]
        struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }

        [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
        [DllImport("user32.dll")] static extern bool SystemParametersInfo(uint action, uint param, ref int value, uint winIni);
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
        [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desktop);

        // Segundos desde o último mouse/teclado desta sessão.
        public static double IdleSeconds()
        {
            LASTINPUTINFO info = new LASTINPUTINFO();
            info.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
            if (!GetLastInputInfo(ref info)) throw new InvalidOperationException("GetLastInputInfo falhou: " + Marshal.GetLastWin32Error());
            return unchecked((uint)Environment.TickCount - info.dwTime) / 1000.0;
        }

        public static bool ScreenSaverRunning()
        {
            int running = 0;
            if (!SystemParametersInfo(SPI_GETSCREENSAVERRUNNING, 0, ref running, 0))
                throw new InvalidOperationException("SPI_GETSCREENSAVERRUNNING falhou: " + Marshal.GetLastWin32Error());
            return running != 0;
        }

        // Tela de bloqueio = desktop seguro ativo: a sessão não consegue abrir o desktop de entrada.
        public static bool Locked()
        {
            IntPtr desktop = OpenInputDesktop(0, false, DESKTOP_SWITCHDESKTOP);
            if (desktop == IntPtr.Zero) return true;
            CloseDesktop(desktop);
            return false;
        }
    }

    public class WifiConnection
    {
        public Guid InterfaceGuid;
        public string Ssid;
        public string Bssid;
        public uint AuthAlgorithm;
        public bool SecurityEnabled;
    }

    public static class Wlan
    {
        const uint ERROR_SUCCESS = 0;
        const uint ERROR_SERVICE_NOT_ACTIVE = 1062;
        const int OPCODE_CURRENT_CONNECTION = 7;
        const uint STATE_CONNECTED = 1;
        const int INTERFACE_INFO_SIZE = 532; // GUID(16) + WCHAR[256](512) + DWORD(4)

        [StructLayout(LayoutKind.Sequential)]
        struct DOT11_SSID
        {
            public uint Length;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public byte[] Ssid;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct WLAN_ASSOCIATION_ATTRIBUTES
        {
            public DOT11_SSID Ssid;
            public uint BssType;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] public byte[] Bssid;
            public uint PhyType;
            public uint PhyIndex;
            public uint SignalQuality;
            public uint RxRate;
            public uint TxRate;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct WLAN_SECURITY_ATTRIBUTES
        {
            public int SecurityEnabled;
            public int OneXEnabled;
            public uint AuthAlgorithm;
            public uint CipherAlgorithm;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct WLAN_CONNECTION_ATTRIBUTES
        {
            public uint State;
            public uint Mode;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string ProfileName;
            public WLAN_ASSOCIATION_ATTRIBUTES Association;
            public WLAN_SECURITY_ATTRIBUTES Security;
        }

        [DllImport("wlanapi.dll")] static extern uint WlanOpenHandle(uint version, IntPtr reserved, out uint negotiated, out IntPtr handle);
        [DllImport("wlanapi.dll")] static extern uint WlanCloseHandle(IntPtr handle, IntPtr reserved);
        [DllImport("wlanapi.dll")] static extern uint WlanEnumInterfaces(IntPtr handle, IntPtr reserved, out IntPtr list);
        [DllImport("wlanapi.dll")] static extern uint WlanQueryInterface(IntPtr handle, ref Guid iface, int opcode, IntPtr reserved, out uint size, out IntPtr data, IntPtr valueType);
        [DllImport("wlanapi.dll")] static extern void WlanFreeMemory(IntPtr memory);

        // null = nenhum Wi-Fi conectado (inclui serviço WLAN parado ou máquina sem Wi-Fi).
        // Qualquer outro erro da API lança exceção: quem chama trata como "rede não confirmada".
        public static WifiConnection GetCurrent()
        {
            uint negotiated;
            IntPtr handle;
            uint rc;
            try { rc = WlanOpenHandle(2, IntPtr.Zero, out negotiated, out handle); }
            catch (DllNotFoundException) { return null; }
            if (rc == ERROR_SERVICE_NOT_ACTIVE) return null;
            if (rc != ERROR_SUCCESS) throw new InvalidOperationException("WlanOpenHandle falhou: " + rc);
            try
            {
                IntPtr list;
                rc = WlanEnumInterfaces(handle, IntPtr.Zero, out list);
                if (rc != ERROR_SUCCESS) throw new InvalidOperationException("WlanEnumInterfaces falhou: " + rc);
                try
                {
                    int count = Marshal.ReadInt32(list);
                    for (int i = 0; i < count; i++)
                    {
                        Guid guid = (Guid)Marshal.PtrToStructure(new IntPtr(list.ToInt64() + 8 + i * INTERFACE_INFO_SIZE), typeof(Guid));
                        WifiConnection c = QueryConnection(handle, guid);
                        if (c != null) return c;
                    }
                    return null;
                }
                finally { WlanFreeMemory(list); }
            }
            finally { WlanCloseHandle(handle, IntPtr.Zero); }
        }

        static WifiConnection QueryConnection(IntPtr handle, Guid guid)
        {
            uint size;
            IntPtr data;
            // Interface desconectada responde com erro (ERROR_INVALID_STATE): não é falha.
            if (WlanQueryInterface(handle, ref guid, OPCODE_CURRENT_CONNECTION, IntPtr.Zero, out size, out data, IntPtr.Zero) != ERROR_SUCCESS)
                return null;
            try
            {
                WLAN_CONNECTION_ATTRIBUTES a = (WLAN_CONNECTION_ATTRIBUTES)Marshal.PtrToStructure(data, typeof(WLAN_CONNECTION_ATTRIBUTES));
                if (a.State != STATE_CONNECTED) return null;
                int len = (int)Math.Min(a.Association.Ssid.Length, 32u);
                WifiConnection c = new WifiConnection();
                c.InterfaceGuid = guid;
                c.Ssid = System.Text.Encoding.UTF8.GetString(a.Association.Ssid.Ssid, 0, len);
                c.Bssid = BitConverter.ToString(a.Association.Bssid).Replace('-', ':').ToLowerInvariant();
                c.AuthAlgorithm = a.Security.AuthAlgorithm;
                c.SecurityEnabled = a.Security.SecurityEnabled != 0;
                return c;
            }
            finally { WlanFreeMemory(data); }
        }
    }

    // Sinaliza mudança de endereço/disponibilidade de rede (conectar, desconectar, trocar de rede).
    public static class NetWatch
    {
        public static readonly AutoResetEvent Changed = new AutoResetEvent(false);
        static bool started;

        public static void Start()
        {
            if (started) return;
            started = true;
            NetworkChange.NetworkAddressChanged += delegate { Changed.Set(); };
            NetworkChange.NetworkAvailabilityChanged += delegate { Changed.Set(); };
        }
    }
}
'@

# DOT11_AUTH_ALGORITHM que exigem senha/credencial para associar. Ficam de fora:
# 1 aberta, 2 WEP, 5 não suportado, 10 OWE (criptografa, mas qualquer um entra).
$script:SecureAuthAlgorithms = @(3, 4, 6, 7, 8, 9, 11)

$script:DataDir = Join-Path $env:LOCALAPPDATA 'like-move-home-awake'
$script:EnrollmentPath = Join-Path $script:DataDir 'rede-de-casa.json'
$script:LogPath = Join-Path $script:DataDir 'home-awake.log'
$script:StopEventName = 'Local\LikeMoveHomeAwake.Stop'
$script:InstanceMutexName = 'Local\LikeMoveHomeAwake.Instance'

function ConvertTo-MacAddress([string]$Value) {
    if (-not $Value) { return $null }
    $Value.Trim().ToLowerInvariant().Replace('-', ':')
}

# ---------------------------------------------------------------------------
# Identidade da rede
# ---------------------------------------------------------------------------
function Get-GatewayMac([Guid]$InterfaceGuid) {
    $adapter = Get-NetAdapter -ErrorAction SilentlyContinue |
        Where-Object { [Guid]$_.InterfaceGuid -eq $InterfaceGuid } | Select-Object -First 1
    if (-not $adapter) { return $null }
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric | Select-Object -First 1
    if (-not $route) { return $null }
    # Só lê o cache ARP; nunca envia pacote. Entrada ausente/incompleta = rede não confirmada.
    $neighbor = Get-NetNeighbor -InterfaceIndex $adapter.ifIndex -IPAddress $route.NextHop -ErrorAction SilentlyContinue |
        Where-Object { $_.State -in 'Reachable', 'Stale', 'Delay', 'Probe', 'Permanent' } | Select-Object -First 1
    if (-not $neighbor) { return $null }
    ConvertTo-MacAddress $neighbor.LinkLayerAddress
}

function Get-NetworkIdentity {
    $wifi = [LikeMoveHomeAwake.Wlan]::GetCurrent()
    if (-not $wifi) { return $null }
    [pscustomobject]@{
        Ssid            = $wifi.Ssid
        Bssid           = $wifi.Bssid
        AuthAlgorithm   = [int]$wifi.AuthAlgorithm
        SecurityEnabled = $wifi.SecurityEnabled
        GatewayMac      = Get-GatewayMac $wifi.InterfaceGuid
    }
}

function Test-HomeNetwork {
    param($Current, $Enrolled)
    $no = { param($why) [pscustomobject]@{ Trusted = $false; Reason = $why } }
    if (-not $Enrolled) { return & $no 'nenhuma rede de casa cadastrada' }
    if (-not $Current) { return & $no 'sem Wi-Fi conectado' }
    if ($Current.Ssid -cne $Enrolled.Ssid) { return & $no 'Wi-Fi diferente da rede de casa' }
    if (-not $Current.SecurityEnabled -or $script:SecureAuthAlgorithms -notcontains [int]$Current.AuthAlgorithm) {
        return & $no 'rede sem senha'
    }
    if ([int]$Current.AuthAlgorithm -ne [int]$Enrolled.AuthAlgorithm) { return & $no 'tipo de segurança diferente do cadastrado' }
    if (@($Enrolled.Bssids) -notcontains (ConvertTo-MacAddress $Current.Bssid)) { return & $no 'ponto de acesso (BSSID) não cadastrado' }
    if (-not $Current.GatewayMac) { return & $no 'MAC do roteador ainda não disponível' }
    if ((ConvertTo-MacAddress $Current.GatewayMac) -ne $Enrolled.GatewayMac) { return & $no 'MAC do roteador diferente do cadastrado' }
    [pscustomobject]@{ Trusted = $true; Reason = 'rede de casa confirmada' }
}

# ---------------------------------------------------------------------------
# Cadastro (ação explícita do usuário)
# ---------------------------------------------------------------------------
function Get-HomeNetwork {
    if (-not (Test-Path $script:EnrollmentPath)) { return $null }
    Get-Content $script:EnrollmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function New-HomeNetworkEnrollment {
    # Puro: decide o novo cadastro a partir da rede atual e do cadastro anterior.
    param($Current, $Existing)
    if (-not $Current) { throw 'Não há Wi-Fi conectado. Conecte no Wi-Fi de casa e rode o cadastro de novo.' }
    if (-not $Current.SecurityEnabled -or $script:SecureAuthAlgorithms -notcontains [int]$Current.AuthAlgorithm) {
        throw "A rede '$($Current.Ssid)' não tem senha (WPA2/WPA3). Por segurança ela não pode ser cadastrada."
    }
    if (-not $Current.GatewayMac) { throw 'Não consegui ler o MAC do roteador. Abra um site qualquer e rode o cadastro de novo.' }
    $bssid = ConvertTo-MacAddress $Current.Bssid
    $gateway = ConvertTo-MacAddress $Current.GatewayMac
    $sameNetwork = $Existing -and $Existing.Ssid -ceq $Current.Ssid -and $Existing.GatewayMac -eq $gateway -and
        [int]$Existing.AuthAlgorithm -eq [int]$Current.AuthAlgorithm
    # Mesma rede em outra banda/repetidor: acrescenta o BSSID em vez de trocar o cadastro.
    $bssids = if ($sameNetwork) { @(@($Existing.Bssids) + $bssid | Select-Object -Unique) } else { @($bssid) }
    [pscustomobject]@{
        Ssid          = $Current.Ssid
        AuthAlgorithm = [int]$Current.AuthAlgorithm
        GatewayMac    = $gateway
        Bssids        = $bssids
        Replaced      = [bool]($Existing -and -not $sameNetwork)
    }
}

function Register-HomeNetwork {
    $enrollment = New-HomeNetworkEnrollment -Current (Get-NetworkIdentity) -Existing (Get-HomeNetwork)
    New-Item -ItemType Directory -Force -Path $script:DataDir | Out-Null
    $enrollment | Select-Object Ssid, AuthAlgorithm, GatewayMac, Bssids |
        ConvertTo-Json | Set-Content -Path $script:EnrollmentPath -Encoding UTF8
    $enrollment
}

function Unregister-HomeNetwork {
    if (Test-Path $script:EnrollmentPath) { Remove-Item $script:EnrollmentPath; return $true }
    $false
}

# ---------------------------------------------------------------------------
# Manter acordado (só na rede de casa)
# ---------------------------------------------------------------------------
function Set-KeepAwake([bool]$On) {
    $flags = if ($On) {
        [LikeMoveHomeAwake.Power]::ES_CONTINUOUS -bor [LikeMoveHomeAwake.Power]::ES_SYSTEM_REQUIRED -bor [LikeMoveHomeAwake.Power]::ES_DISPLAY_REQUIRED
    } else {
        [LikeMoveHomeAwake.Power]::ES_CONTINUOUS
    }
    if ([LikeMoveHomeAwake.Power]::SetThreadExecutionState($flags) -eq 0) { throw 'SetThreadExecutionState falhou' }
}

function Get-SystemExecutionState {
    # SystemExecutionState (16): flags ES_* em vigor no sistema, sem precisar de administrador.
    [uint32]$state = 0
    $rc = [LikeMoveHomeAwake.Power]::CallNtPowerInformation(16, [IntPtr]::Zero, 0, [ref]$state, 4)
    if ($rc -ne 0) { throw ('CallNtPowerInformation retornou 0x{0:X}' -f $rc) }
    $state
}

function Write-HomeAwakeLog([string]$Message) {
    New-Item -ItemType Directory -Force -Path $script:DataDir | Out-Null
    Add-Content -Path $script:LogPath -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message) -Encoding UTF8
}

# ---------------------------------------------------------------------------
# Autoverificação: prova, na própria máquina e sem administrador, que o pedido evita o bloqueio
# ---------------------------------------------------------------------------
# A doc de SetThreadExecutionState diz que ele não impede a proteção de tela; o teste do wakepy diz que
# impede (docs/research/home-awake-lock-prevention-research.md). Só a máquina real responde, então enquanto
# está na rede de casa o programa mede a ociosidade e anota o que aconteceu em autoverificacao.txt.
$script:SelfCheckPath = Join-Path $script:DataDir 'autoverificacao.txt'
$script:SelfCheckMarginSeconds = 10    # ociosidade acima do limite para valer como prova (jitter entre amostras)
$script:SelfCheckMaxGapSeconds = 120   # amostras mais espaçadas (suspensão, travamento) não contam como tempo observado

function Get-SelfCheckThreshold {
    # Puro: o menor tempo de ociosidade entre as causas de bloqueio encontradas (null = nenhuma).
    param($Causes)
    $secs = @($Causes | Where-Object { $_ -and $null -ne $_.Segundos } | ForEach-Object { [int]$_.Segundos })
    if ($secs.Count -eq 0) { return $null }
    ($secs | Measure-Object -Minimum).Minimum
}

function New-SelfCheck {
    param($ThresholdSeconds, [string]$ThresholdCause)
    [pscustomobject]@{
        ThresholdSeconds = $ThresholdSeconds
        ThresholdCause   = $ThresholdCause
        HeldSeconds      = 0.0    # tempo observado em casa
        ContinuousSeconds = 0.0   # tempo seguido com o pedido em vigor e a tela destravada
        MaxIdleHeld      = 0.0    # maior ociosidade já observada com o pedido em vigor e sem bloqueio
        Events           = New-Object System.Collections.Generic.List[string]
        Failures         = 0
        Risks            = 0
        RequestLost      = $false
        ForeignSeen      = $false   # outro programa segurava a tela na última vez que o nosso pedido estava solto
        ScreenSaverSeen  = $false
        PrevTime         = $null
        PrevTrusted      = $false
        PrevLocked       = $false
        PrevHeldIdle     = 0.0
        LastError        = $null
        LastSaved        = $null
    }
}

function Add-SelfCheckSample {
    <#
    Puro (só altera $Check). Sample: Now, Trusted, RequestHeld (SYSTEM e DISPLAY no estado do sistema),
    AnyHeld (SYSTEM ou DISPLAY), IdleSeconds, ScreenSaverRunning, Locked. Ociosidade só vale como prova enquanto o pedido esteve em vigor
    sem interrupção: ficar ocioso fora de casa, ou antes de o programa começar a observar, não conta.
    #>
    param($Check, $Sample)
    $c = $Check; $s = $Sample; $limit = $c.ThresholdSeconds
    $gap = if ($c.PrevTime) { ($s.Now - $c.PrevTime).TotalSeconds } else { 0 }
    $observed = $c.PrevTrusted -and $gap -gt 0 -and $gap -le $script:SelfCheckMaxGapSeconds

    # Fora de casa o nosso pedido está solto: se o estado do sistema segue ligado, é outro programa (vídeo, apresentação).
    if (-not $s.Trusted) { $c.ForeignSeen = [bool]$s.AnyHeld }
    if ($s.Trusted -and $observed) { $c.HeldSeconds += $gap }
    $healthy = $s.Trusted -and $s.RequestHeld -and -not $s.Locked -and -not $s.ScreenSaverRunning
    if ($healthy -and $observed) { $c.ContinuousSeconds += $gap } elseif (-not $healthy) { $c.ContinuousSeconds = 0.0 }
    $heldIdle = [Math]::Min([double]$s.IdleSeconds, $c.ContinuousSeconds)

    if ($s.Trusted) {
        if (-not $s.RequestHeld) {
            if (-not $c.RequestLost) {
                $c.RequestLost = $true; $c.Failures++
                $c.Events.Add('FALHA: o pedido de tela e sistema ligados não aparece no estado do sistema (o Windows o descartou?)')
            }
        } else { $c.RequestLost = $false }
        if ($null -ne $limit) {
            if ($s.ScreenSaverRunning -and $s.IdleSeconds -ge $limit) {
                if (-not $c.ScreenSaverSeen) {
                    $c.ScreenSaverSeen = $true; $c.Risks++
                    $c.Events.Add(('RISCO CONFIRMADO: a proteção de tela iniciou com o pedido ativo (ocioso há {0:N0} s, limite {1} s)' -f $s.IdleSeconds, $limit))
                }
            } elseif (-not $s.ScreenSaverRunning) { $c.ScreenSaverSeen = $false }
            if ($s.Locked -and -not $c.PrevLocked -and $c.PrevTrusted -and $c.PrevHeldIdle -ge ($limit - $script:SelfCheckMarginSeconds)) {
                $c.Risks++
                $c.Events.Add(('RISCO CONFIRMADO: a tela bloqueou com o pedido ativo (ocioso há ~{0:N0} s, limite {1} s)' -f $c.PrevHeldIdle, $limit))
            }
            if ($healthy -and $heldIdle -gt $c.MaxIdleHeld) { $c.MaxIdleHeld = $heldIdle }
        }
    }
    $c.PrevTime = $s.Now; $c.PrevTrusted = [bool]$s.Trusted; $c.PrevLocked = [bool]$s.Locked; $c.PrevHeldIdle = $heldIdle
}

function Get-SelfCheckVerdict {
    # Puro: Risco e Falha vencem tudo; Confirmado exige ociosidade acima do limite + margem com o pedido em vigor.
    param($Check)
    $c = $Check
    if ($c.Risks -gt 0) { return 'Risco' }
    if ($c.Failures -gt 0) { return 'Falha' }
    if ($null -eq $c.ThresholdSeconds) { return 'NaoAplicavel' }
    if ($c.MaxIdleHeld -ge ($c.ThresholdSeconds + $script:SelfCheckMarginSeconds)) {
        # Com outro programa segurando a tela, não bloquear não prova nada sobre o nosso pedido.
        if ($c.ForeignSeen) { return 'Inconclusivo' }
        return 'Confirmado'
    }
    'Aguardando'
}

function Format-SelfCheck {
    param($Check, [bool]$Running = $true)
    $c = $Check
    $limit = $c.ThresholdSeconds
    $cause = if ($c.ThresholdCause) { " (causa: $($c.ThresholdCause))" } else { '' }
    $result = switch (Get-SelfCheckVerdict $c) {
        'Confirmado' { ('CONFIRMADO: ficou {0:N0} s sem mouse nem teclado na rede de casa (limite do bloqueio: {1} s{2}) e a tela não bloqueou nem a proteção de tela iniciou.' -f $c.MaxIdleHeld, $limit, $cause) }
        'Risco'      { 'RISCO CONFIRMADO: o pedido NÃO bastou nesta máquina; veja os eventos. O Home Awake não muda configuração de bloqueio sozinho.' }
        'Falha'      { 'FALHA: o pedido de tela ligada não ficou em vigor; veja os eventos.' }
        'Inconclusivo' { 'INCONCLUSIVO: a tela não bloqueou, mas outro programa (vídeo, apresentação, outro keep-awake) também segurava a tela. Feche-os, deixe o notebook parado em casa e repita.' }
        'NaoAplicavel' { 'NADA A CONFIRMAR: as configurações lidas não têm bloqueio por inatividade. Se a tela bloquear mesmo assim, rode o 1-diagnosticar.cmd e envie o diagnostico.txt.' }
        default {
            if ($c.HeldSeconds -le 0) { 'AGUARDANDO: ainda não esteve na rede de casa.' }
            else { ('AGUARDANDO: em casa há {0:N0} min, mas a máquina ainda não ficou parada por mais de {1} s (limite {2} s{3} + margem). Deixe-a sem tocar no mouse/teclado.' -f ($c.HeldSeconds / 60), ($limit + $script:SelfCheckMarginSeconds), $limit, $cause) }
        }
    }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("Autoverificação do Home Awake — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') — $env:COMPUTERNAME")
    $lines.Add($result)
    $lines.Add(('Tempo observado em casa: {0:N1} min; maior ociosidade sem bloqueio: {1:N0} s; limite verificado: {2}.' -f ($c.HeldSeconds / 60), $c.MaxIdleHeld, $(if ($null -ne $limit) { "$limit s" } else { 'nenhum' })))
    $lines.Add("Programa: $(if ($Running) { 'rodando' } else { 'encerrado' })")
    if ($c.Events.Count -gt 0) {
        $lines.Add('Eventos:')
        foreach ($e in $c.Events) { $lines.Add("  - $e") }
    }
    $lines
}

function Save-SelfCheck {
    param($Check, [bool]$Running = $true, [string]$Path = $script:SelfCheckPath)
    New-Item -ItemType Directory -Force -Path (Split-Path $Path -Parent) | Out-Null
    Format-SelfCheck $Check $Running | Set-Content -Path $Path -Encoding UTF8
}

function Get-LiveSession {
    # Impuro: o que o Windows diz agora. Erro de leitura sobe: quem chama anota, nunca vira "tudo certo".
    $bits = (Get-SystemExecutionState) -band 3
    [pscustomobject]@{
        Now                = Get-Date
        RequestHeld        = $bits -eq 3
        AnyHeld            = $bits -ne 0
        IdleSeconds        = [LikeMoveHomeAwake.Session]::IdleSeconds()
        ScreenSaverRunning = [LikeMoveHomeAwake.Session]::ScreenSaverRunning()
        Locked             = [LikeMoveHomeAwake.Session]::Locked()
    }
}

function Update-SelfCheck {
    param($Check, [bool]$Trusted, [scriptblock]$Log, [scriptblock]$ReadSession = { Get-LiveSession }, [string]$Path = $script:SelfCheckPath)
    $before = Get-SelfCheckVerdict $Check
    $events = $Check.Events.Count
    try {
        $live = & $ReadSession
    } catch {
        $msg = "autoverificação: leitura falhou: $($_.Exception.Message)"
        if ($Check.LastError -ne $msg) { $Check.LastError = $msg; & $Log $msg }
        return
    }
    $Check.LastError = $null
    Add-SelfCheckSample $Check ([pscustomobject]@{
        Now = $live.Now; Trusted = $Trusted; RequestHeld = $live.RequestHeld; AnyHeld = $live.AnyHeld; IdleSeconds = $live.IdleSeconds
        ScreenSaverRunning = $live.ScreenSaverRunning; Locked = $live.Locked })
    for ($i = $events; $i -lt $Check.Events.Count; $i++) { & $Log "autoverificação: $($Check.Events[$i])" }
    $after = Get-SelfCheckVerdict $Check
    if ($after -ne $before) { & $Log "autoverificação: resultado $before -> $after" }
    # Grava ao mudar o resultado, a cada evento novo e a cada 5 min, para o relatório mostrar o andamento.
    $due = -not $Check.LastSaved -or ($live.Now - $Check.LastSaved).TotalSeconds -ge 300
    if ($after -ne $before -or $Check.Events.Count -ne $events -or $due) {
        Save-SelfCheck $Check $true $Path
        $Check.LastSaved = $live.Now
    }
}

function Get-SelfCheckReport {
    param([string]$Path = $script:SelfCheckPath)
    if (-not (Test-Path $Path)) { return 'Ainda não há autoverificação. Rode o 3-iniciar.cmd na rede de casa e deixe o notebook parado.' }
    Get-Content $Path -Encoding UTF8
}

function Invoke-HomeAwakeLoop {
    <#
    Reavalia a rede a cada sinal e mantém o pedido de "acordado" só enquanto a rede de casa
    estiver confirmada. Qualquer dúvida (erro, rede incompleta) conta como "fora de casa".
    WaitForSignal devolve 'stop', 'change' ou 'timeout'.
    #>
    param(
        [scriptblock]$GetIdentity,
        $Enrolled,
        [scriptblock]$SetAwake,
        [scriptblock]$WaitForSignal,
        [scriptblock]$Log
    )
    $awake = $null
    try {
        while ($true) {
            try {
                $verdict = Test-HomeNetwork -Current (& $GetIdentity) -Enrolled $Enrolled
            } catch {
                $verdict = [pscustomobject]@{ Trusted = $false; Reason = "erro ao ler a rede: $($_.Exception.Message)" }
            }
            & $SetAwake $verdict.Trusted
            if ($verdict.Trusted -ne $awake) {
                $what = if ($verdict.Trusted) { 'ATIVO: tela não bloqueia' } else { 'INATIVO: Windows bloqueia normalmente' }
                & $Log "$what ($($verdict.Reason))"
                $awake = $verdict.Trusted
            }
            if ((& $WaitForSignal) -eq 'stop') { break }
        }
    } finally {
        & $SetAwake $false
        & $Log 'encerrado: pedido liberado, Windows bloqueia normalmente'
    }
}

function New-StartupSelfCheck([scriptblock]$Log) {
    # Sem as configurações não há limite a verificar: anota e segue sem autoverificação de bloqueio.
    try {
        $causes = @(Get-LockDiagnosis (Get-LockSettings) | Where-Object { $_ })
        $limit = Get-SelfCheckThreshold $causes
        $cause = if ($limit) { ($causes | Where-Object { $_.Segundos -eq $limit } | Select-Object -First 1).Causa } else { $null }
    } catch {
        & $Log "autoverificação: não consegui ler as configurações de bloqueio: $($_.Exception.Message)"
        $limit = $null; $cause = $null
    }
    & $Log "autoverificação: limite de bloqueio $(if ($limit) { "$limit s ($cause)" } else { 'nenhum encontrado' }); relatório em $script:SelfCheckPath"
    $check = New-SelfCheck $limit $cause
    # Ainda sem pedido nosso: qualquer bit ligado agora é de outro programa.
    try { $check.ForeignSeen = ((Get-SystemExecutionState) -band 3) -ne 0 } catch { & $Log "autoverificação: não consegui ler o estado de energia: $($_.Exception.Message)" }
    Save-SelfCheck $check $true
    $check
}

function Start-HomeAwake {
    $created = $false
    $mutex = New-Object System.Threading.Mutex($true, $script:InstanceMutexName, [ref]$created)
    if (-not $created) { Write-HomeAwakeLog 'já está rodando; esta cópia saiu'; return }
    $stop = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::AutoReset, $script:StopEventName)
    try {
        $enrolled = Get-HomeNetwork
        Write-HomeAwakeLog "iniciado (rede cadastrada: $(if ($enrolled) { $enrolled.Ssid } else { 'nenhuma' }))"
        [LikeMoveHomeAwake.NetWatch]::Start()
        $handles = [System.Threading.WaitHandle[]]@($stop, [LikeMoveHomeAwake.NetWatch]::Changed)
        $log = { param($m) Write-HomeAwakeLog $m }
        $check = New-StartupSelfCheck $log
        $ctx = [pscustomobject]@{ Trusted = $false }
        try {
            Invoke-HomeAwakeLoop -Enrolled $enrolled `
                -GetIdentity { Get-NetworkIdentity } `
                -SetAwake { param($on) Set-KeepAwake $on; $ctx.Trusted = $on } `
                -Log $log `
                -WaitForSignal {
                    # 60 s: renova o pedido e reconfere a rede mesmo se algum evento se perder.
                    # A cada 5 s a autoverificação mede a ociosidade e o estado da tela.
                    $deadline = (Get-Date).AddSeconds(60)
                    while (($left = ($deadline - (Get-Date)).TotalMilliseconds) -gt 0) {
                        switch ([System.Threading.WaitHandle]::WaitAny($handles, [int][Math]::Min(5000, $left))) {
                            0 { return 'stop' }
                            1 { return 'change' }
                        }
                        Update-SelfCheck -Check $check -Trusted $ctx.Trusted -Log $log
                    }
                    'timeout'
                }
        } finally {
            Save-SelfCheck $check $false
        }
    } finally {
        $stop.Dispose()
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}

function Stop-HomeAwake {
    $stop = $null
    if (-not [System.Threading.EventWaitHandle]::TryOpenExisting($script:StopEventName, [ref]$stop)) { return $false }
    [void]$stop.Set()
    $stop.Dispose()
    $true
}

# ---------------------------------------------------------------------------
# Diagnóstico (somente leitura)
# ---------------------------------------------------------------------------
function Get-PowerSettingSeconds([string]$Subgroup, [string]$Setting) {
    # Os rótulos do powercfg mudam com o idioma; os dois últimos valores hex são sempre AC e DC.
    $hex = @(powercfg /qh SCHEME_CURRENT $Subgroup $Setting | Select-String '0x[0-9a-fA-F]+\s*$' |
        ForEach-Object { [Convert]::ToUInt32(($_.Line -replace '.*0x', ''), 16) })
    if ($hex.Count -lt 2) { return [pscustomobject]@{ Ac = $null; Dc = $null } }
    [pscustomobject]@{ Ac = $hex[-2]; Dc = $hex[-1] }
}

function Get-RegistryValue([string]$Path, [string]$Name) {
    $item = Get-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
    if ($item) { $item.$Name } else { $null }
}

function Get-LockSettings {
    $desktop = 'HKCU:\Control Panel\Desktop'
    $policy = 'HKCU:\Software\Policies\Microsoft\Windows\Control Panel\Desktop'
    $pick = { param($name) $p = Get-RegistryValue $policy $name; if ($null -ne $p) { $p } else { Get-RegistryValue $desktop $name } }
    $caps = New-Object byte[] 76
    [void][LikeMoveHomeAwake.Power]::CallNtPowerInformationBytes(4, [IntPtr]::Zero, 0, $caps, 76)
    $video = Get-PowerSettingSeconds 'SUB_VIDEO' 'VIDEOIDLE'
    $sleep = Get-PowerSettingSeconds 'SUB_SLEEP' 'STANDBYIDLE'
    $consoleLock = Get-PowerSettingSeconds 'SUB_NONE' 'CONSOLELOCK'
    $toInt = { param($v) if ($null -eq $v -or "$v" -eq '') { $null } else { [int]"$v" } }
    [pscustomobject]@{
        InactivityTimeoutSecs  = & $toInt (Get-RegistryValue 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs')
        ScreenSaverActive      = & $toInt (& $pick 'ScreenSaveActive')
        ScreenSaverSecure      = & $toInt (& $pick 'ScreenSaverIsSecure')
        ScreenSaverTimeoutSecs = & $toInt (& $pick 'ScreenSaveTimeOut')
        ScreenSaverExe         = & $pick 'SCRNSAVE.EXE'
        VideoIdleAc            = $video.Ac
        VideoIdleDc            = $video.Dc
        StandbyIdleAc          = $sleep.Ac
        StandbyIdleDc          = $sleep.Dc
        ConsoleLockAc          = $consoleLock.Ac
        ConsoleLockDc          = $consoleLock.Dc
        SlideshowAutoLock      = & $toInt (Get-RegistryValue 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lock Screen' 'SlideshowAutoLock')
        LockScreenAutoLock     = & $toInt (Get-RegistryValue $desktop 'LockScreenAutoLockActive')
        DynamicLock            = & $toInt (Get-RegistryValue 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Winlogon' 'EnableGoodbye')
        HasBattery             = [bool](Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
        ModernStandby          = $caps[20] -ne 0   # SYSTEM_POWER_CAPABILITIES.AoAc
    }
}

function Get-LockDiagnosis {
    # Puro: transforma as configurações lidas em causas de bloqueio, da que dispara primeiro à última.
    param($Settings)
    $s = $Settings
    $causes = New-Object System.Collections.Generic.List[object]
    $add = { param($name, $secs, $prevented, $action)
        $causes.Add([pscustomobject]@{ Causa = $name; Segundos = $secs; HomeAwakeEvita = $prevented; OQueFazer = $action }) }

    if ($s.InactivityTimeoutSecs -gt 0) {
        & $add 'Política "Logon interativo: limite de inatividade da máquina"' $s.InactivityTimeoutSecs $false `
            'É política de segurança: o Home Awake não contorna. Se o notebook é seu e foi você que definiu, altere em secpol.msc > Políticas Locais > Opções de Segurança (exige administrador).'
    }
    if ($s.ScreenSaverActive -eq 1 -and $s.ScreenSaverSecure -eq 1 -and $s.ScreenSaverTimeoutSecs -gt 0 -and $s.ScreenSaverExe) {
        & $add 'Proteção de tela com "Ao reiniciar, exibir tela de logon"' $s.ScreenSaverTimeoutSecs $true `
            'O pedido de tela ligada (ES_DISPLAY_REQUIRED) impede a proteção de tela de iniciar. Nada a mudar.'
    }
    $displayLocks = $s.SlideshowAutoLock -eq 1 -or $s.LockScreenAutoLock -eq 1 -or ($s.ModernStandby -and $s.ConsoleLockAc -ne 0)
    foreach ($p in @(@('na tomada', $s.VideoIdleAc), @('na bateria', $s.VideoIdleDc))) {
        if ($displayLocks -and $p[1] -gt 0) {
            & $add "Desligar a tela após inatividade ($($p[0])) seguido de tela de bloqueio" $p[1] $true `
                'O pedido de tela ligada zera o contador de desligar a tela. Nada a mudar.'
        }
    }
    foreach ($p in @(@('na tomada', $s.StandbyIdleAc, $s.ConsoleLockAc), @('na bateria', $s.StandbyIdleDc, $s.ConsoleLockDc))) {
        if ($p[1] -gt 0 -and $p[2] -ne 0) {
            $note = if ($p[0] -eq 'na bateria' -and $s.ModernStandby) { ' Atenção: em Modern Standby na bateria o Windows pode descartar o pedido 5 min após o tempo de suspensão; prefira deixar na tomada.' } else { '' }
            & $add "Suspender após inatividade ($($p[0])) com exigência de entrar ao acordar" $p[1] $true `
                ('O pedido de sistema ligado (ES_SYSTEM_REQUIRED) impede a suspensão. Nada a mudar.' + $note)
        }
    }
    if ($s.DynamicLock -eq 1) {
        & $add 'Bloqueio dinâmico (celular Bluetooth se afastou)' $null $false `
            'Não é por inatividade: o Home Awake não interfere. Se for esse o caso, desligue em Configurações > Contas > Opções de entrada > Bloqueio dinâmico.'
    }
    @($causes | Sort-Object @{ Expression = { if ($null -eq $_.Segundos) { [int]::MaxValue } else { $_.Segundos } } })
}

function Format-LockDiagnosis {
    param($Settings, $Causes, $Identity, $Enrolled)
    $Causes = @($Causes | Where-Object { $_ })   # lista vazia chega como $null pelo pipeline
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("Diagnóstico do bloqueio de tela — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') — $env:COMPUTERNAME")
    $lines.Add('(somente leitura: nada foi alterado)')
    $lines.Add('')
    if ($Causes.Count -eq 0) {
        $lines.Add('Nenhuma causa de bloqueio por inatividade encontrada nas configurações.')
    } else {
        $first = $Causes[0]
        $when = if ($null -ne $first.Segundos) { "em $($first.Segundos) s" } else { 'sem tempo fixo' }
        $lines.Add("CAUSA QUE DISPARA PRIMEIRO ($when): $($first.Causa)")
        $lines.Add("  Home Awake evita? $(if ($first.HomeAwakeEvita) { 'SIM' } else { 'NÃO' }) — $($first.OQueFazer)")
        $lines.Add('')
        $lines.Add('Todas as causas encontradas:')
        foreach ($c in $Causes) {
            $secs = if ($null -ne $c.Segundos) { "$($c.Segundos) s" } else { '-' }
            $lines.Add("  - [$secs] $($c.Causa) | evita: $(if ($c.HomeAwakeEvita) { 'sim' } else { 'não' })")
        }
    }
    $lines.Add('')
    $lines.Add('Rede atual:')
    if ($Identity) {
        $lines.Add("  Wi-Fi '$($Identity.Ssid)' BSSID $($Identity.Bssid) segurança $($Identity.AuthAlgorithm) MAC do roteador $(if ($Identity.GatewayMac) { $Identity.GatewayMac } else { '(indisponível)' })")
    } else {
        $lines.Add('  sem Wi-Fi conectado')
    }
    $verdict = Test-HomeNetwork -Current $Identity -Enrolled $Enrolled
    $lines.Add("  Rede de casa: $(if ($verdict.Trusted) { 'CONFIRMADA' } else { "não ($($verdict.Reason))" })")
    $lines.Add('')
    $lines.Add('Valores lidos:')
    foreach ($p in $Settings.PSObject.Properties) { $lines.Add("  $($p.Name) = $($p.Value)") }
    $lines
}

Export-ModuleMember -Function Get-NetworkIdentity, Test-HomeNetwork, Get-HomeNetwork, New-HomeNetworkEnrollment,
    Register-HomeNetwork, Unregister-HomeNetwork, Set-KeepAwake, Get-SystemExecutionState, Invoke-HomeAwakeLoop,
    Start-HomeAwake, Stop-HomeAwake, Get-LockSettings, Get-LockDiagnosis, Format-LockDiagnosis, Write-HomeAwakeLog,
    Get-SelfCheckThreshold, New-SelfCheck, Add-SelfCheckSample, Get-SelfCheckVerdict, Format-SelfCheck,
    Save-SelfCheck, Update-SelfCheck, Get-SelfCheckReport, Get-LiveSession
