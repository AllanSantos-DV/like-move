"""System tray icon com pystray para controle do jiggler."""

import logging
from typing import Any, Optional

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from .config import JigglerState, TriggerMode
from .device_monitor import DeviceMonitor
from .jiggler import MonitorThread

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

    def _on_toggle(self, icon: Icon, item: MenuItem) -> None:
        """Alterna entre ativado/desativado."""
        self._state.enabled = not self._state.enabled
        status = "ativado" if self._state.enabled else "desativado"
        logger.info("Jiggler %s", status)

        # Atualiza ícone para refletir estado
        if self._icon:
            self._icon.icon = create_icon_image(self._state.enabled)

    def _on_set_threshold(self, seconds: int) -> Any:
        """Retorna callback para definir threshold específico."""
        def handler(icon: Icon, item: MenuItem) -> None:
            self._state.idle_threshold = seconds
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

    def _on_quit(self, icon: Icon, item: MenuItem) -> None:
        """Encerra a aplicação."""
        logger.info("Encerrando like-move...")
        if self._monitor:
            self._monitor.stop()
        if self._device_monitor:
            self._device_monitor.stop()
            self._device_monitor = None
        icon.stop()

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
            Menu.SEPARATOR,
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
            title="like-move — Mouse Jiggler",
            menu=self._build_menu(),
        )
        self._icon = icon
        icon.run(setup=self._setup)
