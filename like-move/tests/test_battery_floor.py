"""Testes da opção "Bateria mínima": solta o pedido na bateria abaixo de X%, desligada por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, detector, tray  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402
from test_sister_features import state  # noqa: E402


class BatteryPercentTest(unittest.TestCase):
    def read(self, raw):
        with mock.patch.object(detector, "_power_status", return_value=SimpleNamespace(BatteryLifePercent=raw)):
            return detector.battery_percent()

    def test_reports_the_charge(self):
        self.assertEqual(self.read(42), 42)
        self.assertEqual(self.read(100), 100)

    def test_unknown_charge_is_none(self):
        self.assertIsNone(self.read(255))

    def test_a_failed_call_is_an_error(self):
        with mock.patch.object(detector.kernel32, "GetSystemPowerStatus", return_value=0):
            with self.assertRaises(OSError):
                detector.battery_percent()


class IsBatteryLowTest(unittest.TestCase):
    def test_off_when_the_floor_is_zero(self):
        self.assertFalse(awake.is_battery_low(1, 0, was_low=False))

    def test_low_only_below_the_floor(self):
        self.assertTrue(awake.is_battery_low(19, 20, was_low=False))
        self.assertFalse(awake.is_battery_low(20, 20, was_low=False))

    def test_unknown_charge_is_not_low(self):
        self.assertFalse(awake.is_battery_low(None, 20, was_low=False))
        self.assertFalse(awake.is_battery_low(None, 20, was_low=True))

    def test_once_low_it_resumes_only_a_margin_above_the_floor(self):
        edge = 20 + awake.BATTERY_RESUME_MARGIN
        self.assertTrue(awake.is_battery_low(20, 20, was_low=True))
        self.assertTrue(awake.is_battery_low(edge - 1, 20, was_low=True))
        self.assertFalse(awake.is_battery_low(edge, 20, was_low=True))


class DecisionTest(unittest.TestCase):
    def decide(self, st=None, **kw):
        return awake.decide_keep_awake(
            st or state(trigger_mode=TriggerMode.ALWAYS), idle_seconds=0, device_disconnected=False,
            trusted=True, locked=kw.pop("locked", False), **kw,
        )

    def test_low_battery_releases_with_its_own_reason(self):
        d = self.decide(battery_low=True)
        self.assertEqual((d.wanted, d.reason), (False, awake.REASON_LOW_BATTERY))
        self.assertNotIn(awake.REASON_LOW_BATTERY, awake._HOLDING_REASONS)

    def test_it_also_overrides_the_triggers(self):
        self.assertEqual(self.decide(battery_low=True, timed=True).reason, awake.REASON_LOW_BATTERY)
        self.assertEqual(self.decide(battery_low=True, process_running=True).reason, awake.REASON_LOW_BATTERY)
        self.assertEqual(self.decide(battery_low=True, cpu_busy=True).reason, awake.REASON_LOW_BATTERY)

    def test_the_other_gates_keep_precedence(self):
        self.assertEqual(self.decide(battery_low=True, locked=True).reason, awake.REASON_LOCKED)
        self.assertEqual(self.decide(state(enabled=False), battery_low=True).reason, awake.REASON_DISABLED)
        st = state(ac_only=True, trigger_mode=TriggerMode.ALWAYS)
        self.assertEqual(self.decide(st, on_ac=False, battery_low=True).reason, awake.REASON_BATTERY)

    def test_default_decision_is_unchanged(self):
        self.assertEqual(self.decide().reason, awake.REASON_ALWAYS)

    def test_status_text_names_the_reason(self):
        self.assertEqual(awake.status_text(awake.REASON_LOW_BATTERY, state(), idle_seconds=0), "Parado: bateria baixa")


class MonitorBatteryTest(unittest.TestCase):
    def setUp(self):
        patches = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "is_on_ac_power": mock.patch.object(awake, "is_on_ac_power", return_value=False),
            "battery_percent": mock.patch.object(awake, "battery_percent", return_value=50),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "get_execution_state": mock.patch.object(
                awake, "get_execution_state", return_value=awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED
            ),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        st = state(trigger_mode=TriggerMode.ALWAYS, **kw)
        mon = awake.MonitorThread(st)
        mon.notifier = mock.Mock()
        return st, mon

    def test_off_by_default_nothing_is_read(self):
        _, mon = self.monitor()
        self.m["battery_percent"].return_value = 1
        mon._update()
        self.m["battery_percent"].assert_not_called()
        self.m["is_on_ac_power"].assert_not_called()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_below_the_floor_on_battery_releases_the_request(self):
        _, mon = self.monitor(battery_floor=20)
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)
        self.m["battery_percent"].return_value = 19
        mon._update()
        self.m["set_keep_awake"].assert_called_with(False, True)
        self.assertEqual(mon.status, "Parado: bateria baixa")

    def test_at_the_floor_it_keeps_holding(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["battery_percent"].return_value = 20
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_on_ac_it_never_applies_and_the_charge_is_not_read(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["is_on_ac_power"].return_value = True
        self.m["battery_percent"].return_value = 1
        mon._update()
        self.m["battery_percent"].assert_not_called()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_plugging_in_resumes_at_once(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["battery_percent"].return_value = 10
        mon._update()
        self.m["is_on_ac_power"].return_value = True
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (True, True))

    def test_a_jittering_reading_does_not_flap(self):
        _, mon = self.monitor(battery_floor=20)
        for percent in (21, 19, 20, 21, 22, 19):
            self.m["battery_percent"].return_value = percent
            mon._update()
        self.assertEqual([c.args for c in self.m["set_keep_awake"].call_args_list], [(True, True), (False, True)])

    def test_resumes_a_margin_above_the_floor(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["battery_percent"].return_value = 19
        mon._update()
        self.m["battery_percent"].return_value = 20 + awake.BATTERY_RESUME_MARGIN
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (True, True))

    def test_unknown_charge_counts_as_not_low(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["battery_percent"].return_value = None
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_a_failed_read_is_logged_once_and_counts_as_not_low(self):
        _, mon = self.monitor(battery_floor=20)
        self.m["battery_percent"].side_effect = OSError("sem bateria")
        with self.assertLogs(awake.logger, "WARNING") as logs:
            mon._update()
            mon._update()
        self.assertEqual(len([r for r in logs.records if "bateria" in r.getMessage()]), 1)
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_a_deadline_does_not_override_a_low_battery(self):
        _, mon = self.monitor(battery_floor=20, awake_until=1000.0)
        self.m["battery_percent"].return_value = 5
        with mock.patch.object(awake.time, "time", return_value=500.0):
            mon._update()
        self.m["set_keep_awake"].assert_not_called()

    def test_changing_the_floor_while_holding_takes_effect(self):
        st, mon = self.monitor(battery_floor=10)
        self.m["battery_percent"].return_value = 15
        mon._update()
        st.battery_floor = 20
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (False, True))


class ConfigTest(unittest.TestCase):
    def load_with(self, payload):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            d = os.path.join(tmp, "like-move")
            os.makedirs(d)
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                fh.write(payload)
            return config.JigglerState()

    def test_off_by_default_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertEqual(st.battery_floor, 0)
            st.battery_floor = 20
            st.save()
            self.assertEqual(config.JigglerState().battery_floor, 20)

    def test_invalid_values_fall_back_with_a_warning(self):
        for payload in ('{"battery_floor": "baixa"}', '{"battery_floor": 250}', '{"battery_floor": -1}', '{"battery_floor": true}'):
            with self.subTest(payload), self.assertLogs(config.logger, "WARNING"):
                self.assertEqual(self.load_with(payload).battery_floor, 0)


class TrayBatteryMenuTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = tray.TrayApp()
        self.app._icon = mock.Mock()
        self.app._monitor = SimpleNamespace(status="x", notifier=None)

    def items(self):
        top = {(i.text(i) if callable(i.text) else i.text): i for i in self.app._build_menu().items}
        return top["Bateria mínima"].submenu.items

    def test_options_are_radio_items_with_off_checked_by_default(self):
        items = self.items()
        self.assertEqual([i.text for i in items], ["Desligado", "Abaixo de 10%", "Abaixo de 20%", "Abaixo de 30%"])
        self.assertTrue(all(i.radio for i in items))
        self.assertEqual([bool(i.checked) for i in items], [True, False, False, False])

    def test_choosing_a_floor_persists_and_moves_the_check(self):
        self.app._on_set_battery_floor(20)(None, None)
        self.assertEqual(self.app._state.battery_floor, 20)
        self.assertEqual(tray.JigglerState().battery_floor, 20)
        self.assertEqual([bool(i.checked) for i in self.items()], [False, False, True, False])
        self.app._on_set_battery_floor(0)(None, None)
        self.assertEqual(tray.JigglerState().battery_floor, 0)


if __name__ == "__main__":
    unittest.main()
