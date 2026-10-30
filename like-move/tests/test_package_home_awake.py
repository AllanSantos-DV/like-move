"""O zip do Home Awake leva só os scripts e o LEIA-ME, igual no build local e na CI.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import subprocess
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = {
    "1-diagnosticar.cmd",
    "2-cadastrar-rede-de-casa.cmd",
    "3-iniciar.cmd",
    "4-parar.cmd",
    "5-verificar.cmd",
    "home-awake.ps1",
    "HomeAwake.psm1",
    "LEIA-ME.txt",
}


class PackageHomeAwake(unittest.TestCase):
    def test_zip_tem_so_os_scripts_e_o_leia_me(self):
        with tempfile.TemporaryDirectory() as out:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 os.path.join(ROOT, "package-home-awake.ps1"), "-OutDir", out],
                check=True, capture_output=True, text=True,
            )
            with zipfile.ZipFile(os.path.join(out, "home-awake.zip")) as z:
                names = set(z.namelist())
        # cadastro.txt, diagnostico.txt (dados de quem rodou aqui) e tests/ não podem aparecer
        self.assertEqual(names, EXPECTED)


if __name__ == "__main__":
    unittest.main()
