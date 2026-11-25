"""Detecção de inatividade e tela bloqueada via Win32 API (ctypes)."""

import ctypes
import ctypes.wintypes
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 DLLs
# ---------------------------------------------------------------------------
wt_dword = ctypes.wintypes.DWORD

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ---------------------------------------------------------------------------
# Estruturas Win32
# ---------------------------------------------------------------------------
class LASTINPUTINFO(ctypes.Structure):
    """Estrutura LASTINPUTINFO — tempo do último evento de input."""

    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.cbSize = ctypes.sizeof(LASTINPUTINFO)


# ---------------------------------------------------------------------------
# Protótipos de funções Win32
# ---------------------------------------------------------------------------
# BOOL GetLastInputInfo(PLASTINPUTINFO plii)
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = ctypes.wintypes.BOOL

# ULONGLONG GetTickCount64()
kernel32.GetTickCount64.argtypes = []
kernel32.GetTickCount64.restype = ctypes.c_uint64

# HDESK OpenInputDesktop(DWORD dwFlags, BOOL fInherit, DWORD dwDesiredAccess)
# Sem sufixo W — esta função não recebe strings
user32.OpenInputDesktop.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
]
user32.OpenInputDesktop.restype = ctypes.wintypes.HANDLE

# BOOL CloseDesktop(HDESK hDesktop)
user32.CloseDesktop.argtypes = [ctypes.wintypes.HANDLE]
user32.CloseDesktop.restype = ctypes.wintypes.BOOL


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------
def idle_ms_since(last_input_tick: int, current_tick: int) -> int:
    """Milissegundos entre o último input e agora, com os dois ticks em 32 bits.

    GetLastInputInfo devolve o tick no formato de GetTickCount (DWORD), que volta a zero a cada
    ~49,7 dias de uptime. A subtração módulo 2**32 dá o intervalo certo antes e depois da volta.
    """
    return (current_tick - last_input_tick) & 0xFFFFFFFF


def get_idle_time_ms() -> int:
    """Retorna o tempo de inatividade em milissegundos.

    Usa GetLastInputInfo para obter o tick do último input e
    GetTickCount64 para o tick atual. A diferença é o tempo idle.
    """
    lii = LASTINPUTINFO()
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        logger.warning("GetLastInputInfo falhou")
        return 0

    return idle_ms_since(lii.dwTime, kernel32.GetTickCount64())


def is_screen_locked() -> bool:
    """Verifica se a tela está bloqueada (Secure Desktop ativo).

    Usa OpenInputDesktop — retorna NULL quando a tela está bloqueada
    (Winlogon/Secure Desktop). Quando retorna um handle válido,
    fecha-o com CloseDesktop para evitar leak.
    """
    # Solicitar acesso mínimo (0) — só queremos saber se é acessível
    hdesk = user32.OpenInputDesktop(0, False, 0)

    if not hdesk:
        return True  # Tela bloqueada

    # Desktop acessível — fechar handle e reportar como desbloqueada
    try:
        user32.CloseDesktop(hdesk)
    except Exception:
        logger.warning("CloseDesktop falhou", exc_info=True)

    return False


class SYSTEM_POWER_STATUS(ctypes.Structure):
    """Estrutura SYSTEM_POWER_STATUS de GetSystemPowerStatus."""

    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
kernel32.GetSystemPowerStatus.restype = ctypes.wintypes.BOOL

user32.LockWorkStation.argtypes = []
user32.LockWorkStation.restype = ctypes.wintypes.BOOL

_powrprof = ctypes.WinDLL("powrprof")
_powrprof.CallNtPowerInformation.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
]
_powrprof.CallNtPowerInformation.restype = ctypes.c_long

_AC_OFFLINE = 0
_BATTERY_PERCENT_UNKNOWN = 255
_SYSTEM_EXECUTION_STATE = 16


def _power_status() -> SYSTEM_POWER_STATUS:
    status = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise OSError(f"GetSystemPowerStatus falhou (erro {ctypes.get_last_error()})")
    return status


def is_on_ac_power() -> bool:
    """True se o PC está na tomada. Status desconhecido (255) conta como tomada: desktops não têm bateria."""
    return _power_status().ACLineStatus != _AC_OFFLINE


