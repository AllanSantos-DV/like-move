"""Auto-update via GitHub Releases (sem dependências externas).

Fluxo (custom, alinhado à filosofia minimalista do projeto):

    GET https://api.github.com/repos/<owner>/<repo>/releases/latest
    → compara ``tag_name`` (ex.: "v1.0.4") com a versão local (VERSION)
    → se houver versão maior, baixa o asset ``.exe`` e substitui o binário
      em execução via um script auxiliar (.bat) que espera o processo sair.

Só faz a troca do binário quando rodando "congelado" (``sys.frozen`` do
PyInstaller). Em modo desenvolvimento (Python), apenas informa e abre a
página de releases no navegador.

Usa somente a stdlib (``urllib``) — nada de ``requests``/``pyupdater``.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from typing import NamedTuple, Optional

from . import __version__

logger = logging.getLogger(__name__)

# Repositório de releases (owner/repo)
REPO: str = "AllanSantos-DV/like-move"
_API_LATEST: str = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASES_PAGE: str = f"https://github.com/{REPO}/releases/latest"
_USER_AGENT: str = "like-move-updater"
_HTTP_TIMEOUT: float = 12.0

# Flags de criação de processo (Windows) para desanexar o helper
_DETACHED_PROCESS: int = 0x00000008
_CREATE_NEW_PROCESS_GROUP: int = 0x00000200
_CREATE_NO_WINDOW: int = 0x08000000


class UpdateInfo(NamedTuple):
    """Metadados de uma atualização disponível."""

    version: str            # ex.: "1.0.4"
    tag: str                # ex.: "v1.0.4"
    download_url: str       # URL do asset .exe
    size: int               # tamanho esperado em bytes (0 se desconhecido)
    notes: str              # release notes
    html_url: str           # página da release


def is_frozen() -> bool:
    """True quando rodando como executável PyInstaller (.exe)."""
    return bool(getattr(sys, "frozen", False))


def releases_page() -> str:
    """URL da página de releases (para abrir no navegador em modo dev)."""
    return _RELEASES_PAGE


def _parse_version(value: str) -> tuple:
    """Converte "v1.2.3" em (1, 2, 3), tolerante a sufixos não numéricos."""
    value = (value or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in value.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str) -> bool:
    """True se a versão ``remote`` for maior que ``local``."""
    return _parse_version(remote) > _parse_version(local)


def _fetch_latest() -> Optional[dict]:
    """Busca o JSON da release mais recente. None em qualquer falha."""
    req = urllib.request.Request(
        _API_LATEST,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.load(resp)
    except Exception:
        logger.debug("Falha ao consultar releases do GitHub", exc_info=True)
        return None


def _pick_exe_asset(assets: list) -> Optional[dict]:
    """Escolhe o asset .exe da lista de assets da release."""
    for asset in assets or []:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and asset.get("browser_download_url"):
            return asset
    return None


def check_for_update() -> Optional[UpdateInfo]:
    """Verifica se há versão mais nova publicada. None se não houver/erro."""
    data = _fetch_latest()
    if not data:
        return None

    tag = str(data.get("tag_name") or "")
    if not tag or not is_newer(tag, __version__):
        logger.info("Sem atualização (local=%s, remoto=%s)", __version__, tag or "?")
        return None

    asset = _pick_exe_asset(data.get("assets") or [])
    download_url = asset.get("browser_download_url", "") if asset else ""
    size = int(asset.get("size", 0)) if asset else 0

    logger.info("Atualização disponível: %s (local=%s)", tag, __version__)
    return UpdateInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        download_url=download_url,
        size=size,
        notes=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or _RELEASES_PAGE),
    )


def _download(url: str, dest: str) -> bool:
    """Baixa ``url`` para ``dest``. True em sucesso."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp, open(
            dest, "wb"
        ) as out:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return True
    except Exception:
        logger.warning("Falha ao baixar atualização de %s", url, exc_info=True)
        return False


def _write_helper_bat(bat_path: str, old_exe: str, new_exe: str) -> None:
    """Escreve o .bat que espera o app sair, troca o binário e reinicia.

    Usa ``ping`` como delay (funciona sem console, ao contrário de
    ``timeout``) e faz loop até conseguir apagar o exe (que fica travado
    enquanto o app roda).
    """
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "OLD={old_exe}"\r\n'
        f'set "NEW={new_exe}"\r\n'
        ":wait\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        'del "%OLD%" >nul 2>&1\r\n'
        'if exist "%OLD%" goto wait\r\n'
        'move /y "%NEW%" "%OLD%" >nul 2>&1\r\n'
        'start "" "%OLD%"\r\n'
        'del "%~f0" >nul 2>&1\r\n'
    )
    with open(bat_path, "w", encoding="ascii", newline="") as f:
        f.write(script)


def download_and_stage(update: UpdateInfo) -> Optional[str]:
    """Baixa o novo .exe e prepara o helper. Retorna o caminho do .bat.

    Não reinicia o app — o chamador deve encerrar o processo em seguida
    para que o helper consiga substituir o binário travado.
    """
    if not is_frozen():
        logger.info("Modo dev: pulando troca de binário")
        return None
    if not update.download_url:
        logger.warning("Update sem asset .exe para baixar")
        return None

    old_exe = os.path.abspath(sys.executable)
    tmpdir = os.path.join(tempfile.gettempdir(), "like-move-update")
    os.makedirs(tmpdir, exist_ok=True)
    new_exe = os.path.join(tmpdir, "like-move-new.exe")

    if not _download(update.download_url, new_exe):
        return None

    # Verificação básica de integridade: tamanho esperado (quando conhecido)
    try:
        actual = os.path.getsize(new_exe)
    except OSError:
        actual = 0
    if actual <= 0 or (update.size and actual != update.size):
        logger.warning(
            "Download inválido (esperado=%d, obtido=%d)", update.size, actual
        )
        return None

    bat_path = os.path.join(tmpdir, "apply_update.bat")
    _write_helper_bat(bat_path, old_exe, new_exe)
    return bat_path


def launch_helper(bat_path: str) -> bool:
    """Dispara o helper .bat desanexado do processo atual."""
    try:
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=(
                _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
            ),
            close_fds=True,
        )
        return True
    except Exception:
        logger.warning("Falha ao iniciar o helper de atualização", exc_info=True)
        return False
