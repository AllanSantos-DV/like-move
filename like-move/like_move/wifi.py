"""Detecção da rede Wi-Fi atual (SSID + BSSID) via WLAN API (ctypes).

Usa exclusivamente ``wlanapi.dll`` através de ``ctypes`` — sem dependências
externas (nada de ``netsh`` nem ``pywifi``). O fluxo é:

    WlanOpenHandle → WlanEnumInterfaces → WlanQueryInterface
    (opcode ``wlan_intf_opcode_current_connection`` = 7)

De ``WLAN_CONNECTION_ATTRIBUTES`` extraímos o SSID (``DOT11_SSID``) e o
BSSID (``DOT11_MAC_ADDRESS`` — o MAC do ponto de acesso). O BSSID é usado
para reforçar a checagem de rede confiável contra "evil-twin" (uma rede
pública com o mesmo nome do seu Wi-Fi de casa).

Motivação de segurança: manter a tela acordada só é desejável em redes
confiáveis; em redes públicas/desconhecidas o ideal é deixar bloquear.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import time
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes WLAN
# ---------------------------------------------------------------------------
ERROR_SUCCESS: int = 0
WLAN_CLIENT_VERSION: int = 2  # Vista+ (2)
WLAN_INTF_OPCODE_CURRENT_CONNECTION: int = 7
WLAN_INTERFACE_STATE_CONNECTED: int = 1
DOT11_SSID_MAX_LENGTH: int = 32

_CACHE_TTL_SECONDS: float = 3.0


# ---------------------------------------------------------------------------
# Estruturas Win32 / WLAN
# ---------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_uint),  # WLAN_INTERFACE_STATE
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        # Array flexível — acessado via ponteiro para o primeiro elemento
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", ctypes.c_ulong),
        ("ucSSID", ctypes.c_ubyte * DOT11_SSID_MAX_LENGTH),
    ]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", ctypes.c_uint),           # DOT11_BSS_TYPE
        ("dot11Bssid", ctypes.c_ubyte * 6),        # DOT11_MAC_ADDRESS
        ("dot11PhyType", ctypes.c_uint),           # DOT11_PHY_TYPE
        ("uDot11PhyIndex", ctypes.c_ulong),
        ("wlanSignalQuality", ctypes.c_ulong),
        ("ulRxRate", ctypes.c_ulong),
        ("ulTxRate", ctypes.c_ulong),
    ]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", wintypes.BOOL),
        ("bOneXEnabled", wintypes.BOOL),
        ("dot11AuthAlgorithm", ctypes.c_uint),
        ("dot11CipherAlgorithm", ctypes.c_uint),
    ]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", ctypes.c_uint),                # WLAN_INTERFACE_STATE
        ("wlanConnectionMode", ctypes.c_uint),     # WLAN_CONNECTION_MODE
        ("strProfileName", ctypes.c_wchar * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
    ]


class ConnectionInfo(NamedTuple):
    """Resultado da consulta da conexão Wi-Fi atual."""

    connected: bool          # há um Wi-Fi conectado no momento
    ssid: Optional[str]      # nome da rede (se conectado)
    bssid: Optional[str]     # MAC do AP em minúsculas "aa:bb:.." (se conectado)
    wifi_present: bool       # existe ao menos um adaptador Wi-Fi na máquina


# ---------------------------------------------------------------------------
# Carga da DLL (tolerante a ambientes sem wlanapi / não-Windows)
# ---------------------------------------------------------------------------
def _load_wlanapi():
    try:
        wlan = ctypes.WinDLL("wlanapi", use_last_error=True)  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        logger.info("wlanapi.dll indisponível — detecção de Wi-Fi desativada")
        return None

    wlan.WlanOpenHandle.argtypes = [
        wintypes.DWORD, ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE),
    ]
    wlan.WlanOpenHandle.restype = wintypes.DWORD

    wlan.WlanEnumInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)),
    ]
    wlan.WlanEnumInterfaces.restype = wintypes.DWORD

    wlan.WlanQueryInterface.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_int, ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_int),
    ]
    wlan.WlanQueryInterface.restype = wintypes.DWORD

    wlan.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    wlan.WlanFreeMemory.restype = None

    wlan.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    wlan.WlanCloseHandle.restype = wintypes.DWORD
    return wlan


_wlanapi = _load_wlanapi()

_cache_lock = threading.Lock()
_cache: Optional[tuple[float, ConnectionInfo]] = None


# ---------------------------------------------------------------------------
# Consulta de baixo nível
# ---------------------------------------------------------------------------
def _query_interface_connection(handle, guid) -> Optional[ConnectionInfo]:
    """Consulta a conexão atual de uma interface. None se não conectada."""
    data_size = wintypes.DWORD(0)
    data_ptr = ctypes.c_void_p()
    ret = _wlanapi.WlanQueryInterface(
        handle,
        ctypes.byref(guid),
        WLAN_INTF_OPCODE_CURRENT_CONNECTION,
        None,
        ctypes.byref(data_size),
        ctypes.byref(data_ptr),
        None,
    )
    if ret != ERROR_SUCCESS or not data_ptr:
        # Erro comum: 0x00000057 quando a interface não está conectada
        return None

    try:
        attrs = ctypes.cast(
            data_ptr, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)
        ).contents
        if attrs.isState != WLAN_INTERFACE_STATE_CONNECTED:
            return None

        assoc = attrs.wlanAssociationAttributes
        ssid_len = min(int(assoc.dot11Ssid.uSSIDLength), DOT11_SSID_MAX_LENGTH)
        ssid_bytes = bytes(assoc.dot11Ssid.ucSSID[:ssid_len])
        ssid = ssid_bytes.decode("utf-8", "replace") if ssid_len else ""
        bssid = ":".join("%02x" % b for b in assoc.dot11Bssid)

        return ConnectionInfo(
            connected=True,
            ssid=ssid or None,
            bssid=bssid,
            wifi_present=True,
        )
    finally:
        _wlanapi.WlanFreeMemory(data_ptr)


def _query_connection() -> ConnectionInfo:
    """Consulta a primeira interface Wi-Fi conectada. Nunca levanta."""
    if _wlanapi is None:
        return ConnectionInfo(False, None, None, False)

    handle = wintypes.HANDLE()
    negotiated = wintypes.DWORD()
    ret = _wlanapi.WlanOpenHandle(
        WLAN_CLIENT_VERSION, None,
        ctypes.byref(negotiated), ctypes.byref(handle),
    )
    if ret != ERROR_SUCCESS:
        # Serviço WLAN não ativo (1062) ou outro erro — sem Wi-Fi utilizável
        logger.debug("WlanOpenHandle falhou (ret=%d)", ret)
        return ConnectionInfo(False, None, None, False)

    iface_list_ptr = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    try:
        ret = _wlanapi.WlanEnumInterfaces(
            handle, None, ctypes.byref(iface_list_ptr)
        )
        if ret != ERROR_SUCCESS or not iface_list_ptr:
            return ConnectionInfo(False, None, None, False)

        try:
            num = iface_list_ptr.contents.dwNumberOfItems
            wifi_present = num > 0
            # Ponteiro para o primeiro elemento do array flexível
            first = ctypes.cast(
                ctypes.addressof(iface_list_ptr.contents.InterfaceInfo),
                ctypes.POINTER(WLAN_INTERFACE_INFO),
            )
            for i in range(num):
                iface = first[i]
                info = _query_interface_connection(handle, iface.InterfaceGuid)
                if info is not None:
                    return info
            return ConnectionInfo(False, None, None, wifi_present)
        finally:
            _wlanapi.WlanFreeMemory(iface_list_ptr)
    finally:
        _wlanapi.WlanCloseHandle(handle, None)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def get_current_connection(use_cache: bool = True) -> ConnectionInfo:
    """Retorna a conexão Wi-Fi atual (com cache curto de ~3s).

    Args:
        use_cache: se ``False``, força uma consulta nova (útil ao "marcar
            a rede atual" no menu, onde queremos dado fresco).
    """
    global _cache
    if use_cache:
        with _cache_lock:
            if _cache is not None and (time.monotonic() - _cache[0]) < _CACHE_TTL_SECONDS:
                return _cache[1]

    try:
        info = _query_connection()
    except Exception:
        logger.debug("Falha ao consultar Wi-Fi", exc_info=True)
        info = ConnectionInfo(False, None, None, False)

    with _cache_lock:
        _cache = (time.monotonic(), info)
    return info


def _norm_bssid(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def is_on_trusted_network(state) -> bool:
    """Decide se a rede atual é confiável, conforme a política do ``state``.

    Regras:
      * Sem Wi-Fi conectado (cabo, Wi-Fi desligado, sem adaptador) →
        usa ``state.wired_is_trusted``.
      * Com Wi-Fi conectado → confere contra ``state.trusted_networks``.
        Se ``state.match_bssid`` e a rede salva tiver BSSID, exige que o
        BSSID também bata (anti evil-twin); senão, casa só pelo SSID.
    """
    info = get_current_connection()

    if not info.connected or not info.ssid:
        return bool(getattr(state, "wired_is_trusted", True))

    match_bssid = bool(getattr(state, "match_bssid", True))
    current_bssid = _norm_bssid(info.bssid)

    for net in getattr(state, "trusted_networks", []) or []:
        if not isinstance(net, dict):
            continue
        if net.get("ssid") != info.ssid:
            continue
        saved_bssid = _norm_bssid(net.get("bssid"))
        if match_bssid and saved_bssid:
            if saved_bssid == current_bssid:
                return True
            # SSID bate mas BSSID não — possível evil-twin: não confiar
            continue
        return True

    return False
