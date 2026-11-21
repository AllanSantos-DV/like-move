"""A autoria do mantenedor consta no pacote npm, na licença, no README e nos metadados do exe.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
AUTHOR = "Allan Santos"


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


class Authorship(unittest.TestCase):
    def test_pacote_npm_tem_o_autor(self):
        author = json.loads(read(ROOT, "npm", "package.json"))["author"]
        self.assertEqual(author["name"], AUTHOR)

    def test_licenca_tem_o_copyright_do_autor(self):
        self.assertRegex(read(REPO, "LICENSE"), rf"Copyright \(c\) \d{{4}} {AUTHOR}\b")

    def test_readme_credita_o_autor(self):
        self.assertIn(f"© {AUTHOR}", read(ROOT, "README.md"))

    def test_exe_tem_o_autor_como_empresa(self):
        self.assertRegex(read(ROOT, "like-move.spec"), rf"StringStruct\('CompanyName', '{AUTHOR}'\)")

    def test_nada_de_email_nem_caminho_local_nos_manifestos(self):
        for text in (read(ROOT, "npm", "package.json"), read(REPO, "LICENSE"), read(ROOT, "like-move.spec")):
            self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+|C:\\Users\\", text))


if __name__ == "__main__":
    unittest.main()
