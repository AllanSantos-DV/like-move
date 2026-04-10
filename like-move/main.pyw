"""like-move — Mouse jiggler inteligente para Windows.

Previne bloqueio de tela por inatividade quando o usuário alterna entre
PCs via KVM switch. Roda na bandeja do sistema sem janela de console.

Uso: pythonw main.pyw
"""

import logging
import sys

# Configurar logging (vai para stderr quando executado com python;
# silencioso com pythonw pois não há console)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("like-move")


def main() -> None:
    """Entry point principal."""
    # Verificar se está rodando no Windows
    if sys.platform != "win32":
        logger.error("like-move só funciona no Windows.")
        sys.exit(1)

    logger.info("Iniciando like-move v1.0.0...")

    # Splash screen com fade animation (~2.5 s)
    from like_move.splash import show_splash

    show_splash()

    from like_move.tray import TrayApp

    app = TrayApp()

    try:
        # app.run() é blocking — roda o event loop do pystray
        # O MonitorThread é iniciado via setup callback do tray icon
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
    except Exception:
        logger.exception("Erro fatal")
        sys.exit(1)

    logger.info("like-move encerrado.")


if __name__ == "__main__":
    main()
