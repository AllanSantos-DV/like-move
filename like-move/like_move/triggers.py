"""Gatilhos por programa em execução e por carga de CPU: lógica pura, sem chamar o Windows."""

from typing import Iterable, Optional

# Leituras seguidas acima do limite para a CPU contar como ocupada, e abaixo para deixar de contar:
# a saída é lenta para um trabalho com pausas curtas não ficar ligando e desligando o pedido.
CPU_ON_TICKS: int = 5
CPU_OFF_TICKS: int = 30


def normalize_process_name(name: str) -> str:
    """Nome como o Windows lista: minúsculo, sem espaços nas pontas e com ``.exe`` quando faltar."""
    name = name.strip().lower()
    return name if not name or "." in name else name + ".exe"


def any_running(watched: Iterable[str], running: Iterable[str]) -> bool:
    """True se algum programa vigiado está entre os que rodam agora."""
    wanted = {normalize_process_name(n) for n in watched}
    wanted.discard("")
    return not wanted.isdisjoint(running)


def cpu_percent(previous: tuple, current: tuple) -> Optional[float]:
    """Uso da CPU (0 a 100) entre duas leituras de ``get_system_times``; ``None`` se o tempo não avançou."""
    idle = current[0] - previous[0]
    total = (current[1] - previous[1]) + (current[2] - previous[2])
    if total <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (1.0 - idle / total)))


class CpuLoadGate:
    """Histerese da carga de CPU: liga depois de ``CPU_ON_TICKS`` leituras acima do limite e só desliga depois de
    ``CPU_OFF_TICKS`` leituras abaixo dele."""

    def __init__(self) -> None:
        self.busy = False
        self._streak = 0

    def reset(self) -> None:
        """Esquece o histórico (opção desligada)."""
        self.busy = False
        self._streak = 0

    def update(self, percent: Optional[float], threshold: int) -> bool:
        """Registra uma leitura e devolve se a CPU conta como ocupada. Leitura ausente mantém o estado."""
        if percent is None:
            return self.busy
        above = percent >= threshold
        if above == self.busy:
            self._streak = 0
            return self.busy
        self._streak += 1
        if self._streak >= (CPU_ON_TICKS if above else CPU_OFF_TICKS):
            self.busy = above
            self._streak = 0
        return self.busy
