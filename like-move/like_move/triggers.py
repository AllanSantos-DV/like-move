"""Gatilhos por programa em execução, por carga de CPU e por tráfego de rede: lógica pura, sem chamar o Windows."""

from typing import Hashable, Iterable, Mapping, Optional

# Leituras seguidas acima do limite para a CPU contar como ocupada, e abaixo para deixar de contar:
# a saída é lenta para um trabalho com pausas curtas não ficar ligando e desligando o pedido.
CPU_ON_TICKS: int = 5
CPU_OFF_TICKS: int = 30

# Mesma histerese para o tráfego de rede, que também oscila em rajadas
NETWORK_ON_TICKS: int = 5
NETWORK_OFF_TICKS: int = 30

# Contadores de octetos de 32 bits (DWORD) voltam a zero depois de 4 GiB
_COUNTER_MODULUS: int = 1 << 32


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


def bytes_per_second(
    previous: Mapping[Hashable, tuple[int, int]], current: Mapping[Hashable, tuple[int, int]], elapsed: float,
) -> Optional[float]:
    """Tráfego total (recebido + enviado) em bytes por segundo entre duas leituras de ``get_interface_octets``.

    Cada leitura mapeia a interface para ``(octetos recebidos, octetos enviados)``. A diferença é feita módulo 2**32,
    então a volta de um contador de 32 bits não vira um salto negativo (para um intervalo curto o resultado é o mesmo
    com contadores de 64 bits). Só contam as interfaces presentes nas duas leituras, para uma que apareceu ou sumiu não
    inventar tráfego; sem nenhuma em comum o tráfego medido é zero. ``None`` se o tempo não avançou.
    """
    if elapsed <= 0:
        return None
    moved = 0
    for key in previous.keys() & current.keys():
        before_in, before_out = previous[key]
        now_in, now_out = current[key]
        moved += ((now_in - before_in) % _COUNTER_MODULUS) + ((now_out - before_out) % _COUNTER_MODULUS)
    return moved / elapsed


class LoadGate:
    """Histerese de uma carga numérica: liga depois de ``on_ticks`` leituras acima do limite e só desliga depois de
    ``off_ticks`` leituras abaixo dele."""

    def __init__(self, on_ticks: int, off_ticks: int) -> None:
        self._on_ticks = on_ticks
        self._off_ticks = off_ticks
        self.busy = False
        self._streak = 0

    def reset(self) -> None:
        """Esquece o histórico (opção desligada)."""
        self.busy = False
        self._streak = 0

    def update(self, value: Optional[float], threshold: float) -> bool:
        """Registra uma leitura e devolve se a carga conta como ocupada. Leitura ausente mantém o estado."""
        if value is None:
            return self.busy
        above = value >= threshold
        if above == self.busy:
            self._streak = 0
            return self.busy
        self._streak += 1
        if self._streak >= (self._on_ticks if above else self._off_ticks):
            self.busy = above
            self._streak = 0
        return self.busy


class CpuLoadGate(LoadGate):
    """Histerese da carga de CPU: ``CPU_ON_TICKS`` leituras acima do limite ligam e ``CPU_OFF_TICKS`` abaixo desligam."""

    def __init__(self) -> None:
        super().__init__(CPU_ON_TICKS, CPU_OFF_TICKS)


class NetworkLoadGate(LoadGate):
    """Histerese do tráfego de rede: ``NETWORK_ON_TICKS`` leituras acima do limite ligam e ``NETWORK_OFF_TICKS`` abaixo desligam."""

    def __init__(self) -> None:
        super().__init__(NETWORK_ON_TICKS, NETWORK_OFF_TICKS)
