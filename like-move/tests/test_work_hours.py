"""Testes do "Horário de trabalho": janela por dias e horas que mantém o PC acordado, desligada por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, timer, tray  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402
from monitor_support import MonitorMixin, TrayMixin  # noqa: E402
from test_sister_features import state  # noqa: E402

WEEKDAYS = [0, 1, 2, 3, 4]


def hours(**kw):
    base = {"enabled": True, "days": WEEKDAYS, "start": "09:00", "end": "18:00"}
    base.update(kw)
    return base


def at(day, hh, mm=0):
    """Instante local na semana de segunda 2026-11-23 (day 0) a domingo 2026-11-29 (day 6)."""
    return dt.datetime(2026, 11, 23 + day, hh, mm)


class InWorkHoursTest(unittest.TestCase):
    def test_inside_and_outside_the_window(self):
        self.assertTrue(timer.in_work_hours(hours(), at(2, 12)))
        self.assertFalse(timer.in_work_hours(hours(), at(2, 8, 59)))
        self.assertFalse(timer.in_work_hours(hours(), at(2, 20)))

    def test_start_is_inclusive_and_end_is_exclusive(self):
        self.assertTrue(timer.in_work_hours(hours(), at(2, 9, 0)))
        self.assertTrue(timer.in_work_hours(hours(), at(2, 17, 59)))
        self.assertFalse(timer.in_work_hours(hours(), at(2, 18, 0)))

    def test_only_the_chosen_weekdays(self):
        for day in range(5):
            self.assertTrue(timer.in_work_hours(hours(), at(day, 12)), day)
        self.assertFalse(timer.in_work_hours(hours(), at(5, 12)))
        self.assertFalse(timer.in_work_hours(hours(), at(6, 12)))

    def test_disabled_is_never_inside(self):
        self.assertFalse(timer.in_work_hours(hours(enabled=False), at(2, 12)))

    def test_no_days_is_never_inside(self):
        self.assertFalse(timer.in_work_hours(hours(days=[]), at(2, 12)))

    def test_window_crossing_midnight_belongs_to_the_day_it_started(self):
        night = hours(days=[4], start="22:00", end="06:00")  # só a sexta
        self.assertFalse(timer.in_work_hours(night, at(4, 21, 59)))
        self.assertTrue(timer.in_work_hours(night, at(4, 22, 0)))
        self.assertTrue(timer.in_work_hours(night, at(4, 23, 59)))
        self.assertTrue(timer.in_work_hours(night, at(5, 0, 0)))
        self.assertTrue(timer.in_work_hours(night, at(5, 5, 59)))
        self.assertFalse(timer.in_work_hours(night, at(5, 6, 0)))
        self.assertFalse(timer.in_work_hours(night, at(5, 22, 0)))
        self.assertFalse(timer.in_work_hours(night, at(4, 3, 0)))

    def test_midnight_crossing_wraps_from_sunday_to_monday(self):
        night = hours(days=[6], start="22:00", end="06:00")
        self.assertTrue(timer.in_work_hours(night, at(0, 2)))
        self.assertFalse(timer.in_work_hours(night, at(1, 2)))

    def test_equal_start_and_end_is_a_full_day_from_the_start(self):
        full = hours(days=[2], start="09:00", end="09:00")
        self.assertTrue(timer.in_work_hours(full, at(2, 9)))
        self.assertTrue(timer.in_work_hours(full, at(3, 8, 59)))
        self.assertFalse(timer.in_work_hours(full, at(3, 9)))
        self.assertFalse(timer.in_work_hours(full, at(2, 8, 59)))

    def test_malformed_configuration_is_never_inside(self):
        bad = [
            None, "09:00-18:00", [], {}, hours(enabled="yes"), hours(days="seg"), hours(days=[7]), hours(days=[-1]),
            hours(days=[True]), hours(days=["1"]), hours(start="9:00"), hours(start="24:00"), hours(end="18:60"),
            hours(start=900), hours(end=None),
        ]
        for cfg in bad:
            with self.subTest(cfg=cfg):
                self.assertFalse(timer.in_work_hours(cfg, at(2, 12)))


class ParseWorkHoursTest(unittest.TestCase):
    def test_days_are_sorted_and_deduplicated(self):
        self.assertEqual(timer.parse_work_hours(hours(days=[4, 0, 0, 2]))["days"], [0, 2, 4])

    def test_malformed_is_none(self):
        self.assertIsNone(timer.parse_work_hours(hours(start="25:00")))


class DecisionTest(unittest.TestCase):
    def decide(self, st=None, **kw):
        return awake.decide_keep_awake(
            st or state(), idle_seconds=0, device_disconnected=False, trusted=kw.pop("trusted", True),
            locked=kw.pop("locked", False), **kw,
        )

    def test_scheduled_holds_with_its_reason(self):
        d = self.decide(scheduled=True)
        self.assertEqual((d.wanted, d.reason), (True, awake.REASON_SCHEDULED))
        self.assertIn(awake.REASON_SCHEDULED, awake._HOLDING_REASONS)
        self.assertEqual(awake.status_text(d.reason, state(), idle_seconds=0), "Acordado agora: horário")

    def test_gates_win(self):
        self.assertEqual(self.decide(scheduled=True, locked=True).reason, awake.REASON_LOCKED)
        self.assertEqual(self.decide(state(trusted_only=True), scheduled=True, trusted=False).reason, awake.REASON_UNTRUSTED)
        self.assertEqual(self.decide(state(ac_only=True), scheduled=True, on_ac=False).reason, awake.REASON_BATTERY)
        self.assertEqual(self.decide(scheduled=True, battery_low=True).reason, awake.REASON_LOW_BATTERY)
        self.assertEqual(self.decide(state(enabled=False), scheduled=True).reason, awake.REASON_DISABLED)

    def test_the_deadline_keeps_the_slot_above_it(self):
        self.assertEqual(self.decide(scheduled=True, timed=True).reason, awake.REASON_TIMED)

    def test_it_sits_above_the_other_triggers(self):
        d = self.decide(scheduled=True, process_running=True, cpu_busy=True)
        self.assertEqual(d.reason, awake.REASON_SCHEDULED)

    def test_default_decision_is_unchanged(self):
        self.assertEqual(self.decide().reason, awake.REASON_WAITING)


class MonitorWorkHoursTest(MonitorMixin, unittest.TestCase):
    INSIDE = at(2, 10).timestamp()
    OUTSIDE = at(2, 20).timestamp()

    def update(self, mon, when):
        with mock.patch.object(awake.time, "time", return_value=when):
            mon._update()

    def test_off_by_default_nothing_is_evaluated(self):
        _, mon = self.monitor()
        with mock.patch.object(awake.timer, "in_work_hours") as in_hours:
            self.update(mon, self.INSIDE)
        in_hours.assert_not_called()
        self.m["set_keep_awake"].assert_not_called()
        self.assertTrue(mon.status.startswith("Aguardando"))

    def test_inside_the_window_holds_the_request(self):
        _, mon = self.monitor(work_hours=hours())
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_called_once_with(True, True)
        self.assertEqual(mon.status, "Acordado agora: horário")

    def test_leaving_the_window_releases_it(self):
        _, mon = self.monitor(work_hours=hours())
        self.update(mon, self.INSIDE)
        self.update(mon, self.OUTSIDE)
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (False, True))
        self.assertTrue(mon.status.startswith("Aguardando"))

    def test_a_weekend_day_does_not_hold(self):
        _, mon = self.monitor(work_hours=hours())
        self.update(mon, at(5, 10).timestamp())
        self.m["set_keep_awake"].assert_not_called()

    def test_turning_it_on_while_running_takes_effect(self):
        st, mon = self.monitor()
        self.update(mon, self.INSIDE)
        st.work_hours = hours()
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_locked_screen_wins(self):
        _, mon = self.monitor(work_hours=hours())
        self.m["is_screen_locked"].return_value = True
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: tela bloqueada")

    def test_untrusted_network_wins(self):
        _, mon = self.monitor(work_hours=hours(), trusted_only=True)
        self.m["is_on_trusted_network"].return_value = False
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: fora de rede confiável")

    def test_ac_only_on_battery_wins(self):
        _, mon = self.monitor(work_hours=hours(), ac_only=True)
        self.m["is_on_ac_power"].return_value = False
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: na bateria")

    def test_low_battery_wins(self):
        _, mon = self.monitor(work_hours=hours(), battery_floor=20)
        self.m["is_on_ac_power"].return_value = False
        self.m["battery_percent"].return_value = 10
        self.update(mon, self.INSIDE)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: bateria baixa")


class ConfigTest(unittest.TestCase):
    def load_with(self, payload):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            d = os.path.join(tmp, "like-move")
            os.makedirs(d)
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                fh.write(payload)
            return config.JigglerState()

    def test_off_by_default_with_the_proposed_hours(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            self.assertEqual(
                config.JigglerState().work_hours,
                {"enabled": False, "days": WEEKDAYS, "start": "09:00", "end": "18:00"},
            )

    def test_defaults_are_not_shared_between_states(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            first = config.JigglerState()
            first.work_hours["days"].append(6)
            self.assertEqual(config.JigglerState().work_hours["days"], WEEKDAYS)

    def test_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            st.work_hours = hours(days=[0, 2], start="22:00", end="06:00")
            st.save()
            self.assertEqual(config.JigglerState().work_hours, hours(days=[0, 2], start="22:00", end="06:00"))

    def test_malformed_values_fall_back_to_disabled_with_one_warning(self):
        payloads = [
            '{"work_hours": "sempre"}', '{"work_hours": {"enabled": true, "days": "seg", "start": "09:00", "end": "18:00"}}',
            '{"work_hours": {"enabled": true, "days": [9], "start": "09:00", "end": "18:00"}}',
            '{"work_hours": {"enabled": true, "days": [0], "start": "9h", "end": "18:00"}}',
            '{"work_hours": {"enabled": "sim", "days": [0], "start": "09:00", "end": "18:00"}}',
            '{"work_hours": {"enabled": true}}',
        ]
        for payload in payloads:
            with self.subTest(payload), self.assertLogs(config.logger, "WARNING") as logs:
                st = self.load_with(payload)
            self.assertEqual(len(logs.records), 1)
            self.assertEqual(st.work_hours, {"enabled": False, "days": WEEKDAYS, "start": "09:00", "end": "18:00"})
            self.assertFalse(timer.in_work_hours(st.work_hours, at(2, 12)))


class TrayWorkHoursMenuTest(TrayMixin, unittest.TestCase):
    def items(self):
        return self.top()["Horário de trabalho"].submenu.items

    def labels(self):
        return [i.text for i in self.items() if i is not tray.Menu.SEPARATOR]

    def test_entries_exist_and_it_is_off_by_default(self):
        self.assertEqual(self.labels(), ["Ligado", "Seg–Sex 09:00–18:00", "Seg–Sex 08:00–20:00"])
        self.assertFalse(self.items()[0].checked)

    def test_toggle_persists_across_a_reload(self):
        self.app._on_toggle_work_hours(None, None)
        self.assertTrue(self.items()[0].checked)
        self.assertTrue(tray.JigglerState().work_hours["enabled"])
        self.app._on_toggle_work_hours(None, None)
        self.assertFalse(tray.JigglerState().work_hours["enabled"])

    def test_presets_are_radio_items_and_the_default_one_is_checked(self):
        presets = [i for i in self.items() if i.radio]
        self.assertEqual([bool(i.checked) for i in presets], [True, False])

    def test_choosing_a_preset_persists_and_keeps_the_toggle(self):
        self.app._on_toggle_work_hours(None, None)
        label, days, start, end = tray.WORK_HOURS_PRESETS[1]
        self.app._on_set_work_hours(days, start, end)(None, None)
        reloaded = tray.JigglerState().work_hours
        self.assertEqual(reloaded, {"enabled": True, "days": WEEKDAYS, "start": "08:00", "end": "20:00"})
        presets = [i for i in self.items() if i.radio]
        self.assertEqual([bool(i.checked) for i in presets], [False, True])


if __name__ == "__main__":
    unittest.main()
