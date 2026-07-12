"""Configurações do like-move."""

import enum

from . import settings


# Tempo de inatividade (segundos) antes de começar o jiggle
IDLE_THRESHOLD_SECONDS: int = 30

# Intervalo entre jiggles enquanto idle (segundos)
JIGGLE_INTERVAL_SECONDS: int = 10

# Intervalo de verificação do estado de idle (segundos)
CHECK_INTERVAL_SECONDS: int = 1

# Deslocamento do mouse em pixels (ida e volta)
JIGGLE_PIXELS: int = 1


class TriggerMode(enum.Enum):
    """Modos de trigger para o jiggler."""

    IDLE = "idle"        # Jiggle quando idle > threshold (GetLastInputInfo)
    KVM = "kvm"          # Jiggle quando dispositivo desconecta
    BOTH = "both"        # Qualquer trigger ativa o jiggle
    ALWAYS = "always"    # Jiggle contínuo (controle manual pelo tray)

    @classmethod
    def from_value(cls, value: str) -> "TriggerMode":
        """Converte uma string para TriggerMode, com fallback para IDLE."""
        for mode in cls:
            if mode.value == value:
                return mode
        return cls.IDLE


class JigglerState:
    """Estado mutável do jiggler em runtime, persistido em ``%APPDATA%``.

    Na inicialização carrega os valores salvos (ou os defaults). Chame
    :meth:`save` após qualquer mutação para persistir.
    """

    def __init__(self) -> None:
        data = settings.load()

        # Comportamento base do jiggler
        self.enabled: bool = bool(data.get("enabled", True))
        self.idle_threshold: int = int(data.get("idle_threshold", IDLE_THRESHOLD_SECONDS))
        self.jiggle_interval: int = int(data.get("jiggle_interval", JIGGLE_INTERVAL_SECONDS))
        self.trigger_mode: TriggerMode = TriggerMode.from_value(
            str(data.get("trigger_mode", TriggerMode.IDLE.value))
        )
        self.monitor_devices: set[str] = set(data.get("monitor_devices") or ["monitor"])

        # Gate de rede Wi-Fi confiável (segurança)
        self.trusted_only: bool = bool(data.get("trusted_only", False))
        self.wired_is_trusted: bool = bool(data.get("wired_is_trusted", True))
        self.match_bssid: bool = bool(data.get("match_bssid", True))
        self.trusted_networks: list[dict[str, str]] = list(data.get("trusted_networks") or [])

        # Auto-update
        self.check_updates_on_start: bool = bool(data.get("check_updates_on_start", True))

    def to_dict(self) -> dict:
        """Serializa o estado para persistência (JSON-friendly)."""
        return {
            "enabled": self.enabled,
            "idle_threshold": self.idle_threshold,
            "jiggle_interval": self.jiggle_interval,
            "trigger_mode": self.trigger_mode.value,
            "monitor_devices": sorted(self.monitor_devices),
            "trusted_only": self.trusted_only,
            "wired_is_trusted": self.wired_is_trusted,
            "match_bssid": self.match_bssid,
            "trusted_networks": self.trusted_networks,
            "check_updates_on_start": self.check_updates_on_start,
        }

    def save(self) -> None:
        """Persiste o estado atual no arquivo de configuração."""
        settings.save(self.to_dict())
