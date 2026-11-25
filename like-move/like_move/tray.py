"""System tray icon com pystray para controle do like-move."""

import datetime as dt
import logging
import os
from typing import Any, Optional

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem
from pystray._util import win32 as _pystray_win32
import threading


from .config import JigglerState, TriggerMode
from .device_monitor import DeviceMonitor
from .awake import MonitorThread
from .wifi import get_current_connection
from . import diagnose, timer, triggers, updater
from .detector import visible_window_process_names

logger = logging.getLogger(__name__)

# Thresholds disponíveis no menu (segundos)
THRESHOLD_OPTIONS: list[int] = [15, 30, 60, 120, 300]

# Prazos do menu "Manter acordado por…": minutos e horários do relógio
TIMER_MINUTES: list[tuple[int, str]] = [(30, "30 min"), (60, "1 hora"), (120, "2 horas"), (240, "4 horas")]
TIMER_CLOCK_TIMES: list[tuple[int, int]] = [(12, 0), (18, 0), (22, 0)]

# Limite de CPU do menu "CPU ocupada": porcentagem (0 = desligado) e rótulo
CPU_OPTIONS: list[tuple[int, str]] = [(0, "Desligado"), (25, "Acima de 25%"), (50, "Acima de 50%"), (75, "Acima de 75%")]

# Limite do menu "Rede ocupada": KB/s (0 = desligado) e rótulo
NETWORK_OPTIONS: list[tuple[int, str]] = [
    (0, "Desligado"), (100, "Acima de 100 KB/s"), (500, "Acima de 500 KB/s"), (2048, "Acima de 2 MB/s"),
]

# Horários prontos do submenu "Horário de trabalho": rótulo, dias (0 = segunda), início e fim
WORK_HOURS_PRESETS: list[tuple[str, list[int], str, str]] = [
    ("Seg–Sex 09:00–18:00", [0, 1, 2, 3, 4], "09:00", "18:00"),
    ("Seg–Sex 08:00–20:00", [0, 1, 2, 3, 4], "08:00", "20:00"),
]

# Carga mínima do menu "Bateria mínima": porcentagem (0 = desligado) e rótulo
BATTERY_OPTIONS: list[tuple[int, str]] = [(0, "Desligado"), (10, "Abaixo de 10%"), (20, "Abaixo de 20%"), (30, "Abaixo de 30%")]

# Quantos programas com janela aberta o submenu "Vigiar um programa" lista
MAX_CANDIDATE_PROGRAMS: int = 30

# Programas do próprio Windows que têm janela mas ninguém quer vigiar
SHELL_PROGRAMS: frozenset[str] = frozenset({
    "applicationframehost.exe", "textinputhost.exe", "systemsettings.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "lockapp.exe",
})

# Mapping: TriggerMode → display label
_MODE_LABELS: dict[TriggerMode, str] = {
    TriggerMode.IDLE: "Inatividade",
    TriggerMode.KVM: "KVM",
    TriggerMode.BOTH: "Ambos",
    TriggerMode.ALWAYS: "Sempre",
}

# Mapping: device key → display label
_DEVICE_LABELS: dict[str, str] = {
    "monitor": "Monitor",
    "mouse": "Mouse",
    "keyboard": "Teclado",
}


def create_icon_image(enabled: bool = True) -> Image.Image:
    """Gera imagem 64x64 para o ícone do tray.

    Verde quando ativo, cinza quando desativado.
    Desenha um 'M' estilizado (mouse) no centro.
    """
    size = 64
    bg_color = "#2ecc71" if enabled else "#95a5a6"
    fg_color = "#ffffff"

    image = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(image)

    # Desenha um cursor/seta estilizado
    # Triângulo apontando para cima-direita (ícone de cursor)
    arrow_points = [
        (16, 12),   # topo
        (16, 52),   # base esquerda
        (28, 40),   # junção
        (36, 52),   # ponta inferior direita
        (42, 46),   # canto
        (34, 34),   # junção
        (48, 30),   # ponta direita
    ]
    draw.polygon(arrow_points, fill=fg_color)

    return image


