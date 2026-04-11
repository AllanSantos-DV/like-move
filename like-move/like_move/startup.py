"""Gerencia inicialização automática do like-move com o Windows.

Usa a chave de registro HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
para registrar/remover o like-move — não requer privilégios de administrador.
"""

import logging
import sys
import winreg

logger = logging.getLogger(__name__)

APP_NAME = "like-move"
_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_startup_enabled() -> bool:
    """Verifica se o like-move está configurado para iniciar com o Windows."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        logger.warning("Não foi possível acessar o registro do Windows")
        return False


def enable_startup() -> None:
    """Registra o like-move para iniciar com o Windows."""
    if not getattr(sys, "frozen", False):
        logger.warning("Startup automático só funciona no .exe empacotado")
        return

    exe_path = sys.executable
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        )
        try:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            logger.info("Startup registrado: %s", exe_path)
        finally:
            winreg.CloseKey(key)
    except OSError:
        logger.exception("Falha ao registrar startup no registro")


def disable_startup() -> None:
    """Remove o like-move da inicialização automática do Windows."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        )
        try:
            winreg.DeleteValue(key, APP_NAME)
            logger.info("Startup removido do registro")
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
    except OSError:
        logger.exception("Falha ao remover startup do registro")


def toggle_startup() -> bool:
    """Alterna o estado de inicialização automática. Retorna o novo estado."""
    if is_startup_enabled():
        disable_startup()
        return False
    else:
        enable_startup()
        return True