def battery_percent() -> Optional[int]:
    """Carga da bateria em % (0 a 100); ``None`` quando o Windows não sabe (255) ou não há bateria."""
    percent = _power_status().BatteryLifePercent
    return None if percent > 100 else percent


def lock_workstation() -> None:
    """Bloqueia a tela do usuário (equivale a Win+L)."""
    if not user32.LockWorkStation():
        raise OSError(f"LockWorkStation falhou (erro {ctypes.get_last_error()})")


def get_execution_state() -> int:
    """Flags ES_* em vigor no sistema todo (soma dos pedidos de todos os programas), sem administrador."""
    state = ctypes.c_ulong(0)
    rc = _powrprof.CallNtPowerInformation(
        _SYSTEM_EXECUTION_STATE, None, 0, ctypes.byref(state), ctypes.sizeof(state),
    )
    if rc != 0:
        raise OSError(f"CallNtPowerInformation retornou 0x{rc & 0xFFFFFFFF:X}")
    return state.value


class PROCESSENTRY32W(ctypes.Structure):
    """Estrutura PROCESSENTRY32W do Toolhelp."""

    _fields_ = [
        ("dwSize", wt_dword), ("cntUsage", wt_dword), ("th32ProcessID", wt_dword),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt_dword), ("cntThreads", wt_dword),
        ("th32ParentProcessID", wt_dword), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt_dword),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt_dword), ("dwHighDateTime", wt_dword)]


_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_NO_MORE_FILES = 18

kernel32.CreateToolhelp32Snapshot.argtypes = [wt_dword, wt_dword]
kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = ctypes.wintypes.BOOL
kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = ctypes.wintypes.BOOL
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(_FILETIME)] * 3
kernel32.GetSystemTimes.restype = ctypes.wintypes.BOOL
kernel32.OpenProcess.argtypes = [wt_dword, ctypes.wintypes.BOOL, wt_dword]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, wt_dword, ctypes.c_wchar_p, ctypes.POINTER(wt_dword),
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
user32.EnumWindows.restype = ctypes.wintypes.BOOL
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(wt_dword)]


def running_process_names() -> set[str]:
    """Nomes (minúsculos, como ``blender.exe``) dos programas em execução agora."""
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, _INVALID_HANDLE):
        raise OSError(f"CreateToolhelp32Snapshot falhou (erro {ctypes.get_last_error()})")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        names: set[str] = set()
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != _ERROR_NO_MORE_FILES:
            raise OSError(f"Process32NextW falhou (erro {error})")
        return names
    finally:
        kernel32.CloseHandle(snapshot)


