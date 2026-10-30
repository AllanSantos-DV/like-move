"""O que vai para o site público (GitHub Pages) é só página e mídia do produto.

O pages.yml publica like-move/site/ inteiro. Metadados de gerador (voz, medição) e qualquer
quadro narrado interno ficam fora: este teste só deixa versionar tipos de arquivo de página e mídia.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
ALLOWED = {".html", ".png", ".jpg", ".mp4", ".vtt"}


def tracked_site_files():
    out = subprocess.run(
        ["git", "-C", REPO, "ls-files", "like-move/site"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


class SiteFiles(unittest.TestCase):
    def test_ha_arquivos_do_site_versionados(self):
        self.assertIn("like-move/site/index.html", tracked_site_files())

    def test_site_versiona_so_pagina_e_midia(self):
        extras = [p for p in tracked_site_files() if os.path.splitext(p)[1].lower() not in ALLOWED]
        self.assertEqual(extras, [], "arquivos versionados no site fora de pagina/midia (iriam para o Pages)")


if __name__ == "__main__":
    unittest.main()
