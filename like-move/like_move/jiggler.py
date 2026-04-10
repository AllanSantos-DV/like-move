"""Lógica de mouse jiggle e thread de monitoramento."""

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from typing import Optional

from .config import CHECK_INTERVAL_SECONDS, JIGGLE_PIXELS, JigglerState, TriggerMode
from .detector import get_idle_time_ms, is_screen_locked
from .device_monitor import DeviceBaseline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes Win32 para SendInput
# ---------------------------------------------------------------------------
INPUT_MOUSE: int = 0
MOUSEEVENTF_MOVE: int = 0x0001

user32 = ctypes.windll.user32  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Estruturas Win32 para SendInput
# ---------------------------------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    """Estrutura MOUSEINPUT para eventos de mouse sintéticos."""

    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    """Union interna do INPUT — apenas mouse é usado."""

    _fields_ = [
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    """Estrutura INPUT para SendInput."""

    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", _INPUT_UNION),
    ]


# Protótipo: UINT SendInput(UINT cInputs, LPINPUT pInputs, int cbSize)
user32.SendInput.argtypes = [
    ctypes.c_uint,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
]
user32.SendInput.restype = ctypes.c_uint


# ---------------------------------------------------------------------------
# Funções de jiggle
# ---------------------------------------------------------------------------
def _make_mouse_input(dx: int, dy: int) -> INPUT:
    """Cria uma estrutura INPUT para movimento relativo do mouse."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = None  # type: ignore[assignment]
    return inp


def jiggle_mouse(pixels: int = JIGGLE_PIXELS) -> bool:
    """Faz jiggle mínimo do mouse: move +pixels e depois -pixels.

    Usa SendInput com MOUSEEVENTF_MOVE (movimento relativo).
    O cursor volta à posição original — imperceptível para o usuário.

    Returns:
        True se ambos os movimentos foram injetados com sucesso.
    """
    # Movimento de ida (+pixels no eixo X)
    inp_right = _make_mouse_input(pixels, 0)
    result1 = user32.SendInput(1, ctypes.byref(inp_right), ctypes.sizeof(INPUT))

    # Movimento de volta (-pixels no eixo X)
    inp_left = _make_mouse_input(-pixels, 0)
    result2 = user32.SendInput(1, ctypes.byref(inp_left), ctypes.sizeof(INPUT))

    success = result1 == 1 and result2 == 1
    if not success:
        logger.warning("SendInput falhou: ida=%d, volta=%d", result1, result2)

    return success


# ---------------------------------------------------------------------------
# Thread de monitoramento
# ---------------------------------------------------------------------------
class MonitorThread(threading.Thread):
    """Thread daemon que monitora inatividade e faz jiggle quando necessário."""

    def __init__(self, state: JigglerState) -> None:
        super().__init__(daemon=True, name="like-move-monitor")
        self._state = state
        self._stop_event = threading.Event()
        self._last_jiggle_time: float = 0.0
        self._device_baseline: Optional[DeviceBaseline] = None

    def stop(self) -> None:
        """Sinaliza a thread para parar graciosamente."""
        self._stop_event.set()

    def reset_device_baseline(self) -> None:
        """Reset device baseline so it recaptures on next KVM check."""
        self._device_baseline = None

    def run(self) -> None:
        """Loop principal de monitoramento."""
        logger.info("Monitor iniciado (threshold=%ds)", self._state.idle_threshold)

        while not self._stop_event.is_set():
            try:
                self._check_and_jiggle()
            except Exception:
                logger.error("Erro no loop de monitoramento", exc_info=True)

            self._stop_event.wait(CHECK_INTERVAL_SECONDS)

        logger.info("Monitor encerrado")

    def _check_and_jiggle(self) -> None:
        """Verifica condições e faz jiggle se necessário."""
        if not self._state.enabled:
            return

        # Não fazer jiggle se a tela está bloqueada (seria inútil)
        if is_screen_locked():
            return

        mode = self._state.trigger_mode
        should_jiggle = False

        # IDLE or BOTH: check idle threshold
        if mode in (TriggerMode.IDLE, TriggerMode.BOTH):
            idle_ms = get_idle_time_ms()
            idle_seconds = idle_ms / 1000.0
            if idle_seconds >= self._state.idle_threshold:
                should_jiggle = True

        # KVM or BOTH: check device disconnection
        if mode in (TriggerMode.KVM, TriggerMode.BOTH):
            if self._device_baseline is None:
                self._device_baseline = DeviceBaseline()
            if self._device_baseline.has_disconnection(self._state.monitor_devices):
                should_jiggle = True
            else:
                # Counts restored — refresh baseline for next comparison
                self._device_baseline.refresh()

        # ALWAYS: jiggle continuously
        if mode == TriggerMode.ALWAYS:
            should_jiggle = True

        if not should_jiggle:
            return

        # Respect jiggle interval
        now = time.monotonic()
        elapsed = now - self._last_jiggle_time

        if elapsed >= self._state.jiggle_interval:
            if jiggle_mouse():
                logger.debug("Jiggle executado (mode=%s)", mode.value)
            self._last_jiggle_time = now
