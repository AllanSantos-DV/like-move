"""Detecção de inatividade e tela bloqueada via Win32 API (ctypes)."""

import ctypes
import ctypes.wintypes
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 DLLs
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


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
def get_idle_time_ms() -> int:
    """Retorna o tempo de inatividade em milissegundos.

    Usa GetLastInputInfo para obter o tick do último input e
    GetTickCount64 para o tick atual. A diferença é o tempo idle.
    """
    lii = LASTINPUTINFO()
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        logger.warning("GetLastInputInfo falhou")
        return 0

    current_tick: int = kernel32.GetTickCount64()

    # dwTime é DWORD (32-bit), current_tick é 64-bit.
    # Mascarar current_tick para 32 bits para subtração correta
    # quando dwTime ainda não sofreu overflow.
    idle_ms = (current_tick & 0xFFFFFFFF) - lii.dwTime
    if idle_ms < 0:
        # Overflow do DWORD — tratar como idle zero
        idle_ms = 0

    return idle_ms


def is_screen_locked() -> bool:
    """Verifica se a tela está bloqueada (Secure Desktop ativo).

    Usa OpenInputDesktopW — retorna NULL quando a tela está bloqueada
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
