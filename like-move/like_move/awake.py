"""Mantém o Windows acordado com SetThreadExecutionState e a thread de monitoramento.

Nenhuma entrada de mouse/teclado é simulada: quando as condições do modo escolhido
valem, a thread pede ao Windows "tela e sistema ligados" (ES_CONTINUOUS |
ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED). O pedido pertence a esta thread e o
Windows o descarta quando o processo termina.
"""

import ctypes
import datetime as dt
import logging
import threading
import time
from typing import Callable, NamedTuple, Optional

from .config import CHECK_INTERVAL_SECONDS, JigglerState, TriggerMode
from .detector import (
    battery_percent, get_execution_state, get_idle_time_ms, get_system_times, is_on_ac_power, is_screen_locked,
    lock_workstation, running_process_names,
)
from . import timer, triggers
from .device_monitor import DeviceMonitor
from .wifi import is_on_trusted_network

logger = logging.getLogger(__name__)

ES_CONTINUOUS: int = 0x80000000
ES_SYSTEM_REQUIRED: int = 0x00000001
ES_DISPLAY_REQUIRED: int = 0x00000002

# Leituras seguidas fora da rede confiável antes de bloquear a tela: um soluço do Wi-Fi não pode bloquear.
LOCK_DEBOUNCE_TICKS: int = 5

# Pontos acima do mínimo em que a carga precisa voltar para o pedido ser retomado: a leitura em % oscila.
BATTERY_RESUME_MARGIN: int = 5

# Segundos antes do fim do prazo em que o usuário é avisado, para poder prorrogar.
DEADLINE_WARNING_SECONDS: int = 120

REASON_DISABLED = "desativado"
REASON_LOCKED = "tela bloqueada"
REASON_UNTRUSTED = "fora de rede confiável"
REASON_BATTERY = "na bateria"
REASON_LOW_BATTERY = "bateria baixa"
REASON_TIMED = "prazo"
REASON_SCHEDULED = "horário"
REASON_PROCESS = "programa em execução"
REASON_CPU = "CPU alta"
REASON_ALWAYS = "Sempre"
REASON_IDLE = "inatividade"
REASON_KVM = "KVM"
REASON_WAITING = "aguardando"

_HOLDING_REASONS = frozenset({REASON_TIMED, REASON_SCHEDULED, REASON_PROCESS, REASON_CPU, REASON_ALWAYS, REASON_IDLE, REASON_KVM})

# Gatilhos que acabam por conta própria: o fim deles é o "terminou" de "Bloquear a tela ao terminar".
_SELF_ENDING_REASONS = frozenset({REASON_TIMED, REASON_PROCESS, REASON_CPU})

_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
_kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
_kernel32.SetThreadExecutionState.restype = ctypes.c_uint


class Decision(NamedTuple):
    """Resultado de :func:`decide_keep_awake`: se o pedido deve estar ativo e por quê."""

    wanted: bool
    reason: str


def required_bits(display: bool) -> int:
    """Bits do pedido de energia: sempre o sistema, e a tela a menos que ela possa apagar."""
    return ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if display else ES_SYSTEM_REQUIRED


def set_keep_awake(on: bool, display: bool = True) -> None:
    """Liga/desliga o pedido de energia da thread atual; ``display=False`` deixa a tela apagar."""
    flags = ES_CONTINUOUS | required_bits(display) if on else ES_CONTINUOUS
    if _kernel32.SetThreadExecutionState(flags) == 0:
        raise OSError("SetThreadExecutionState falhou")


def decide_keep_awake(
    state: JigglerState,
    *,
    idle_seconds: float,
    device_disconnected: bool,
    trusted: bool,
    locked: bool,
    on_ac: bool = True,
    timed: bool = False,
    scheduled: bool = False,
    process_running: bool = False,
    cpu_busy: bool = False,
    battery_low: bool = False,
) -> Decision:
    """Decide se o pedido deve estar ativo agora e o motivo (puro, sem chamar o Windows).

    As travas (desativado, tela bloqueada, rede não confiável, bateria, bateria baixa) valem antes de qualquer modo,
    inclusive durante um prazo, um programa vigiado ou uma CPU ocupada.
    """
    if not state.enabled:
        return Decision(False, REASON_DISABLED)
    if locked:
        return Decision(False, REASON_LOCKED)
    # Gate de segurança: fora de rede confiável a tela bloqueia normalmente.
    if state.trusted_only and not trusted:
        return Decision(False, REASON_UNTRUSTED)
    if state.ac_only and not on_ac:
        return Decision(False, REASON_BATTERY)
    if battery_low:
        return Decision(False, REASON_LOW_BATTERY)
    if timed:
        return Decision(True, REASON_TIMED)
    if scheduled:
        return Decision(True, REASON_SCHEDULED)
    if process_running:
        return Decision(True, REASON_PROCESS)
    if cpu_busy:
        return Decision(True, REASON_CPU)
    mode = state.trigger_mode
    if mode == TriggerMode.ALWAYS:
        return Decision(True, REASON_ALWAYS)
    if mode in (TriggerMode.IDLE, TriggerMode.BOTH) and idle_seconds >= state.idle_threshold:
        return Decision(True, REASON_IDLE)
    if mode in (TriggerMode.KVM, TriggerMode.BOTH) and device_disconnected:
        return Decision(True, REASON_KVM)
    return Decision(False, REASON_WAITING)


