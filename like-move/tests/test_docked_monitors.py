"""Testes de "Acordado com monitor externo": mantém acordado com dois ou mais monitores, desligado por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, detector, tray  # noqa: E402
from monitor_support import MonitorMixin, TrayMixin  # noqa: E402
from test_sister_features import state  # noqa: E402


class MonitorCountTest(unittest.TestCase):
    def test_reads_sm_cmonitors(self):
        with mock.patch.object(detector.user32, "GetSystemMetrics", return_value=2) as metrics:
            self.assertEqual(detector.get_monitor_count(), 2)
        metrics.assert_called_once_with(80)

    def test_zero_is_a_failed_read_with_the_error_code(self):
        with mock.patch.object(detector.user32, "GetSystemMetrics", return_value=0), \
                mock.patch.object(detector.ctypes, "get_last_error", return_value=5):
            with self.assertRaisesRegex(OSError, "erro 5"):
                detector.get_monitor_count()

    @unittest.skipUnless(sys.platform == "win32", "usa a API do Windows")
    def test_the_real_call_counts_at_least_one_monitor(self):
        self.assertGreaterEqual(detector.get_monitor_count(), 1)


class DecisionTest(unittest.TestCase):
    def decide(self, st=None, **kw):
        return awake.decide_keep_awake(
            st or state(), idle_seconds=0, device_disconnected=False, trusted=kw.pop("trusted", True),
            locked=kw.pop("locked", False), **kw,
        )

    def test_docked_holds_with_its_reason(self):
        d = self.decide(docked=True)
        self.assertEqual((d.wanted, d.reason), (True, awake.REASON_DOCKED))
        self.assertIn(awake.REASON_DOCKED, awake._HOLDING_REASONS)
        self.assertEqual(awake.status_text(d.reason, state(), idle_seconds=0), "Acordado agora: monitor externo")

    def test_gates_win(self):
        self.assertEqual(self.decide(docked=True, locked=True).reason, awake.REASON_LOCKED)
        self.assertEqual(self.decide(state(trusted_only=True), docked=True, trusted=False).reason, awake.REASON_UNTRUSTED)
        self.assertEqual(self.decide(state(ac_only=True), docked=True, on_ac=False).reason, awake.REASON_BATTERY)
        self.assertEqual(self.decide(docked=True, battery_low=True).reason, awake.REASON_LOW_BATTERY)

    def test_it_sits_below_the_other_triggers(self):
        self.assertEqual(self.decide(docked=True, network_busy=True).reason, awake.REASON_NETWORK)
        self.assertEqual(self.decide(docked=True, timed=True).reason, awake.REASON_TIMED)

    def test_default_decision_is_unchanged(self):
        self.assertEqual(self.decide().reason, awake.REASON_WAITING)


class MonitorDockedTest(MonitorMixin, unittest.TestCase):
    def test_off_by_default_nothing_is_read(self):
        _, mon = self.monitor()
        self.m["get_monitor_count"].return_value = 3
        mon._update()
        self.m["get_monitor_count"].assert_not_called()
        self.m["set_keep_awake"].assert_not_called()
        self.assertTrue(mon.status.startswith("Aguardando"))

    def test_two_monitors_hold_the_request(self):
        _, mon = self.monitor(docked_monitors=True)
        self.m["get_monitor_count"].return_value = 2
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)
        self.assertEqual(mon.status, "Acordado agora: monitor externo")

    def test_one_monitor_does_not_hold(self):
        _, mon = self.monitor(docked_monitors=True)
        mon._update()
        self.m["get_monitor_count"].assert_called_once_with()
        self.m["set_keep_awake"].assert_not_called()

    def test_unplugging_the_external_monitor_releases_it(self):
        _, mon = self.monitor(docked_monitors=True)
        self.m["get_monitor_count"].return_value = 2
        mon._update()
        self.m["get_monitor_count"].return_value = 1
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (False, True))

    def test_a_failed_read_is_logged_once_and_counts_as_not_docked(self):
        _, mon = self.monitor(docked_monitors=True)
        self.m["get_monitor_count"].side_effect = OSError("GetSystemMetrics devolveu 0")
        with self.assertLogs(awake.logger, "WARNING") as logs:
            mon._update()
            mon._update()
        self.assertEqual(len(logs.records), 1)
        self.m["set_keep_awake"].assert_not_called()

    def test_the_failure_is_logged_again_after_a_good_read(self):
        _, mon = self.monitor(docked_monitors=True)
        self.m["get_monitor_count"].side_effect = [OSError("x"), 1, OSError("y")]
        with self.assertLogs(awake.logger, "WARNING") as logs:
            for _ in range(3):
                mon._update()
        self.assertEqual(len(logs.records), 2)

    def test_locked_screen_wins(self):
        _, mon = self.monitor(docked_monitors=True)
        self.m["get_monitor_count"].return_value = 2
        self.m["is_screen_locked"].return_value = True
        mon._update()
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: tela bloqueada")

    def test_untrusted_network_wins(self):
        _, mon = self.monitor(docked_monitors=True, trusted_only=True)
        self.m["get_monitor_count"].return_value = 2
        self.m["is_on_trusted_network"].return_value = False
        mon._update()
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: fora de rede confiável")

    def test_ac_only_on_battery_wins(self):
        _, mon = self.monitor(docked_monitors=True, ac_only=True)
        self.m["get_monitor_count"].return_value = 2
        self.m["is_on_ac_power"].return_value = False
        mon._update()
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: na bateria")


class ConfigTest(unittest.TestCase):
    def test_off_by_default_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertFalse(st.docked_monitors)
            st.docked_monitors = True
            st.save()
            self.assertTrue(config.JigglerState().docked_monitors)


class TrayDockedMenuTest(TrayMixin, unittest.TestCase):
    def test_entry_exists_and_is_unchecked_by_default(self):
        item = self.top()["Acordado com monitor externo"]
        self.assertFalse(item.checked)

    def test_toggle_persists_across_a_reload(self):
        self.app._on_toggle_docked_monitors(None, None)
        self.assertTrue(self.top()["Acordado com monitor externo"].checked)
        self.assertTrue(tray.JigglerState().docked_monitors)
        self.app._on_toggle_docked_monitors(None, None)
        self.assertFalse(tray.JigglerState().docked_monitors)


if __name__ == "__main__":
    unittest.main()