def _now() -> dt.datetime:
    return dt.datetime.now()


def _format_threshold(seconds: int) -> str:
    """Formata threshold para exibição no menu."""
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}min"


class TrayApp:
    """Aplicação de system tray para controle do like-move."""

    def __init__(self) -> None:
        self._state = JigglerState()
        self._monitor: Optional[MonitorThread] = None
        self._device_monitor: Optional[DeviceMonitor] = None
        self._icon: Optional[Icon] = None
        self._pending_update: Optional["updater.UpdateInfo"] = None
        self._open_file = os.startfile  # type: ignore[attr-defined]

    def _on_toggle(self, icon: Icon, item: MenuItem) -> None:
        """Alterna entre ativado/desativado."""
        self._state.enabled = not self._state.enabled
        status = "ativado" if self._state.enabled else "desativado"
        logger.info("like-move %s", status)

        # Atualiza ícone para refletir estado
        if self._icon:
            self._icon.icon = create_icon_image(self._state.enabled)
        self._state.save()

    def _status_text(self, item: MenuItem) -> str:
        """Linha de status (dinâmica): o que o monitor decidiu no último ciclo."""
        monitor = self._monitor
        return (monitor.status if monitor and monitor.status else "like-move")

    def _start_timer(self, deadline: float) -> None:
        """Grava o prazo, liga o like-move (o usuário pediu) e avisa até quando."""
        self._state.awake_until = deadline
        self._state.enabled = True
        self._state.save()
        until = dt.datetime.fromtimestamp(deadline).strftime("%H:%M")
        logger.info("Prazo para manter acordado até %s", until)
        if self._icon:
            self._icon.icon = create_icon_image(True)
            self._icon.notify(f"Prazo definido até {until}.", "like-move")
            self._icon.update_menu()

    def _on_set_timer_minutes(self, minutes: int) -> Any:
        """Retorna callback que mantém acordado por ``minutes`` minutos."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._start_timer(timer.deadline_after(minutes, _now()))
        return handler

    def _on_set_timer_until(self, hour: int, minute: int) -> Any:
        """Retorna callback que mantém acordado até a próxima ocorrência de ``hour:minute``."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._start_timer(timer.deadline_until(hour, minute, _now()))
        return handler

    def _on_cancel_timer(self, icon: Icon, item: MenuItem) -> None:
        """Cancela o prazo: volta a valer só o modo escolhido."""
        self._state.awake_until = 0.0
        self._state.save()
        logger.info("Prazo para manter acordado cancelado")
        if self._icon:
            self._icon.update_menu()

    def _is_timer_active(self, item: MenuItem) -> bool:
        return timer.is_active(self._state.awake_until, _now().timestamp())

    def _timer_header_text(self, item: MenuItem) -> str:
        left = timer.remaining_text(self._state.awake_until, _now().timestamp())
        return f"Prazo: faltam {left}"

    def _toggle_option(self, field: str, label: str) -> None:
        """Inverte uma opção booleana do estado, salva e atualiza o menu."""
        value = not getattr(self._state, field)
        setattr(self._state, field, value)
        self._state.save()
        logger.info("%s: %s", label, "ativado" if value else "desativado")
        if self._icon:
            self._icon.update_menu()

    def _on_toggle_ac_only(self, icon: Icon, item: MenuItem) -> None:
        self._toggle_option("ac_only", "Só na tomada")

    def _on_toggle_display_may_sleep(self, icon: Icon, item: MenuItem) -> None:
        self._toggle_option("display_may_sleep", "Tela pode apagar")

    def _on_toggle_lock_on_untrusted(self, icon: Icon, item: MenuItem) -> None:
        self._toggle_option("lock_on_untrusted", "Bloquear a tela ao sair da rede")

    def _on_toggle_lock_when_done(self, icon: Icon, item: MenuItem) -> None:
        self._toggle_option("lock_when_done", "Bloquear a tela ao terminar")

    def _on_toggle_notify_transitions(self, icon: Icon, item: MenuItem) -> None:
        self._toggle_option("notify_transitions", "Avisar nas mudanças")

    def _on_diagnose(self, icon: Icon, item: MenuItem) -> None:
        """Roda o diagnóstico de bloqueio (somente leitura) em segundo plano e abre o relatório."""
        def worker() -> None:
            try:
                path = diagnose.run()
                logger.info("Diagnóstico de bloqueio gravado em %s", path)
                self._open_file(path)
            except Exception as exc:
                logger.error("Diagnóstico de bloqueio falhou", exc_info=True)
                if self._icon:
                    self._icon.notify(f"Diagnóstico falhou: {exc}", "like-move")

        threading.Thread(target=worker, daemon=True, name="like-move-diagnose").start()

    def _watched_header_text(self, item: MenuItem) -> str:
        return "Clique para deixar de vigiar:" if self._state.watched_processes else "Nenhum programa vigiado"

    def _watched_menu_items(self) -> list:
        """Itens do submenu "Programas vigiados": cada programa vigiado (clique remove) e como adicionar outro."""
        items: list = [MenuItem(self._watched_header_text, None, enabled=False)]
        for name in self._state.watched_processes:
            items.append(MenuItem(name, self._on_unwatch(name), checked=lambda item: True))
        items.append(Menu.SEPARATOR)
        items.append(MenuItem("Vigiar um programa", Menu(self._candidate_menu_items)))
        items.append(
            MenuItem("Parar de vigiar todos", self._on_clear_watched, visible=lambda item: bool(self._state.watched_processes))
        )
        return items

    def _candidate_menu_items(self) -> list:
        """Programas com janela aberta que ainda não são vigiados."""
        try:
            names = visible_window_process_names()
        except OSError:
            logger.error("Não consegui listar os programas com janela aberta", exc_info=True)
            return [MenuItem("Não consegui listar os programas", None, enabled=False)]
        watched = {triggers.normalize_process_name(n) for n in self._state.watched_processes}
        candidates = [n for n in names if n not in watched and n not in SHELL_PROGRAMS]
        if not candidates:
            return [MenuItem("Nenhum programa com janela aberta", None, enabled=False)]
        items = [MenuItem(n, self._on_watch(n)) for n in candidates[:MAX_CANDIDATE_PROGRAMS]]
        if len(candidates) > MAX_CANDIDATE_PROGRAMS:
            items.append(MenuItem(f"… e mais {len(candidates) - MAX_CANDIDATE_PROGRAMS}", None, enabled=False))
        return items

    def _on_watch(self, name: str) -> Any:
        """Retorna callback que passa a vigiar o programa ``name``."""
        def handler(icon: Icon, item: MenuItem) -> None:
            normalized = triggers.normalize_process_name(name)
            if normalized not in self._state.watched_processes:
                self._state.watched_processes = [*self._state.watched_processes, normalized]
            self._state.save()
            logger.info("Programa vigiado: %s", name)
            if self._icon:
                self._icon.update_menu()
        return handler

    def _on_unwatch(self, name: str) -> Any:
        """Retorna callback que deixa de vigiar o programa ``name``."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.watched_processes = [n for n in self._state.watched_processes if n != name]
            self._state.save()
            logger.info("Programa deixou de ser vigiado: %s", name)
            if self._icon:
                self._icon.update_menu()
        return handler

    def _on_clear_watched(self, icon: Icon, item: MenuItem) -> None:
        """Deixa de vigiar todos os programas."""
        self._state.watched_processes = []
        self._state.save()
        logger.info("Nenhum programa vigiado")
        if self._icon:
            self._icon.update_menu()

    def _on_set_cpu_threshold(self, percent: int) -> Any:
        """Retorna callback que define o limite de CPU (0 desliga)."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.cpu_threshold = percent
            self._state.save()
            logger.info("Limite de CPU: %s", f"{percent}%" if percent else "desligado")
        return handler

    def _is_cpu_threshold_checked(self, percent: int) -> Any:
        def check(item: MenuItem) -> bool:
            return self._state.cpu_threshold == percent
        return check

    def _on_set_network_threshold(self, kbps: int) -> Any:
        """Retorna callback que define o limite de tráfego de rede em KB/s (0 desliga)."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.network_threshold_kbps = kbps
            self._state.save()
            logger.info("Limite de rede: %s", f"{kbps} KB/s" if kbps else "desligado")
        return handler

    def _is_network_threshold_checked(self, kbps: int) -> Any:
        def check(item: MenuItem) -> bool:
            return self._state.network_threshold_kbps == kbps
        return check

    def _on_toggle_work_hours(self, icon: Icon, item: MenuItem) -> None:
        """Liga/desliga o horário de trabalho, mantendo os dias e as horas escolhidos."""
        hours = self._state.work_hours
        self._state.work_hours = {**hours, "enabled": not hours["enabled"]}
        self._state.save()
        logger.info("Horário de trabalho: %s", "ligado" if self._state.work_hours["enabled"] else "desligado")
        if self._icon:
            self._icon.update_menu()

    def _on_set_work_hours(self, days: list[int], start: str, end: str) -> Any:
        """Retorna callback que escolhe os dias e as horas do horário de trabalho (não liga nem desliga)."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.work_hours = {**self._state.work_hours, "days": list(days), "start": start, "end": end}
            self._state.save()
            logger.info("Horário de trabalho: dias %s, %s às %s", days, start, end)
        return handler

    def _is_work_hours_checked(self, days: list[int], start: str, end: str) -> Any:
        def check(item: MenuItem) -> bool:
            hours = self._state.work_hours
            return (hours["days"], hours["start"], hours["end"]) == (days, start, end)
        return check

    def _on_set_battery_floor(self, percent: int) -> Any:
        """Retorna callback que define a carga mínima da bateria (0 desliga)."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.battery_floor = percent
            self._state.save()
            logger.info("Bateria mínima: %s", f"{percent}%" if percent else "desligado")
        return handler

    def _is_battery_floor_checked(self, percent: int) -> Any:
        def check(item: MenuItem) -> bool:
            return self._state.battery_floor == percent
        return check

    def _on_set_threshold(self, seconds: int) -> Any:
        """Retorna callback para definir threshold específico."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.idle_threshold = seconds
            self._state.save()
            logger.info("Threshold alterado para %ds", seconds)
        return handler

    def _is_threshold_checked(self, seconds: int) -> Any:
        """Retorna callback para verificar se threshold está selecionado."""
        def check(item: MenuItem) -> bool:
            return self._state.idle_threshold == seconds
        return check

    def _on_set_mode(self, mode: TriggerMode) -> Any:
        """Retorna callback para definir trigger mode."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.trigger_mode = mode
            self._state.save()
            self._ensure_device_monitor()
            logger.info("Trigger mode alterado para %s", mode.value)
        return handler

    def _is_mode_checked(self, mode: TriggerMode) -> Any:
        """Retorna callback para verificar se mode está selecionado."""
        def check(item: MenuItem) -> bool:
            return self._state.trigger_mode == mode
        return check

    def _on_toggle_device(self, device: str) -> Any:
        """Retorna callback para toggle de dispositivo monitorado."""
        def handler(icon: Icon, item: MenuItem) -> None:
            if device in self._state.monitor_devices:
                # Don't allow removing the last device
                if len(self._state.monitor_devices) > 1:
                    self._state.monitor_devices.discard(device)
                    logger.info("Dispositivo removido: %s", device)
                else:
                    logger.info("Pelo menos um dispositivo deve estar ativo")
                    return
            else:
                self._state.monitor_devices.add(device)
                logger.info("Dispositivo adicionado: %s", device)
            self._state.save()
            if self._device_monitor:
                self._device_monitor.update_monitor_devices(
                    self._state.monitor_devices
                )
        return handler

    def _is_device_checked(self, device: str) -> Any:
        """Retorna callback para verificar se dispositivo está monitorado."""
        def check(item: MenuItem) -> bool:
            return device in self._state.monitor_devices
        return check

    def _is_startup_checked(self, item: MenuItem) -> bool:
        """Verifica se o like-move está configurado para iniciar com o Windows."""
        try:
            from . import startup
        except Exception:
            return False
        return startup.is_startup_enabled()

    def _on_toggle_startup(self, icon: Icon, item: MenuItem) -> None:
        """Alterna inicialização automática com o Windows."""
        try:
            from . import startup
        except Exception:
            logger.exception("Failed to import startup module")
            return
        new_state = startup.toggle_startup()
        status = "ativado" if new_state else "desativado"
        logger.info("Iniciar com Windows: %s", status)

    def _on_about(self, icon: Icon, item: MenuItem) -> None:
        """Exibe diálogo 'Sobre' com informações do app."""
        # Use a dedicated thread so pystray callbacks are not blocked
        try:
            from . import about
        except Exception:
            logger.exception("Failed to import about module")
            return

        def _show():
            about.show_about(icon=self._icon if self._icon is not None else None)

        t = threading.Thread(target=_show, daemon=True)
        t.start()

    def _on_quit(self, icon: Icon, item: MenuItem) -> None:
        """Encerra a aplicação."""
        logger.info("Encerrando like-move...")
        if self._monitor:
            self._monitor.stop()
        if self._device_monitor:
            self._device_monitor.stop()
            self._device_monitor = None
        icon.stop()

    def _trusted_header_text(self, item: MenuItem) -> str:
        """Texto (dinâmico) que lista as redes confiáveis salvas."""
        nets = self._state.trusted_networks
        if not nets:
            return "Nenhuma rede confiável"
        names = ", ".join(str(n.get("ssid", "?")) for n in nets[:3])
        extra = "…" if len(nets) > 3 else ""
        return f"Confiáveis: {names}{extra}"

    def _is_trusted_only_checked(self, item: MenuItem) -> bool:
        """Estado do toggle 'Só em redes confiáveis'."""
        return self._state.trusted_only

    def _on_toggle_trusted_only(self, icon: Icon, item: MenuItem) -> None:
        """Liga/desliga o gate de rede confiável."""
        self._state.trusted_only = not self._state.trusted_only
        self._state.save()
        status = "ativado" if self._state.trusted_only else "desativado"
        logger.info("Só em redes confiáveis: %s", status)
        if self._icon:
            self._icon.update_menu()

    def _is_current_network_trusted(self, item: MenuItem) -> bool:
        """Visibilidade do item 'remover rede atual' (só se estiver na lista)."""
        info = get_current_connection()
        if not info.ssid:
            return False
        return any(n.get("ssid") == info.ssid for n in self._state.trusted_networks)

    def _on_mark_current_network(self, icon: Icon, item: MenuItem) -> None:
        """Marca a rede Wi-Fi conectada agora como confiável (SSID + BSSID)."""
        info = get_current_connection(use_cache=False)
        if not info.connected or not info.ssid:
            if self._icon:
                self._icon.notify(
                    "Nenhuma rede Wi-Fi conectada no momento.", "like-move"
                )
            return
        # Dedup por SSID — mantém apenas a entrada mais recente
        nets = [
            n for n in self._state.trusted_networks if n.get("ssid") != info.ssid
        ]
        nets.append({"ssid": info.ssid, "bssid": info.bssid or ""})
        self._state.trusted_networks = nets
        self._state.save()
        logger.info("Rede confiável adicionada: %s (%s)", info.ssid, info.bssid)
        if self._icon:
            self._icon.notify(
                f"Rede '{info.ssid}' marcada como confiável.", "like-move"
            )
            self._icon.update_menu()

    def _on_remove_current_network(self, icon: Icon, item: MenuItem) -> None:
        """Remove a rede atual da lista de confiáveis."""
        info = get_current_connection(use_cache=False)
        ssid = info.ssid
        if not ssid:
            return
        remaining = [
            n for n in self._state.trusted_networks if n.get("ssid") != ssid
        ]
        if len(remaining) != len(self._state.trusted_networks):
            self._state.trusted_networks = remaining
            self._state.save()
            logger.info("Rede confiável removida: %s", ssid)
            if self._icon:
                self._icon.notify(
                    f"Rede '{ssid}' removida das confiáveis.", "like-move"
                )
                self._icon.update_menu()

    def _on_clear_trusted(self, icon: Icon, item: MenuItem) -> None:
        """Esquece todas as redes confiáveis."""
        if not self._state.trusted_networks:
            return
        self._state.trusted_networks = []
        self._state.save()
        logger.info("Lista de redes confiáveis limpa")
        if self._icon:
            self._icon.notify("Lista de redes confiáveis limpa.", "like-move")
            self._icon.update_menu()

    # ── Auto-update ────────────────────────────────────────────────
    def _run_update_check(self, notify_no_update: bool) -> None:
        """Verifica atualizações em background e atualiza o menu/notifica."""
        def worker() -> None:
            info = updater.check_for_update()
            self._pending_update = info
            if self._icon:
                if info:
                    self._icon.notify(
                        f"Atualização {info.tag} disponível!", "like-move"
                    )
                elif notify_no_update:
                    self._icon.notify(
                        "Você já está na versão mais recente.", "like-move"
                    )
                self._icon.update_menu()

        threading.Thread(
            target=worker, daemon=True, name="like-move-update-check"
        ).start()

    def _on_check_updates(self, icon: Icon, item: MenuItem) -> None:
        """Verificação manual de atualização."""
        self._run_update_check(notify_no_update=True)

    def _is_update_pending(self, item: MenuItem) -> bool:
        return self._pending_update is not None

    def _apply_pending_text(self, item: MenuItem) -> str:
        info = self._pending_update
        return f"Atualizar para {info.tag}" if info else "Atualizar"

    def _is_update_check_checked(self, item: MenuItem) -> bool:
        return self._state.check_updates_on_start

    def _on_toggle_update_check(self, icon: Icon, item: MenuItem) -> None:
        self._state.check_updates_on_start = not self._state.check_updates_on_start
        self._state.save()
        logger.info(
            "Verificar atualizações ao iniciar: %s",
            "ativado" if self._state.check_updates_on_start else "desativado",
        )
        if self._icon:
            self._icon.update_menu()

    def _quit_for_update(self) -> None:
        """Encerra o app para a nova versão assumir."""
        logger.info("Encerrando para aplicar atualização...")
        if self._monitor:
            self._monitor.stop()
        if self._device_monitor:
            self._device_monitor.stop()
            self._device_monitor = None
        if self._icon:
            self._icon.stop()

    def _on_apply_update(self, icon: Icon, item: MenuItem) -> None:
        """Baixa e aplica a atualização pendente (ou abre a página em dev)."""
        info = self._pending_update
        if not info:
            return

        if not updater.is_frozen():
            # Modo dev: não troca binário; abre a página de releases
            import webbrowser
            webbrowser.open(info.html_url or updater.releases_page())
            return

        if self._icon:
            self._icon.notify(f"Baixando atualização {info.tag}...", "like-move")

        def worker() -> None:
            new_exe = updater.download_and_stage(info)
            if not new_exe:
                if self._icon:
                    self._icon.notify(
                        "Falha ao baixar a atualização.", "like-move"
                    )
                return
            if updater.launch_new(new_exe):
                self._quit_for_update()
            elif self._icon:
                self._icon.notify(
                    "Falha ao iniciar a atualização.", "like-move"
                )

        threading.Thread(
            target=worker, daemon=True, name="like-move-update-apply"
        ).start()

    def _build_menu(self) -> Menu:
        """Constrói o menu de contexto do tray."""
        # Mode submenu (radio)
        mode_items = [
            MenuItem(
                _MODE_LABELS[mode],
                self._on_set_mode(mode),
                checked=self._is_mode_checked(mode),
                radio=True,
            )
            for mode in TriggerMode
        ]

        # KVM device submenu (checkable, visible when mode includes KVM)
        device_items = [
            MenuItem(
                _DEVICE_LABELS[device],
                self._on_toggle_device(device),
                checked=self._is_device_checked(device),
            )
            for device in ("monitor", "mouse", "keyboard")
        ]

        # Threshold submenu
        threshold_items = [
            MenuItem(
                _format_threshold(s),
                self._on_set_threshold(s),
                checked=self._is_threshold_checked(s),
                radio=True,
            )
            for s in THRESHOLD_OPTIONS
        ]

        cpu_items = [
            MenuItem(label, self._on_set_cpu_threshold(pct), checked=self._is_cpu_threshold_checked(pct), radio=True)
            for pct, label in CPU_OPTIONS
        ]

        network_items = [
            MenuItem(label, self._on_set_network_threshold(kbps), checked=self._is_network_threshold_checked(kbps), radio=True)
            for kbps, label in NETWORK_OPTIONS
        ]

        battery_items = [
            MenuItem(label, self._on_set_battery_floor(pct), checked=self._is_battery_floor_checked(pct), radio=True)
            for pct, label in BATTERY_OPTIONS
        ]

        work_hours_items = [
            MenuItem("Ligado", self._on_toggle_work_hours, checked=lambda item: self._state.work_hours["enabled"]),
            Menu.SEPARATOR,
            *[
                MenuItem(label, self._on_set_work_hours(days, start, end),
                         checked=self._is_work_hours_checked(days, start, end), radio=True)
                for label, days, start, end in WORK_HOURS_PRESETS
            ],
        ]

        # Redes Wi-Fi confiáveis (segurança): submenu
        trusted_items = [
            MenuItem(self._trusted_header_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "Marcar rede atual como confiável",
                self._on_mark_current_network,
            ),
            MenuItem(
                "Remover rede atual da lista",
                self._on_remove_current_network,
                visible=self._is_current_network_trusted,
            ),
            MenuItem("Esquecer todas as redes", self._on_clear_trusted),
            Menu.SEPARATOR,
            MenuItem(
                "Só em redes confiáveis",
                self._on_toggle_trusted_only,
                checked=self._is_trusted_only_checked,
            ),
            MenuItem(
                "Bloquear a tela ao sair da rede",
                self._on_toggle_lock_on_untrusted,
                checked=lambda item: self._state.lock_on_untrusted,
            ),
        ]

        timer_items = [
            MenuItem(self._timer_header_text, None, enabled=False, visible=self._is_timer_active),
            *[
                MenuItem(label, self._on_set_timer_minutes(minutes))
                for minutes, label in TIMER_MINUTES
            ],
            *[
                MenuItem(f"Até {h:02d}:{m:02d}", self._on_set_timer_until(h, m))
                for h, m in TIMER_CLOCK_TIMES
            ],
            MenuItem("Cancelar prazo", self._on_cancel_timer, visible=self._is_timer_active),
        ]

        return Menu(
            MenuItem(self._status_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "Ativo",
                self._on_toggle,
                checked=lambda item: self._state.enabled,
                default=True,
            ),
            Menu.SEPARATOR,
            MenuItem("Modo", Menu(*mode_items)),
            MenuItem(
                "Dispositivos KVM",
                Menu(*device_items),
                visible=lambda item: self._state.trigger_mode
                in (TriggerMode.KVM, TriggerMode.BOTH),
            ),
            MenuItem("Threshold", Menu(*threshold_items)),
            MenuItem("Manter acordado por…", Menu(*timer_items)),
            MenuItem("Horário de trabalho", Menu(*work_hours_items)),
            MenuItem("Programas vigiados", Menu(self._watched_menu_items)),
            MenuItem("CPU ocupada", Menu(*cpu_items)),
            MenuItem("Rede ocupada", Menu(*network_items)),
            MenuItem("Redes confiáveis", Menu(*trusted_items)),
            MenuItem(
                "Só na tomada",
                self._on_toggle_ac_only,
                checked=lambda item: self._state.ac_only,
            ),
            MenuItem("Bateria mínima", Menu(*battery_items)),
            MenuItem(
                "Bloquear a tela ao terminar",
                self._on_toggle_lock_when_done,
                checked=lambda item: self._state.lock_when_done,
            ),
            MenuItem(
                "Tela pode apagar",
                self._on_toggle_display_may_sleep,
                checked=lambda item: self._state.display_may_sleep,
            ),
            MenuItem(
                "Avisar nas mudanças",
                self._on_toggle_notify_transitions,
                checked=lambda item: self._state.notify_transitions,
            ),
            MenuItem("Diagnosticar bloqueio", self._on_diagnose),
            Menu.SEPARATOR,
            MenuItem(
                "Iniciar com Windows",
                self._on_toggle_startup,
                checked=self._is_startup_checked,
            ),
            MenuItem(
                self._apply_pending_text,
                self._on_apply_update,
                visible=self._is_update_pending,
            ),
            MenuItem("Verificar atualizações", self._on_check_updates),
            MenuItem(
                "Verificar ao iniciar",
                self._on_toggle_update_check,
                checked=self._is_update_check_checked,
            ),
            MenuItem("Sobre", self._on_about),
            MenuItem("Sair", self._on_quit),
        )

    def _refresh_menu_on_open(self, icon: Icon) -> None:
        """Reconstrói o menu a cada clique direito.

        O pystray no Windows monta o menu nativo em ``update_menu`` e não ao exibi-lo: sem isto a linha de
        status e as entradas do prazo mostrariam o texto de quando o menu foi montado pela última vez.
        """
        try:
            handlers = icon._message_handlers  # type: ignore[attr-defined]
            original = handlers[_pystray_win32.WM_NOTIFY]
        except (AttributeError, KeyError):
            logger.error("pystray sem o tratador de cliques esperado; a linha de status pode ficar desatualizada", exc_info=True)
            return

        def on_notify(wparam: int, lparam: int) -> Any:
            if lparam == _pystray_win32.WM_RBUTTONUP:
                icon.update_menu()
            return original(wparam, lparam)

        handlers[_pystray_win32.WM_NOTIFY] = on_notify

    def _setup(self, icon: Icon) -> None:
        """Callback executado quando o ícone está pronto.

        Inicia a thread de monitoramento.
        """
        self._icon = icon
        self._refresh_menu_on_open(icon)
        icon.visible = True

        self._monitor = MonitorThread(self._state)
        self._monitor.notifier = lambda message: icon.notify(message, "like-move")
        self._monitor.start()
        self._ensure_device_monitor()

        # Verificação de atualização ao iniciar (silenciosa se estiver em dia)
        if self._state.check_updates_on_start:
            self._run_update_check(notify_no_update=False)

        # Toast notification via pystray (balloon/Action Center)
        icon.notify(
            "like-move está rodando — clique direito para configurar",
            "like-move",
        )
        logger.info("like-move iniciado — ícone na bandeja do sistema")

    def _ensure_device_monitor(self) -> None:
        """Create or destroy DeviceMonitor based on current trigger mode."""
        needs_kvm = self._state.trigger_mode in (
            TriggerMode.KVM,
            TriggerMode.BOTH,
        )

        if needs_kvm and self._device_monitor is None:
            self._device_monitor = DeviceMonitor(self._state.monitor_devices)
            self._device_monitor.start()
            if self._monitor:
                self._monitor.set_device_monitor(self._device_monitor)
            logger.info("Device monitor criado (event-driven)")
        elif not needs_kvm and self._device_monitor is not None:
            if self._monitor:
                self._monitor.set_device_monitor(None)
            self._device_monitor.stop()
            self._device_monitor = None
            logger.info("Device monitor destruído")
        elif needs_kvm and self._device_monitor is not None:
            # Mode still includes KVM — refresh baseline
            self._device_monitor.refresh_baseline()

    def run(self) -> None:
        """Inicia a aplicação (blocking)."""
        icon = Icon(
            name="like-move",
            icon=create_icon_image(self._state.enabled),
            title="like-move — tela sem bloquear",
            menu=self._build_menu(),
        )
        self._icon = icon
        icon.run(setup=self._setup)
