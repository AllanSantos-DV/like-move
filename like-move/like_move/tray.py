"""System tray icon com pystray para controle do like-move."""

import logging
from typing import Any, Optional

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem
import threading


from .config import JigglerState, TriggerMode
from .device_monitor import DeviceMonitor
from .awake import MonitorThread
from .wifi import get_current_connection
from . import updater

logger = logging.getLogger(__name__)

# Thresholds disponíveis no menu (segundos)
THRESHOLD_OPTIONS: list[int] = [15, 30, 60, 120, 300]

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

    def _on_toggle(self, icon: Icon, item: MenuItem) -> None:
        """Alterna entre ativado/desativado."""
        self._state.enabled = not self._state.enabled
        status = "ativado" if self._state.enabled else "desativado"
        logger.info("like-move %s", status)

        # Atualiza ícone para refletir estado
        if self._icon:
            self._icon.icon = create_icon_image(self._state.enabled)
        self._state.save()

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
        ]

        return Menu(
            MenuItem(
                "Ativo",
                self._on_toggle,
                checked=lambda item: self._state.enabled,
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
            MenuItem("Redes confiáveis", Menu(*trusted_items)),
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

    def _setup(self, icon: Icon) -> None:
        """Callback executado quando o ícone está pronto.

        Inicia a thread de monitoramento.
        """
        self._icon = icon
        icon.visible = True

        self._monitor = MonitorThread(self._state)
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
