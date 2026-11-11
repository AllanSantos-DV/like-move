"""Testes do like-move: "Iniciar com Windows" relata o estado real e o .exe sem console grava log em arquivo.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import importlib.machinery
import importlib.util
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from like_move import startup  # noqa: E402


def load_main():
    loader = importlib.machinery.SourceFileLoader("like_move_main", os.path.join(ROOT, "main.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ToggleStartupTest(unittest.TestCase):
    def test_registro_que_nao_gravou_relata_desligado(self):
        with mock.patch.object(startup, "is_startup_enabled", side_effect=[False, False]), \
                mock.patch.object(startup, "enable_startup") as enable:
            self.assertFalse(startup.toggle_startup())
        enable.assert_called_once()

    def test_registro_gravado_relata_ligado(self):
        with mock.patch.object(startup, "is_startup_enabled", side_effect=[False, True]), \
                mock.patch.object(startup, "enable_startup"):
            self.assertTrue(startup.toggle_startup())

    def test_remocao_relata_desligado(self):
        with mock.patch.object(startup, "is_startup_enabled", side_effect=[True, False]), \
                mock.patch.object(startup, "disable_startup") as disable:
            self.assertFalse(startup.toggle_startup())
        disable.assert_called_once()


class ConfigureLoggingTest(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        self.saved = (root.handlers[:], root.level)
        root.handlers = []
        self.main = load_main()

    def tearDown(self):
        root = logging.getLogger()
        for h in root.handlers:
            h.close()
        root.handlers, level = self.saved
        root.setLevel(level)

    def test_sem_console_grava_em_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = os.path.join(tmp, "like-move")
            with mock.patch.object(sys, "stderr", None):
                self.main.configure_logging(log_dir)
            logging.getLogger("like-move").info("linha de teste")
            for h in logging.getLogger().handlers:
                h.close()
            with open(os.path.join(log_dir, self.main.LOG_FILENAME), encoding="utf-8") as f:
                self.assertIn("linha de teste", f.read())

    def test_com_console_nao_cria_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.main.configure_logging(tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, self.main.LOG_FILENAME)))
            self.assertIsInstance(logging.getLogger().handlers[0], logging.StreamHandler)


if __name__ == "__main__":
    unittest.main()
