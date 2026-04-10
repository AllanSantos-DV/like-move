"""Configurações do like-move."""

import enum


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


class JigglerState:
    """Estado mutável do jiggler em runtime."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self.idle_threshold: int = IDLE_THRESHOLD_SECONDS
        self.jiggle_interval: int = JIGGLE_INTERVAL_SECONDS
        self.trigger_mode: TriggerMode = TriggerMode.IDLE
        self.monitor_devices: set[str] = {"monitor"}