def should_keep_awake(
    state: JigglerState,
    *,
    idle_seconds: float,
    device_disconnected: bool,
    trusted: bool,
    locked: bool,
    on_ac: bool = True,
    timed: bool = False,
    scheduled: bool = False,
    process_running: bool = False,
    cpu_busy: bool = False,
    battery_low: bool = False,
) -> bool:
    """Versão booleana de :func:`decide_keep_awake`."""
    return decide_keep_awake(
        state, idle_seconds=idle_seconds, device_disconnected=device_disconnected,
        trusted=trusted, locked=locked, on_ac=on_ac, timed=timed,
        scheduled=scheduled, process_running=process_running, cpu_busy=cpu_busy, battery_low=battery_low,
    ).wanted


def is_battery_low(percent: Optional[int], floor: int, *, was_low: bool) -> bool:
    """Carga abaixo do mínimo (``floor``; 0 = desligado)? Depois de baixa, só volta a normal em ``floor`` + ``BATTERY_RESUME_MARGIN``.

    Carga desconhecida (``None``) não conta como baixa.
    """
    if not floor or percent is None:
        return False
    return percent < (floor + BATTERY_RESUME_MARGIN if was_low else floor)


def status_text(reason: str, state: JigglerState, *, idle_seconds: float) -> str:
    """Texto da linha de status do menu para o motivo da decisão atual."""
    if reason in _HOLDING_REASONS:
        return f"Acordado agora: {reason}"
    if reason == REASON_WAITING:
        if state.trigger_mode == TriggerMode.KVM:
            return "Aguardando: dispositivo monitorado conectado"
        return f"Aguardando: faltam {max(0, int(state.idle_threshold - idle_seconds))}s"
    return f"Parado: {reason}"


def should_lock_on_leave(state: JigglerState, *, was_trusted: bool, trusted: bool, locked: bool) -> bool:
    """True quando o PC acabou de sair de uma rede confiável e o usuário pediu para bloquear a tela."""
    return bool(
        state.lock_on_untrusted and was_trusted and not trusted and not locked and state.trusted_networks
    )


def should_lock_when_done(state: JigglerState, *, ending_reason: Optional[str], reason: str, locked: bool) -> bool:
    """True quando um gatilho que acaba sozinho (prazo, programa ou CPU) terminou e o pedido ficou solto de verdade.

    ``ending_reason`` é o motivo que mantinha o PC acordado até então. Não vale se a tela já está bloqueada nem
    quando o pedido foi solto por uma trava (desativado, tela bloqueada, rede, bateria) ou segue preso por outro motivo.
    """
    return bool(
        state.lock_when_done and ending_reason in _SELF_ENDING_REASONS and reason == REASON_WAITING and not locked
    )


def request_lost(holding: bool, execution_state: Optional[int], display: bool = True) -> bool:
    """True se o app acredita manter o pedido mas o sistema não mostra os bits pedidos.

    O estado do sistema soma os pedidos de todos os programas: com o nosso ativo os bits de
    ``required_bits(display)`` têm de estar ligados. Estado ilegível (``None``) não é prova de perda.
    """
    if not holding or execution_state is None:
        return False
    wanted_bits = required_bits(display)
    return execution_state & wanted_bits != wanted_bits


