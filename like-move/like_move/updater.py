"""Auto-update via GitHub Releases (sem dependências externas).

Fluxo:
    GET https://api.github.com/repos/<owner>/<repo>/releases/latest
    → compara ``tag_name`` (ex.: "v1.2.0") com a versão local (VERSION)
    → se houver versão maior, baixa o asset ``like-move-win64.zip``, extrai numa
      pasta irmã ``like-move-<versão>`` e abre o novo ``like-move.exe``.

O app atual só encerra; nenhum script auxiliar troca arquivos em uso. A nova
versão, ao abrir, remove da pasta antiga apenas ``like-move.exe`` e ``_internal``
(e a pasta, se ficar vazia) e reaponta "Iniciar com Windows" para si.

Só aplica quando rodando "congelado" (``sys.frozen`` do PyInstaller). Em modo
desenvolvimento (Python), apenas informa e abre a página de releases.
Usa somente a stdlib (``urllib``/``zipfile``).
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from typing import NamedTuple, Optional

from . import __version__

logger = logging.getLogger(__name__)

# Repositório de releases (owner/repo)
REPO: str = "AllanSantos-DV/like-move"
ASSET_NAME: str = "like-move-win64.zip"
EXE_NAME: str = "like-move.exe"
REPLACED_ARG: str = "--replaced"

_API_LATEST: str = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASES_PAGE: str = f"https://github.com/{REPO}/releases/latest"
_USER_AGENT: str = "like-move-updater"
_HTTP_TIMEOUT: float = 12.0


class UpdateInfo(NamedTuple):
    """Metadados de uma atualização disponível."""

    version: str            # ex.: "1.2.0"
    tag: str                # ex.: "v1.2.0"
    download_url: str       # URL do asset .zip
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


def _pick_asset(assets: list) -> Optional[dict]:
    """Escolhe o asset ``like-move-win64.zip`` da lista de assets da release."""
    for asset in assets or []:
        if str(asset.get("name", "")).lower() == ASSET_NAME and asset.get("browser_download_url"):
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

    asset = _pick_asset(data.get("assets") or [])
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




def stage_update(zip_path: str, install_dir: str, version: str) -> str:
    """Extrai o zip numa pasta irmã de ``install_dir`` e devolve o caminho do novo exe.

    Levanta ``ValueError`` se o zip não trouxer ``like-move.exe``.
    """
    parent = os.path.dirname(os.path.abspath(install_dir))
    target = os.path.join(parent, f"like-move-{version}")
    suffix = 1
    while os.path.exists(target):
        suffix += 1
        target = os.path.join(parent, f"like-move-{version}-{suffix}")

    with tempfile.TemporaryDirectory(prefix="like-move-update-") as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)  # extractall descarta caminhos absolutos e ".."
        # O zip da release traz uma pasta raiz (like-move/); aceita também o conteúdo solto.
        entries = os.listdir(tmp)
        root = os.path.join(tmp, entries[0]) if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])) else tmp
        if not os.path.isfile(os.path.join(root, EXE_NAME)):
            raise ValueError(f"{ASSET_NAME} sem {EXE_NAME}")
        shutil.copytree(root, target)
    return os.path.join(target, EXE_NAME)


def download_and_stage(update: UpdateInfo) -> Optional[str]:
    """Baixa a nova versão e a deixa pronta ao lado da atual. Retorna o novo exe."""
    if not is_frozen():
        logger.info("Modo dev: pulando troca de versão")
        return None
    if not update.download_url:
        logger.warning("Release sem o asset %s", ASSET_NAME)
        return None

    with tempfile.TemporaryDirectory(prefix="like-move-dl-") as tmp:
        zip_path = os.path.join(tmp, ASSET_NAME)
        if not _download(update.download_url, zip_path):
            return None
        actual = os.path.getsize(zip_path)
        if actual <= 0 or (update.size and actual != update.size):
            logger.warning("Download inválido (esperado=%d, obtido=%d)", update.size, actual)
            return None
        try:
            return stage_update(zip_path, os.path.dirname(sys.executable), update.version)
        except (OSError, ValueError, zipfile.BadZipFile):
            logger.warning("Falha ao preparar a atualização", exc_info=True)
            return None


def launch_new(new_exe: str) -> bool:
    """Abre a nova versão, avisando qual pasta ela substitui."""
    try:
        subprocess.Popen([new_exe, REPLACED_ARG, os.path.dirname(sys.executable)], close_fds=True)
        return True
    except OSError:
        logger.warning("Falha ao abrir a nova versão", exc_info=True)
        return False


def cleanup_previous(old_dir: str, timeout: float = 15.0) -> bool:
    """Remove da pasta antiga só os arquivos do like-move, esperando a versão antiga fechar.

    Nunca apaga outros arquivos: se a pasta tiver mais coisas, ela fica.
    """
    old_exe = os.path.join(old_dir, EXE_NAME)
    deadline = time.monotonic() + timeout
    while os.path.exists(old_exe):
        try:
            os.remove(old_exe)
        except PermissionError:  # versão antiga ainda fechando
            if time.monotonic() > deadline:
                logger.warning("Versão antiga não fechou; pasta mantida: %s", old_dir)
                return False
            time.sleep(0.5)
        except FileNotFoundError:
            break
    shutil.rmtree(os.path.join(old_dir, "_internal"), ignore_errors=True)
    try:
        os.rmdir(old_dir)
    except OSError:
        pass  # pasta tem outros arquivos do usuário: fica
    logger.info("Versão anterior removida de %s", old_dir)
    return True
