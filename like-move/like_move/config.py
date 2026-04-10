"""Configurações do like-move."""


# Tempo de inatividade (segundos) antes de começar o jiggle
IDLE_THRESHOLD_SECONDS: int = 30

# Intervalo entre jiggles enquanto idle (segundos)
JIGGLE_INTERVAL_SECONDS: int = 10

# Intervalo de verificação do estado de idle (segundos)
CHECK_INTERVAL_SECONDS: int = 1

# Deslocamento do mouse em pixels (ida e volta)
JIGGLE_PIXELS: int = 1


class JigglerState:
    """Estado mutável do jiggler em runtime."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self.idle_threshold: int = IDLE_THRESHOLD_SECONDS
        self.jiggle_interval: int = JIGGLE_INTERVAL_SECONDS