class MonitorThread(threading.Thread):
    """Thread daemon que liga o pedido quando o modo pede e o libera quando não.

    ``status`` guarda a linha de status do menu; ``notifier`` (opcional) recebe os avisos de mudança.
    """

    def __init__(self, state: JigglerState) -> None:
        super().__init__(daemon=True, name="like-move-monitor")
        self._state = state
        self._stop_event = threading.Event()
        self._device_monitor: Optional[DeviceMonitor] = None
        self._awake = False
        self._held_display = True
        self._was_trusted = False
        self._untrusted_ticks = 0
        self._loss_reported = False
        self._state_read_failed = False
        self._ac_read_failed = False
        self._battery_read_failed = False
        self._battery_is_low = False
        self._ending_reason: Optional[str] = None
        self._done_ticks = 0
        self._first_tick = True
        self._warned_deadline = 0.0
        self._cpu_gate = triggers.CpuLoadGate()
        self._previous_times = None
        self._cpu_threshold_seen = 0
        self._process_read_failed = False
        self._cpu_read_failed = False
        self.status = ""
        self.notifier: Optional[Callable[[str], None]] = None

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

    def _notify(self, message: str) -> None:
        if not self.notifier:
            return
        try:
            self.notifier(message)
        except Exception:
            logger.warning("Aviso ao usuário falhou", exc_info=True)

    def _timer_active(self, now: float) -> bool:
        """Prazo vigente? Um prazo vencido é apagado e salvo, e o usuário é avisado."""
        until = self._state.awake_until
        if not until:
            return False
        if now < until:
            if until - now <= DEADLINE_WARNING_SECONDS and self._warned_deadline != until:
                self._warned_deadline = until
                logger.info("Prazo para manter acordado termina em %s: avisando", timer.remaining_text(until, now))
                self._notify(f"O prazo termina em {timer.remaining_text(until, now)}: escolha outro no menu para prorrogar")
            return True
        if self._state.awake_until == until:
            self._state.awake_until = 0.0
            self._state.save()
        logger.info("Prazo para manter acordado terminou")
        if not self._first_tick:
            self._notify("Prazo terminou: voltou ao modo escolhido")
        return False

    def _scheduled(self, now: float) -> bool:
        """Estamos dentro do horário de trabalho ligado? Desligado, nem olha o relógio."""
        if not self._state.work_hours.get("enabled"):
            return False
        return timer.in_work_hours(self._state.work_hours, dt.datetime.fromtimestamp(now))

    def _read_on_ac(self) -> bool:
        """Está na tomada? Falha de leitura é registrada uma vez e conta como tomada."""
        try:
            on_ac = is_on_ac_power()
        except OSError:
            if not self._ac_read_failed:
                logger.warning("Não consegui ler a fonte de energia; contando como na tomada", exc_info=True)
            self._ac_read_failed = True
            return True
        self._ac_read_failed = False
        return on_ac

    def _battery_low(self, on_ac: bool) -> bool:
        """A carga está abaixo do mínimo escolhido? Só vale na bateria; falha de leitura é registrada uma vez e conta como não."""
        floor = self._state.battery_floor
        if not floor or on_ac:
            self._battery_is_low = False
            return False
        try:
            percent = battery_percent()
        except OSError:
            if not self._battery_read_failed:
                logger.warning("Não consegui ler a carga da bateria; contando como não baixa", exc_info=True)
            self._battery_read_failed = True
            self._battery_is_low = False
            return False
        self._battery_read_failed = False
        was_low, self._battery_is_low = self._battery_is_low, is_battery_low(percent, floor, was_low=self._battery_is_low)
        if self._battery_is_low != was_low:
            logger.info("Bateria em %s%% (mínimo %d%%): %s", percent, floor, "soltando o pedido" if self._battery_is_low else "retomando")
        return self._battery_is_low

    def _process_running(self) -> bool:
        """Algum programa vigiado roda? Falha de leitura é registrada uma vez e conta como não."""
        if not self._state.watched_processes:
            return False
        try:
            running = running_process_names()
        except OSError:
            if not self._process_read_failed:
                logger.warning("Não consegui listar os programas em execução", exc_info=True)
            self._process_read_failed = True
            return False
        self._process_read_failed = False
        return triggers.any_running(self._state.watched_processes, running)

    def _cpu_busy(self) -> bool:
        """A CPU está ocupada (acima do limite, com histerese)? Opção desligada zera o histórico."""
        threshold = self._state.cpu_threshold
        if threshold != self._cpu_threshold_seen:
            self._cpu_threshold_seen = threshold
            self._cpu_gate.reset()
        if not threshold:
            self._cpu_gate.reset()
            self._previous_times = None
            return False
        try:
            times = get_system_times()
        except OSError:
            if not self._cpu_read_failed:
                logger.warning("Não consegui ler o uso da CPU", exc_info=True)
            self._cpu_read_failed = True
            return self._cpu_gate.busy
        self._cpu_read_failed = False
        previous, self._previous_times = self._previous_times, times
        percent = triggers.cpu_percent(previous, times) if previous else None
        return self._cpu_gate.update(percent, threshold)

    def _lock_if_left_trusted(self, on_trusted: bool, locked: bool) -> None:
        """Bloqueia a tela quando a rede confiável some por ``LOCK_DEBOUNCE_TICKS`` leituras seguidas."""
        if not self._state.lock_on_untrusted:
            self._was_trusted = False
            self._untrusted_ticks = 0
            return
        if on_trusted:
            self._was_trusted = True
            self._untrusted_ticks = 0
            return
        if not self._was_trusted:
            return
        self._untrusted_ticks += 1
        if self._untrusted_ticks < LOCK_DEBOUNCE_TICKS:
            return
        was_trusted, self._was_trusted, self._untrusted_ticks = self._was_trusted, False, 0
        if should_lock_on_leave(self._state, was_trusted=was_trusted, trusted=False, locked=locked):
            logger.info("Saiu da rede confiável: bloqueando a tela")
            lock_workstation()

    def _lock_when_done(self, reason: str, locked: bool) -> None:
        """Bloqueia a tela quando um gatilho que acaba sozinho termina e o pedido segue solto por ``LOCK_DEBOUNCE_TICKS`` leituras."""
        if self._state.lock_when_done and reason in _SELF_ENDING_REASONS:
            self._ending_reason, self._done_ticks = reason, 0
            return
        ending = self._ending_reason
        if not should_lock_when_done(self._state, ending_reason=ending, reason=reason, locked=locked):
            self._ending_reason, self._done_ticks = None, 0
            return
        self._done_ticks += 1
        if self._done_ticks < LOCK_DEBOUNCE_TICKS:
            return
        self._ending_reason, self._done_ticks = None, 0
        logger.info("Terminou (%s): bloqueando a tela", ending)
        lock_workstation()

    def _verify_request(self) -> None:
        """Confere no sistema se o pedido continua valendo e o reafirma uma vez se foi perdido."""
        try:
            execution_state = get_execution_state()
        except OSError:
            if not self._state_read_failed:
                logger.warning("Não consegui ler o estado de energia do sistema", exc_info=True)
            self._state_read_failed = True
            return
        self._state_read_failed = False
        if not request_lost(self._awake, execution_state, self._held_display):
            self._loss_reported = False
            return
        if self._loss_reported:
            return
        self._loss_reported = True
        logger.warning("Pedido de energia perdido (estado do sistema 0x%X); reafirmando", execution_state)
        set_keep_awake(True, self._held_display)

    def _update(self) -> None:
        state = self._state
        now = time.time()
        timed = self._timer_active(now)
        idle_seconds = get_idle_time_ms() / 1000.0
        locked = is_screen_locked()
        on_trusted = is_on_trusted_network(state) if (state.trusted_only or state.lock_on_untrusted) else False
        on_ac = self._read_on_ac() if (state.ac_only or state.battery_floor) else True
        decision = decide_keep_awake(
            state,
            idle_seconds=idle_seconds,
            device_disconnected=bool(self._device_monitor and self._device_monitor.device_disconnected),
            trusted=on_trusted,
            locked=locked,
            on_ac=on_ac,
            timed=timed,
            scheduled=self._scheduled(now),
            process_running=self._process_running(),
            cpu_busy=self._cpu_busy(),
            battery_low=self._battery_low(on_ac),
        )
        self.status = status_text(decision.reason, state, idle_seconds=idle_seconds)
        wanted = decision.wanted
        display = not state.display_may_sleep
        if wanted != self._awake:
            set_keep_awake(wanted, display)
            self._awake = wanted
            self._held_display = display
            self._loss_reported = False
            logger.info("Manter acordado: %s (modo=%s)", "sim" if wanted else "não", state.trigger_mode.value)
            if state.notify_transitions:
                self._notify(self.status)
        elif self._awake and display != self._held_display:
            set_keep_awake(True, display)
            self._held_display = display
            self._loss_reported = False
            logger.info("Pedido de energia refeito: tela %s", "ligada" if display else "pode apagar")
        elif self._awake:
            self._verify_request()
        self._lock_if_left_trusted(on_trusted, locked)
        self._lock_when_done(decision.reason, locked)
        self._first_tick = False
