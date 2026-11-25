"""Configurações do like-move."""

import enum
import logging

from . import settings

logger = logging.getLogger(__name__)


# Tempo de inatividade (segundos) antes de manter a máquina acordada
IDLE_THRESHOLD_SECONDS: int = 30

# Intervalo de verificação do estado de idle (segundos)
CHECK_INTERVAL_SECONDS: int = 1


class TriggerMode(enum.Enum):
    """Quando manter a máquina acordada."""

    IDLE = "idle"        # Quando idle > threshold (GetLastInputInfo)
    KVM = "kvm"          # Quando um dispositivo monitorado desconecta
    BOTH = "both"        # Qualquer uma das duas condições
    ALWAYS = "always"    # Sempre (controle manual pelo tray)

    @classmethod
    def from_value(cls, value: str) -> "TriggerMode":
        """Converte uma string para TriggerMode, com fallback para IDLE."""
        for mode in cls:
            if mode.value == value:
                return mode
        return cls.IDLE


class JigglerState:
    """Estado mutável do like-move em runtime, persistido em ``%APPDATA%``.

    Na inicialização carrega os valores salvos (ou os defaults). Chame
    :meth:`save` após qualquer mutação para persistir.
    """

    def __init__(self) -> None:
        data = settings.load()

        # Comportamento base
        self.enabled: bool = bool(data.get("enabled", True))
        self.idle_threshold: int = int(data.get("idle_threshold", IDLE_THRESHOLD_SECONDS))
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

        # Funções opcionais: todas desligadas por padrão
        self.ac_only: bool = bool(data.get("ac_only", False))
        self.lock_on_untrusted: bool = bool(data.get("lock_on_untrusted", False))
        self.notify_transitions: bool = bool(data.get("notify_transitions", False))
        try:
            self.awake_until: float = float(data.get("awake_until", 0.0) or 0.0)
        except (TypeError, ValueError):
            logger.warning("awake_until inválido na configuração; ignorando o prazo")
            self.awake_until = 0.0

    def to_dict(self) -> dict:
        """Serializa o estado para persistência (JSON-friendly)."""
        return {
            "enabled": self.enabled,
            "idle_threshold": self.idle_threshold,
            "trigger_mode": self.trigger_mode.value,
            "monitor_devices": sorted(self.monitor_devices),
            "trusted_only": self.trusted_only,
            "wired_is_trusted": self.wired_is_trusted,
            "match_bssid": self.match_bssid,
            "trusted_networks": self.trusted_networks,
            "check_updates_on_start": self.check_updates_on_start,
            "ac_only": self.ac_only,
            "lock_on_untrusted": self.lock_on_untrusted,
            "notify_transitions": self.notify_transitions,
            "awake_until": self.awake_until,
        }

    def save(self) -> None:
        """Persiste o estado atual no arquivo de configuração."""
        settings.save(self.to_dict())
