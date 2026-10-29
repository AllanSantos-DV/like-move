"""like-move — mantém o Windows sem bloquear, só quando você quer.

Previne o bloqueio de tela por inatividade (inclusive atrás de um KVM switch)
sem simular mouse ou teclado. Roda na bandeja do sistema sem janela de console.

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


def _replaced_dir(argv: list[str]) -> str:
    """Pasta da versão anterior passada em ``--replaced <pasta>`` ("" se ausente)."""
    from like_move.updater import REPLACED_ARG

    if REPLACED_ARG in argv[:-1]:
        return argv[argv.index(REPLACED_ARG) + 1]
    return ""


def main() -> None:
    """Entry point principal."""
    # Verificar se está rodando no Windows
    if sys.platform != "win32":
        logger.error("like-move só funciona no Windows.")
        sys.exit(1)

    from like_move import __version__

    logger.info("Iniciando like-move v%s...", __version__)

    # Aberto pela versão anterior depois de uma atualização: limpa a pasta antiga
    # e reaponta "Iniciar com Windows" para este executável.
    if old_dir := _replaced_dir(sys.argv):
        from like_move import startup, updater

        updater.cleanup_previous(old_dir)
        if startup.is_startup_enabled():
            startup.enable_startup()

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
