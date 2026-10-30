"""Os scripts PowerShell do projeto com texto fora do ASCII precisam de BOM UTF-8.

O Windows PowerShell 5.1 lê arquivo sem BOM na página de código ANSI do sistema (1252 numa instalação
comum). Em 1252 o travessão "—" vira "â€”" e o último caractere é uma aspa tipográfica, que o PowerShell
trata como aspa de verdade: a string fecha no meio e o módulo nem carrega.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"dist", "build", "__pycache__", ".token-guard", ".git"}
BOM = b"\xef\xbb\xbf"


def powershell_scripts():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.lower().endswith((".ps1", ".psm1")):
                yield os.path.join(folder, name)


class HomeAwakeEncoding(unittest.TestCase):
    def test_encontra_os_scripts_do_projeto(self):
        self.assertTrue(list(powershell_scripts()), "nenhum .ps1/.psm1 encontrado")

    def test_script_com_texto_fora_do_ascii_tem_bom(self):
        for path in powershell_scripts():
            with open(path, "rb") as f:
                data = f.read()
            if any(b > 127 for b in data):
                self.assertTrue(
                    data.startswith(BOM),
                    f"{os.path.relpath(path, ROOT)} tem texto fora do ASCII e não começa com BOM UTF-8",
                )


if __name__ == "__main__":
    unittest.main()
