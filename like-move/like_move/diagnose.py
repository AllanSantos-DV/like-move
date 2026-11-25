"""Diagnóstico de bloqueio de tela: roda a leitura do Home Awake (somente leitura) e grava o relatório.

Reaproveita ``HomeAwake.psm1`` (``Get-LockSettings``, ``Get-LockDiagnosis``, ``Format-LockDiagnosis``): nada é
alterado no Windows, só lido.
"""

import os
import subprocess
import sys
from typing import Optional

CREATE_NO_WINDOW = 0x08000000


def default_psm1() -> str:
    """Caminho do ``HomeAwake.psm1`` no código-fonte ou no pacote do PyInstaller."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "home-awake", "HomeAwake.psm1")


def default_out_path() -> str:
    """Onde o relatório é gravado: a pasta de configuração do like-move."""
    from . import settings

    return os.path.join(settings.config_dir(), "diagnostico.txt")


def _quote(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def build_command(psm1: str, out_path: str) -> list[str]:
    """Linha de comando do PowerShell que gera o relatório em ``out_path``."""
    script = (
        f"$ErrorActionPreference='Stop'; Import-Module {_quote(psm1)} -Force; "
        "$s = Get-LockSettings; "
        "$r = Format-LockDiagnosis -Settings $s -Causes (Get-LockDiagnosis $s) -Identity (Get-NetworkIdentity); "
        "($r -split '\\r?\\n') | Where-Object { $_ -notmatch '^\\s+Rede de casa:' } | "
        f"Set-Content -Path {_quote(out_path)} -Encoding UTF8"
    )
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]


def run(psm1: Optional[str] = None, out_path: Optional[str] = None, timeout: int = 60) -> str:
    """Gera o relatório e devolve o caminho do arquivo.

    Levanta ``FileNotFoundError`` se o módulo não existe e ``RuntimeError`` (com o erro do PowerShell) se a
    leitura falha: nunca devolve um relatório que não foi gravado.
    """
    psm1 = psm1 or default_psm1()
    out_path = out_path or default_out_path()
    if not os.path.isfile(psm1):
        raise FileNotFoundError(f"HomeAwake.psm1 não encontrado: {psm1}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    result = subprocess.run(
        build_command(psm1, out_path), capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(f"diagnóstico falhou (código {result.returncode}): {result.stderr.strip()}")
    if not os.path.isfile(out_path):
        raise RuntimeError(f"diagnóstico terminou sem gravar {out_path}")
    return out_path