def visible_window_process_names() -> list[str]:
    """Nomes (minúsculos) dos programas com janela visível e título, em ordem alfabética: os que o usuário reconhece."""
    names: set[str] = set()
    failure: list[BaseException] = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def each(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            pid = wt_dword()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not handle:
                return True
            try:
                size = wt_dword(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    names.add(os.path.basename(buf.value).lower())
            finally:
                kernel32.CloseHandle(handle)
        except Exception as exc:  # o ctypes engoliria a exceção e pararia a enumeração em silêncio
            failure.append(exc)
            return False
        return True

    user32.EnumWindows(each, 0)
    if failure:
        raise OSError(f"EnumWindows falhou: {failure[0]}") from failure[0]
    return sorted(names)


def get_system_times() -> tuple[int, int, int]:
    """Tempos acumulados do sistema em intervalos de 100 ns: ``(ocioso, kernel, usuário)``; o kernel inclui o ocioso."""
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError(f"GetSystemTimes falhou (erro {ctypes.get_last_error()})")
    return tuple((t.dwHighDateTime << 32) | t.dwLowDateTime for t in (idle, kernel, user))  # type: ignore[return-value]


_IF_STRING_SIZE = 257
_IF_MAX_PHYS_ADDRESS_LENGTH = 32
_IF_TYPE_SOFTWARE_LOOPBACK = 24
_IF_FLAG_HARDWARE = 0x01
_IF_FLAG_FILTER = 0x02


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt_dword), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class MIB_IF_ROW2(ctypes.Structure):
    """Estrutura MIB_IF_ROW2 de GetIfTable2; os contadores de octetos são de 64 bits."""

    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64), ("InterfaceIndex", wt_dword), ("InterfaceGuid", _GUID),
        ("Alias", ctypes.c_wchar * _IF_STRING_SIZE), ("Description", ctypes.c_wchar * _IF_STRING_SIZE),
        ("PhysicalAddressLength", wt_dword),
        ("PhysicalAddress", ctypes.c_ubyte * _IF_MAX_PHYS_ADDRESS_LENGTH),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * _IF_MAX_PHYS_ADDRESS_LENGTH),
        ("Mtu", wt_dword), ("Type", wt_dword), ("TunnelType", wt_dword), ("MediaType", wt_dword),
        ("PhysicalMediumType", wt_dword), ("AccessType", wt_dword), ("DirectionType", wt_dword),
        ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
        ("OperStatus", wt_dword), ("AdminStatus", wt_dword), ("MediaConnectState", wt_dword),
        ("NetworkGuid", _GUID), ("ConnectionType", wt_dword),
        ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("InOctets", ctypes.c_uint64), ("InUcastPkts", ctypes.c_uint64), ("InNUcastPkts", ctypes.c_uint64),
        ("InDiscards", ctypes.c_uint64), ("InErrors", ctypes.c_uint64), ("InUnknownProtos", ctypes.c_uint64),
        ("InUcastOctets", ctypes.c_uint64), ("InMulticastOctets", ctypes.c_uint64),
        ("InBroadcastOctets", ctypes.c_uint64),
        ("OutOctets", ctypes.c_uint64), ("OutUcastPkts", ctypes.c_uint64), ("OutNUcastPkts", ctypes.c_uint64),
        ("OutDiscards", ctypes.c_uint64), ("OutErrors", ctypes.c_uint64), ("OutUcastOctets", ctypes.c_uint64),
        ("OutMulticastOctets", ctypes.c_uint64), ("OutBroadcastOctets", ctypes.c_uint64),
        ("OutQLen", ctypes.c_uint64),
    ]


class MIB_IF_TABLE2(ctypes.Structure):
    """Cabeçalho de MIB_IF_TABLE2: ``NumEntries`` linhas MIB_IF_ROW2 começam em ``Table``."""

    _fields_ = [("NumEntries", wt_dword), ("Table", MIB_IF_ROW2 * 1)]


_iphlpapi = ctypes.WinDLL("iphlpapi")
_iphlpapi.GetIfTable2.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
_iphlpapi.GetIfTable2.restype = wt_dword
_iphlpapi.FreeMibTable.argtypes = [ctypes.c_void_p]
_iphlpapi.FreeMibTable.restype = None


def physical_octets(rows) -> dict[int, tuple[int, int]]:
    """Octetos ``(recebidos, enviados)`` por índice só das placas de rede de verdade (``HardwareInterface``).

    Ficam de fora o loopback, as interfaces de filtro (WFP, QoS…) e os adaptadores virtuais e túneis (Hyper-V, VPN):
    todos repetem o tráfego da placa física, e somá-los contaria cada byte várias vezes.
    """
    wanted = _IF_FLAG_HARDWARE
    return {
        r.InterfaceIndex: (r.InOctets, r.OutOctets)
        for r in rows
        if r.Type != _IF_TYPE_SOFTWARE_LOOPBACK
        and r.InterfaceAndOperStatusFlags & (_IF_FLAG_HARDWARE | _IF_FLAG_FILTER) == wanted
    }


def get_interface_octets() -> dict[int, tuple[int, int]]:
    """Octetos ``(recebidos, enviados)`` acumulados por placa de rede (veja :func:`physical_octets`).

    Usa GetIfTable2 e não GetIfTable: o MIB_IFROW antigo lista também as interfaces de filtro e as virtuais como se
    fossem placas, com os mesmos contadores, sem marcar quais são, e tem contadores de 32 bits que voltam a zero.
    """
    table = ctypes.c_void_p()
    rc = _iphlpapi.GetIfTable2(ctypes.byref(table))
    if rc != 0:
        raise OSError(f"GetIfTable2 falhou (erro {rc})")
    try:
        count = wt_dword.from_address(table.value).value
        rows = (MIB_IF_ROW2 * count).from_address(table.value + MIB_IF_TABLE2.Table.offset)
        return physical_octets(rows)
    finally:
        _iphlpapi.FreeMibTable(table)
