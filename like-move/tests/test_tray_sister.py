"""Testes do menu da bandeja para as funções irmãs (prazo, tomada, bloqueio, avisos, diagnóstico).

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import datetime as dt
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import tray  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402


def labels(menu):
    out = []
    for item in menu.items:
        text = item.text
        out.append(text(item) if callable(text) else text)
    return out


class TrayFeaturesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = tray.TrayApp()
        self.app._icon = mock.Mock()
        self.app._monitor = SimpleNamespace(status="Aguardando: faltam 30s", notifier=None)

    def top_items(self):
        return {(i.text(i) if callable(i.text) else i.text): i for i in self.app._build_menu().items}

    def test_status_line_is_first_and_disabled_and_dynamic(self):
        first = self.app._build_menu().items[0]
        self.assertFalse(first.enabled)
        self.assertEqual(first.text, "Aguardando: faltam 30s")
        self.app._monitor.status = "Acordado agora: KVM"
        self.assertEqual(first.text, "Acordado agora: KVM")

    def test_status_line_before_the_monitor_exists(self):
        self.app._monitor = None
        first = self.app._build_menu().items[0]
        self.assertEqual(first.text, "like-move")

    def test_new_toggles_are_off_by_default_in_the_menu(self):
        items = self.top_items()
        for name in ("Só na tomada", "Avisar nas mudanças"):
            self.assertIn(name, items)
            self.assertFalse(items[name].checked)

    def test_menu_keeps_the_existing_entries(self):
        names = set(self.top_items())
        for name in ("Ativo", "Modo", "Threshold", "Redes confiáveis", "Iniciar com Windows", "Sobre", "Sair"):
            self.assertIn(name, names)

    def test_timer_by_minutes_sets_deadline_enables_and_saves(self):
        self.app._state.enabled = False
        fixed = dt.datetime(2026, 11, 25, 15, 0, 0)
        with mock.patch.object(tray, "_now", return_value=fixed):
            self.app._on_set_timer_minutes(60)(self.app._icon, None)
        self.assertEqual(self.app._state.awake_until, fixed.timestamp() + 3600)
        self.assertTrue(self.app._state.enabled)
        self.assertEqual(tray.JigglerState().awake_until, fixed.timestamp() + 3600)
        self.app._icon.notify.assert_called()

    def test_timer_until_clock_time(self):
        fixed = dt.datetime(2026, 11, 25, 15, 0, 0)
        with mock.patch.object(tray, "_now", return_value=fixed):
            self.app._on_set_timer_until(18, 0)(self.app._icon, None)
        self.assertEqual(self.app._state.awake_until, dt.datetime(2026, 11, 25, 18, 0).timestamp())

    def test_cancel_timer_clears_and_saves(self):
        self.app._state.awake_until = 9e12
        self.app._on_cancel_timer(self.app._icon, None)
        self.assertEqual(self.app._state.awake_until, 0.0)
        self.assertEqual(tray.JigglerState().awake_until, 0.0)

    def test_timer_entries_show_only_while_active(self):
        timer_menu = self.top_items()["Manter acordado por…"]
        sub = {(i.text(i) if callable(i.text) else i.text): i for i in timer_menu.submenu.items}
        self.assertFalse(sub["Cancelar prazo"].visible)
        self.app._state.awake_until = 9e12
        self.assertTrue(sub["Cancelar prazo"].visible)

    def test_toggles_flip_and_persist(self):
        for handler, field in (
            (self.app._on_toggle_ac_only, "ac_only"),
            (self.app._on_toggle_lock_on_untrusted, "lock_on_untrusted"),
            (self.app._on_toggle_notify_transitions, "notify_transitions"),
        ):
            handler(self.app._icon, None)
            self.assertTrue(getattr(self.app._state, field), field)
            self.assertTrue(getattr(tray.JigglerState(), field), field)

    def test_lock_toggle_lives_in_the_trusted_networks_submenu(self):
        sub = labels(self.top_items()["Redes confiáveis"].submenu)
        self.assertIn("Bloquear a tela ao sair da rede", sub)

    def test_notifier_is_wired_to_the_icon_when_setting_up(self):
        icon = mock.Mock()
        with mock.patch.object(tray, "MonitorThread") as monitor_cls, \
                mock.patch.object(self.app, "_ensure_device_monitor"), \
                mock.patch.object(self.app, "_run_update_check"):
            self.app._setup(icon)
        monitor_cls.return_value.notifier("oi")
        icon.notify.assert_any_call("oi", "like-move")

    def test_diagnose_opens_the_report_and_notifies(self):
        done = threading.Event()
        opened = []
        self.app._open_file = lambda path: (opened.append(path), done.set())
        with mock.patch.object(tray.diagnose, "run", return_value=r"C:\x\diagnostico.txt"):
            self.app._on_diagnose(self.app._icon, None)
            self.assertTrue(done.wait(5))
        self.assertEqual(opened, [r"C:\x\diagnostico.txt"])

    def test_diagnose_failure_is_reported_not_swallowed(self):
        done = threading.Event()
        self.app._icon.notify.side_effect = lambda *a, **k: done.set()
        with mock.patch.object(tray.diagnose, "run", side_effect=RuntimeError("boom")):
            with self.assertLogs(tray.logger, level="ERROR"):
                self.app._on_diagnose(self.app._icon, None)
                self.assertTrue(done.wait(5))
        message = self.app._icon.notify.call_args.args[0]
        self.assertIn("boom", message)


if __name__ == "__main__":
    unittest.main()
