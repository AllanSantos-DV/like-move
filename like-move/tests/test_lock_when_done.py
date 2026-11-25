"""Testes da opção "Bloquear a tela ao terminar": bloqueia quando prazo, programa ou CPU acabam, desligada por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, tray  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402
from test_sister_features import state  # noqa: E402

ENDING = (awake.REASON_TIMED, awake.REASON_PROCESS, awake.REASON_CPU)


class ShouldLockWhenDoneTest(unittest.TestCase):
    def check(self, ending, reason=awake.REASON_WAITING, locked=False, **kw):
        st = state(lock_when_done=kw.pop("enabled", True))
        return awake.should_lock_when_done(st, ending_reason=ending, reason=reason, locked=locked)

    def test_locks_when_each_self_ending_trigger_gives_way_to_waiting(self):
        for ending in ENDING:
            with self.subTest(ending):
                self.assertTrue(self.check(ending))

    def test_off_by_default(self):
        self.assertFalse(self.check(awake.REASON_PROCESS, enabled=False))

    def test_never_for_reasons_that_do_not_end_by_themselves(self):
        for ending in (awake.REASON_IDLE, awake.REASON_ALWAYS, awake.REASON_KVM, None):
            with self.subTest(ending):
                self.assertFalse(self.check(ending))

    def test_never_when_a_gate_released_the_request(self):
        for gate in (
            awake.REASON_DISABLED, awake.REASON_LOCKED, awake.REASON_UNTRUSTED, awake.REASON_BATTERY,
            awake.REASON_LOW_BATTERY,
        ):
            with self.subTest(gate):
                self.assertFalse(self.check(awake.REASON_PROCESS, reason=gate))

    def test_never_while_another_reason_keeps_holding(self):
        for reason in (awake.REASON_ALWAYS, awake.REASON_KVM, awake.REASON_TIMED):
            with self.subTest(reason):
                self.assertFalse(self.check(awake.REASON_PROCESS, reason=reason))

    def test_an_idle_hold_alone_counts_as_released(self):
        self.assertTrue(self.check(awake.REASON_PROCESS, reason=awake.REASON_IDLE))

    def test_never_when_the_screen_is_already_locked(self):
        self.assertFalse(self.check(awake.REASON_PROCESS, locked=True))


class MonitorLockWhenDoneTest(unittest.TestCase):
    def setUp(self):
        patches = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "lock_workstation": mock.patch.object(awake, "lock_workstation"),
            "get_execution_state": mock.patch.object(
                awake, "get_execution_state", return_value=awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED
            ),
            "running_process_names": mock.patch.object(awake, "running_process_names", return_value={"blender.exe"}),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        kw.setdefault("watched_processes", ["blender.exe"])
        kw.setdefault("lock_when_done", True)
        st = state(**kw)
        mon = awake.MonitorThread(st)
        mon.notifier = mock.Mock()
        return st, mon

    def run_ticks(self, mon, count):
        for _ in range(count):
            mon._update()

    def end_process(self):
        self.m["running_process_names"].return_value = {"explorer.exe"}

    def test_locks_once_after_the_debounce_when_the_watched_program_exits(self):
        _, mon = self.monitor()
        self.run_ticks(mon, 3)
        self.end_process()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS - 1)
        self.m["lock_workstation"].assert_not_called()
        mon._update()
        self.m["lock_workstation"].assert_called_once_with()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_called_once_with()

    def test_the_lock_is_logged(self):
        _, mon = self.monitor()
        mon._update()
        self.end_process()
        with self.assertLogs(awake.logger, "INFO") as logs:
            self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS)
        self.assertTrue(any("bloqueando a tela" in r.getMessage() and awake.REASON_PROCESS in r.getMessage() for r in logs.records))

    def test_a_short_blip_does_not_lock(self):
        _, mon = self.monitor()
        mon._update()
        for _ in range(3):
            self.end_process()
            self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS - 1)
            self.m["running_process_names"].return_value = {"blender.exe"}
            mon._update()
        self.m["lock_workstation"].assert_not_called()

    def test_off_by_default_never_locks(self):
        _, mon = self.monitor(lock_when_done=False)
        mon._update()
        self.end_process()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_nothing_is_locked_just_for_starting_with_the_option_on(self):
        _, mon = self.monitor(watched_processes=[])
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_turning_the_app_off_does_not_lock(self):
        st, mon = self.monitor()
        mon._update()
        st.enabled = False
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.end_process()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_switching_to_always_mode_does_not_lock(self):
        st, mon = self.monitor()
        mon._update()
        st.trigger_mode = TriggerMode.ALWAYS
        self.end_process()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_idle_holding_never_locks_when_the_user_returns(self):
        _, mon = self.monitor(watched_processes=[])
        self.m["get_idle_time_ms"].return_value = 60_000
        self.run_ticks(mon, 3)
        self.m["get_idle_time_ms"].return_value = 0
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_locks_when_the_program_ends_with_the_user_away(self):
        _, mon = self.monitor()
        mon._update()
        self.m["get_idle_time_ms"].return_value = 60_000
        self.end_process()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS + 1)
        self.m["lock_workstation"].assert_called_once_with()

    def test_removing_the_watched_program_in_the_menu_does_not_lock(self):
        st, mon = self.monitor()
        mon._update()
        st.watched_processes = []
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_cancelling_the_deadline_in_the_menu_does_not_lock(self):
        st, mon = self.monitor(watched_processes=[], awake_until=1000.0)
        mon._update()
        st.awake_until = 0.0
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_a_screen_locked_by_the_user_meanwhile_does_not_lock_again(self):
        _, mon = self.monitor()
        mon._update()
        self.end_process()
        self.m["is_screen_locked"].return_value = True
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_not_called()

    def test_locks_when_a_deadline_runs_out(self):
        _, mon = self.monitor(watched_processes=[], awake_until=1000.0)
        with mock.patch.object(awake.time, "time", return_value=500.0):
            self.run_ticks(mon, 2)
        with mock.patch.object(awake.time, "time", return_value=2000.0):
            self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS)
        self.m["lock_workstation"].assert_called_once_with()

    def test_locks_when_the_busy_cpu_calms_down(self):
        _, mon = self.monitor(watched_processes=[], cpu_threshold=50)
        with mock.patch.object(mon, "_cpu_busy", return_value=True):
            self.run_ticks(mon, 2)
        with mock.patch.object(mon, "_cpu_busy", return_value=False):
            self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS)
        self.m["lock_workstation"].assert_called_once_with()

    def test_a_failing_lock_is_raised_and_not_retried_every_tick(self):
        _, mon = self.monitor()
        mon._update()
        self.end_process()
        self.m["lock_workstation"].side_effect = OSError("LockWorkStation falhou")
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS - 1)
        with self.assertRaises(OSError):
            mon._update()
        self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS * 2)
        self.m["lock_workstation"].assert_called_once_with()

    def test_a_second_run_of_the_program_locks_again(self):
        _, mon = self.monitor()
        for _ in range(2):
            self.m["running_process_names"].return_value = {"blender.exe"}
            mon._update()
            self.end_process()
            self.run_ticks(mon, awake.LOCK_DEBOUNCE_TICKS)
        self.assertEqual(self.m["lock_workstation"].call_count, 2)


class ConfigTest(unittest.TestCase):
    def test_off_by_default_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertFalse(st.lock_when_done)
            st.lock_when_done = True
            st.save()
            self.assertTrue(config.JigglerState().lock_when_done)


class TrayLockWhenDoneTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = tray.TrayApp()
        self.app._icon = mock.Mock()
        self.app._monitor = SimpleNamespace(status="x", notifier=None)

    def item(self):
        top = {(i.text(i) if callable(i.text) else i.text): i for i in self.app._build_menu().items}
        return top["Bloquear a tela ao terminar"]

    def test_unchecked_by_default(self):
        self.assertFalse(self.item().checked)

    def test_toggle_flips_and_persists(self):
        self.item()(self.app._icon)
        self.assertTrue(self.app._state.lock_when_done)
        self.assertTrue(tray.JigglerState().lock_when_done)
        self.assertTrue(self.item().checked)
        self.item()(self.app._icon)
        self.assertFalse(tray.JigglerState().lock_when_done)


if __name__ == "__main__":
    unittest.main()
