"""Persistência de configurações do like-move em ``%APPDATA%``.

Armazena um JSON simples e tolerante a versões: campos ausentes são
preenchidos com os defaults e campos desconhecidos são ignorados na
carga. A escrita é atômica (arquivo temporário + ``os.replace``) para
evitar corrupção se o processo for encerrado no meio da gravação.

Este módulo depende apenas da stdlib — não importa ``config`` (para
evitar dependência circular) nem nada de terceiros.
"""

import json
import logging
import os
import tempfile
import threading
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR_NAME = "like-move"
CONFIG_FILENAME = "config.json"

# Valores padrão — também servem de "esquema" tolerante a versões.
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "idle_threshold": 30,
    "trigger_mode": "idle",
    "monitor_devices": ["monitor"],
    # Gate de rede Wi-Fi confiável
    "trusted_only": False,
    "wired_is_trusted": True,
    "match_bssid": True,
    "trusted_networks": [],  # lista de {"ssid": str, "bssid": str}
    # Auto-update
    "check_updates_on_start": True,
}

_lock = threading.Lock()


def config_dir() -> str:
    """Diretório de configuração do like-move (cria-se sob demanda)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    """Caminho completo do arquivo ``config.json``."""
    return os.path.join(config_dir(), CONFIG_FILENAME)


def load() -> dict[str, Any]:
    """Carrega as configurações mescladas sobre os defaults.

    Nunca levanta exceção: em qualquer falha de leitura/parse, retorna
    os defaults (log em nível warning).
    """
    data: dict[str, Any] = dict(DEFAULTS)
    path = config_path()
    try:
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            data.update(stored)
        else:
            logger.warning("Config em %s não é um objeto JSON; usando defaults", path)
    except FileNotFoundError:
        logger.info("Config inexistente (%s); usando defaults", path)
    except (OSError, ValueError):
        logger.warning("Falha ao ler config (%s); usando defaults", path, exc_info=True)
    return data


def save(data: dict[str, Any]) -> bool:
    """Persiste as configurações de forma atômica.

    Returns:
        ``True`` se gravou com sucesso, ``False`` caso contrário.
    """
    path = config_path()
    directory = config_dir()
    try:
        os.makedirs(directory, exist_ok=True)
        with _lock:
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cfg-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
                tmp = None  # movido com sucesso
            finally:
                if tmp is not None and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        logger.debug("Falha ao limpar temporário %s", tmp, exc_info=True)
        return True
    except OSError:
        logger.warning("Falha ao salvar config em %s", path, exc_info=True)
        return False
