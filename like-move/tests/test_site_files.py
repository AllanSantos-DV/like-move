"""O que vai para o site público (GitHub Pages) é só página e mídia do produto.

O pages.py publica os arquivos versionados de like-move/site. Metadados de gerador (voz, medição) e qualquer
quadro narrado interno ficam fora: a mesma guarda do pages.py roda aqui sobre o que está versionado.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pages  # noqa: E402


class SiteFiles(unittest.TestCase):
    def test_ha_arquivos_do_site_versionados(self):
        self.assertIn("like-move/site/index.html", pages.site_files())

    def test_site_versionado_so_tem_conteudo_publico(self):
        self.assertEqual(pages.public_findings(pages.REPO, pages.site_files()), [])


if __name__ == "__main__":
    unittest.main()
