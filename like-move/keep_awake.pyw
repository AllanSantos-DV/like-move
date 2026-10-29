"""keep_awake — impede o Windows de dormir ou apagar a tela.

Usa apenas SetThreadExecutionState (ES_CONTINUOUS | ES_SYSTEM_REQUIRED |
ES_DISPLAY_REQUIRED). Sem simular mouse/teclado, sem rede, sem registro.
O pedido vale enquanto este processo roda e some quando ele termina.

Uso (sem janela):  pythonw keep_awake.pyw
Parar:             encerrar o processo pythonw (Gerenciador de Tarefas)
Verificar:         powercfg /requests   (como administrador)
"""

import ctypes
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# Reafirma o pedido periodicamente por segurança; ES_CONTINUOUS já o mantém.
REFRESH_SECONDS = 60


def keep_awake(stop: threading.Event) -> None:
    """Mantém o pedido de execução ativo até `stop` ser sinalizado."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    try:
        # O estado vale por thread: a mesma thread precisa chamar e ficar viva.
        while not stop.is_set():
            if kernel32.SetThreadExecutionState(flags) == 0:
                raise OSError("SetThreadExecutionState falhou")
            stop.wait(REFRESH_SECONDS)
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)


if __name__ == "__main__":
    keep_awake(threading.Event())
