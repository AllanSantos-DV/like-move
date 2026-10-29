"""Mantém o Windows acordado com SetThreadExecutionState e a thread de monitoramento.

Nenhuma entrada de mouse/teclado é simulada: quando as condições do modo escolhido
valem, a thread pede ao Windows "tela e sistema ligados" (ES_CONTINUOUS |
ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED). O pedido pertence a esta thread e o
Windows o descarta quando o processo termina.
"""

import ctypes
import logging
import threading
from typing import Optional

from .config import CHECK_INTERVAL_SECONDS, JigglerState, TriggerMode
from .detector import get_idle_time_ms, is_screen_locked
from .device_monitor import DeviceMonitor
from .wifi import is_on_trusted_network

logger = logging.getLogger(__name__)

ES_CONTINUOUS: int = 0x80000000
ES_SYSTEM_REQUIRED: int = 0x00000001
ES_DISPLAY_REQUIRED: int = 0x00000002

_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
_kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
_kernel32.SetThreadExecutionState.restype = ctypes.c_uint


def set_keep_awake(on: bool) -> None:
    """Liga/desliga o pedido de tela e sistema ligados para a thread atual."""
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else ES_CONTINUOUS
    if _kernel32.SetThreadExecutionState(flags) == 0:
        raise OSError("SetThreadExecutionState falhou")


def should_keep_awake(
    state: JigglerState,
    *,
    idle_seconds: float,
    device_disconnected: bool,
    trusted: bool,
    locked: bool,
) -> bool:
    """Decide se o pedido deve estar ativo agora (puro, sem chamar o Windows)."""
    if not state.enabled or locked:
        return False
    # Gate de segurança: fora de rede confiável a tela bloqueia normalmente.
    if state.trusted_only and not trusted:
        return False
    mode = state.trigger_mode
    if mode == TriggerMode.ALWAYS:
        return True
    idle_hit = mode in (TriggerMode.IDLE, TriggerMode.BOTH) and idle_seconds >= state.idle_threshold
    kvm_hit = mode in (TriggerMode.KVM, TriggerMode.BOTH) and device_disconnected
    return idle_hit or kvm_hit


class MonitorThread(threading.Thread):
    """Thread daemon que liga o pedido quando o modo pede e o libera quando não."""

    def __init__(self, state: JigglerState) -> None:
        super().__init__(daemon=True, name="like-move-monitor")
        self._state = state
        self._stop_event = threading.Event()
        self._device_monitor: Optional[DeviceMonitor] = None
        self._awake = False

    def stop(self) -> None:
        """Sinaliza a thread para parar graciosamente."""
        self._stop_event.set()

    def set_device_monitor(self, monitor: Optional[DeviceMonitor]) -> None:
        """Set or clear the device monitor reference."""
        self._device_monitor = monitor

    def run(self) -> None:
        """Loop principal: o pedido é ligado e desligado sempre nesta mesma thread."""
        logger.info("Monitor iniciado (threshold=%ds)", self._state.idle_threshold)
        try:
            while not self._stop_event.is_set():
                try:
                    self._update()
                except Exception:
                    logger.error("Erro no loop de monitoramento", exc_info=True)
                self._stop_event.wait(CHECK_INTERVAL_SECONDS)
        finally:
            set_keep_awake(False)
            logger.info("Monitor encerrado")

    def _update(self) -> None:
        state = self._state
        wanted = should_keep_awake(
            state,
            idle_seconds=get_idle_time_ms() / 1000.0,
            device_disconnected=bool(self._device_monitor and self._device_monitor.device_disconnected),
            trusted=state.trusted_only and is_on_trusted_network(state),
            locked=is_screen_locked(),
        )
        if wanted != self._awake:
            set_keep_awake(wanted)
            self._awake = wanted
            logger.info("Manter acordado: %s (modo=%s)", "sim" if wanted else "não", state.trigger_mode.value)
