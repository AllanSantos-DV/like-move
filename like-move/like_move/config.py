"""Configurações do like-move."""

import enum
import logging

from . import settings, timer

logger = logging.getLogger(__name__)


# Tempo de inatividade (segundos) antes de manter a máquina acordada
IDLE_THRESHOLD_SECONDS: int = 30

# Intervalo de verificação do estado de idle (segundos)
CHECK_INTERVAL_SECONDS: int = 1


def _clean_process_list(value: object) -> list[str]:
    """Lista de nomes de programas vigiados; qualquer outra coisa na configuração vira lista vazia, com aviso."""
    if value is None:
        return []
    if not isinstance(value, list):
        logger.warning("watched_processes inválido na configuração; ignorando")
        return []
    valid = [v for v in value if isinstance(v, str) and v.strip()]
    if len(valid) != len(value):
        logger.warning("watched_processes com %d item(ns) inválido(s) na configuração; mantendo os válidos", len(value) - len(valid))
    return valid


def _clean_cpu_threshold(value: object) -> int:
    """Limite de CPU em % (0 = desligado); valor fora de 0..100 ou não numérico volta a 0, com aviso."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        logger.warning("cpu_threshold inválido na configuração; desligando")
        return 0
    return value


def _clean_battery_floor(value: object) -> int:
    """Carga mínima da bateria em % (0 = desligado); valor fora de 0..100 ou não numérico volta a 0, com aviso."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        logger.warning("battery_floor inválido na configuração; desligando")
        return 0
    return value


def _clean_work_hours(value: object) -> dict:
    """Horário de trabalho da configuração; ausente ou malformado volta ao padrão (desligado), com aviso se malformado."""
    default = settings.DEFAULTS["work_hours"]
    if value is None:
        return {**default, "days": list(default["days"])}
    parsed = timer.parse_work_hours(value)
    if parsed is None:
        logger.warning("work_hours inválido na configuração; desligando")
        return {**default, "days": list(default["days"])}
    return parsed


def _clean_network_threshold(value: object) -> int:
    """Limite de rede em KB/s (0 = desligado); valor negativo ou não numérico volta a 0, com aviso."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        logger.warning("network_threshold_kbps inválido na configuração; desligando")
        return 0
    return value


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
        self.display_may_sleep: bool = bool(data.get("display_may_sleep", False))
        self.notify_transitions: bool = bool(data.get("notify_transitions", False))
        self.watched_processes: list[str] = _clean_process_list(data.get("watched_processes"))
        self.cpu_threshold: int = _clean_cpu_threshold(data.get("cpu_threshold"))
        self.battery_floor: int = _clean_battery_floor(data.get("battery_floor"))
        self.lock_when_done: bool = bool(data.get("lock_when_done", False))
        self.work_hours: dict = _clean_work_hours(data.get("work_hours"))
        self.network_threshold_kbps: int = _clean_network_threshold(data.get("network_threshold_kbps"))
        self.docked_monitors: bool = bool(data.get("docked_monitors", False))
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
            "display_may_sleep": self.display_may_sleep,
            "notify_transitions": self.notify_transitions,
            "awake_until": self.awake_until,
            "watched_processes": self.watched_processes,
            "cpu_threshold": self.cpu_threshold,
            "battery_floor": self.battery_floor,
            "lock_when_done": self.lock_when_done,
            "work_hours": self.work_hours,
            "network_threshold_kbps": self.network_threshold_kbps,
            "docked_monitors": self.docked_monitors,
        }

    def save(self) -> None:
        """Persiste o estado atual no arquivo de configuração."""
        settings.save(self.to_dict())
