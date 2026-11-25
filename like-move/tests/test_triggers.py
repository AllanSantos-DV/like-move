"""Testes dos gatilhos por programa em execução e por carga de CPU.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, detector, triggers  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402
from test_sister_features import state  # noqa: E402


class ProcessMatchingTest(unittest.TestCase):
    def test_name_is_normalized_like_the_windows_list(self):
        self.assertEqual(triggers.normalize_process_name("  Blender "), "blender.exe")
        self.assertEqual(triggers.normalize_process_name("Code.EXE"), "code.exe")
        self.assertEqual(triggers.normalize_process_name(""), "")

    def test_any_running_matches_case_insensitively(self):
        self.assertTrue(triggers.any_running(["Blender"], {"blender.exe", "explorer.exe"}))

    def test_no_match_when_the_program_is_not_running(self):
        self.assertFalse(triggers.any_running(["blender.exe"], {"explorer.exe"}))

    def test_empty_watch_list_never_matches(self):
        self.assertFalse(triggers.any_running([], {"explorer.exe"}))
        self.assertFalse(triggers.any_running(["  "], {"explorer.exe", ""}))


class CpuPercentTest(unittest.TestCase):
    def test_idle_share_of_the_interval_gives_the_load(self):
        # intervalo: kernel 100 (inclui 60 ocioso) + usuário 100 => 200 total, 60 ocioso => 70%
        self.assertAlmostEqual(triggers.cpu_percent((0, 0, 0), (60, 100, 100)), 70.0)

    def test_no_time_elapsed_gives_none(self):
        self.assertIsNone(triggers.cpu_percent((5, 10, 10), (5, 10, 10)))


class CpuLoadGateTest(unittest.TestCase):
    def feed(self, gate, value, times, threshold=50):
        for _ in range(times):
            gate.update(value, threshold)
        return gate.busy

    def test_needs_consecutive_readings_above_the_limit_to_turn_on(self):
        gate = triggers.CpuLoadGate()
        self.assertFalse(self.feed(gate, 90, triggers.CPU_ON_TICKS - 1))
        self.assertTrue(gate.update(90, 50))

    def test_a_dip_resets_the_count_to_turn_on(self):
        gate = triggers.CpuLoadGate()
        self.feed(gate, 90, triggers.CPU_ON_TICKS - 1)
        gate.update(10, 50)
        self.assertFalse(self.feed(gate, 90, triggers.CPU_ON_TICKS - 1))

    def test_stays_on_through_short_pauses(self):
        gate = triggers.CpuLoadGate()
        self.feed(gate, 90, triggers.CPU_ON_TICKS)
        self.assertTrue(self.feed(gate, 5, triggers.CPU_OFF_TICKS - 1))

    def test_turns_off_after_a_long_quiet_stretch(self):
        gate = triggers.CpuLoadGate()
        self.feed(gate, 90, triggers.CPU_ON_TICKS)
        self.assertFalse(self.feed(gate, 5, triggers.CPU_OFF_TICKS))

    def test_a_missing_reading_keeps_the_state(self):
        gate = triggers.CpuLoadGate()
        self.feed(gate, 90, triggers.CPU_ON_TICKS)
        self.assertTrue(gate.update(None, 50))

    def test_reset_forgets_everything(self):
        gate = triggers.CpuLoadGate()
        self.feed(gate, 90, triggers.CPU_ON_TICKS)
        gate.reset()
        self.assertFalse(gate.busy)


class DecisionTest(unittest.TestCase):
    def decide(self, **kw):
        locked = kw.pop("locked", False)
        return awake.decide_keep_awake(
            state(), idle_seconds=0, device_disconnected=False, trusted=True, locked=locked, **kw
        )

    def test_watched_program_running_holds_even_when_the_user_is_active(self):
        d = self.decide(process_running=True)
        self.assertEqual((d.wanted, d.reason), (True, awake.REASON_PROCESS))

    def test_busy_cpu_holds_even_when_the_user_is_active(self):
        d = self.decide(cpu_busy=True)
        self.assertEqual((d.wanted, d.reason), (True, awake.REASON_CPU))

    def test_program_wins_over_cpu_in_the_reason(self):
        self.assertEqual(self.decide(process_running=True, cpu_busy=True).reason, awake.REASON_PROCESS)

    def test_gates_still_win_over_both_triggers(self):
        self.assertEqual(self.decide(process_running=True, cpu_busy=True, locked=True).reason, awake.REASON_LOCKED)
        st = state(trusted_only=True)
        d = awake.decide_keep_awake(
            st, idle_seconds=0, device_disconnected=False, trusted=False, locked=False, process_running=True,
        )
        self.assertEqual(d.reason, awake.REASON_UNTRUSTED)
        st = state(ac_only=True)
        d = awake.decide_keep_awake(
            st, idle_seconds=0, device_disconnected=False, trusted=True, locked=False, on_ac=False, cpu_busy=True,
        )
        self.assertEqual(d.reason, awake.REASON_BATTERY)

    def test_without_the_triggers_the_decision_is_unchanged(self):
        self.assertEqual(self.decide().reason, awake.REASON_WAITING)

    def test_status_text_names_the_trigger(self):
        st = state()
        self.assertEqual(awake.status_text(awake.REASON_PROCESS, st, idle_seconds=0), "Acordado agora: programa em execução")
        self.assertEqual(awake.status_text(awake.REASON_CPU, st, idle_seconds=0), "Acordado agora: CPU alta")


class MonitorTriggersTest(unittest.TestCase):
    def setUp(self):
        names = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "is_on_trusted_network": mock.patch.object(awake, "is_on_trusted_network", return_value=True),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "get_execution_state": mock.patch.object(
                awake, "get_execution_state", return_value=awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED
            ),
            "running_process_names": mock.patch.object(awake, "running_process_names", return_value={"explorer.exe"}),
            "get_system_times": mock.patch.object(awake, "get_system_times", return_value=(0, 0, 0)),
        }
        self.m = {k: p.start() for k, p in names.items()}
        for p in names.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        st = state(**kw)
        mon = awake.MonitorThread(st)
        mon.notifier = mock.Mock()
        return st, mon

    def test_watched_program_starting_turns_the_request_on(self):
        st, mon = self.monitor(watched_processes=["blender.exe"])
        mon._update()
        self.m["set_keep_awake"].assert_not_called()
        self.m["running_process_names"].return_value = {"blender.exe"}
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True)
        self.assertEqual(mon.status, "Acordado agora: programa em execução")

    def test_process_list_is_not_read_when_nothing_is_watched(self):
        st, mon = self.monitor()
        mon._update()
        self.m["running_process_names"].assert_not_called()

    def test_failing_process_list_is_logged_once_and_counts_as_not_running(self):
        st, mon = self.monitor(watched_processes=["blender.exe"])
        self.m["running_process_names"].side_effect = OSError("snapshot")
        with self.assertLogs(awake.logger, "WARNING") as logs:
            mon._update()
            mon._update()
        self.assertEqual(len(logs.records), 1)
        self.m["set_keep_awake"].assert_not_called()

    def test_busy_cpu_turns_the_request_on_after_the_debounce(self):
        st, mon = self.monitor(cpu_threshold=50)
        total = [0]

        def times():
            total[0] += 100
            return (total[0] * 0, total[0], total[0])  # nenhum ocioso: 100% de carga

        self.m["get_system_times"].side_effect = times
        for _ in range(triggers.CPU_ON_TICKS):
            mon._update()
        self.m["set_keep_awake"].assert_not_called()
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True)
        self.assertEqual(mon.status, "Acordado agora: CPU alta")

    def test_cpu_is_not_sampled_when_the_option_is_off(self):
        st, mon = self.monitor(cpu_threshold=0)
        mon._update()
        self.m["get_system_times"].assert_not_called()


class RealWindowsTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "usa a API do Windows")
    def test_running_process_names_lists_this_interpreter(self):
        mine = os.path.basename(sys.executable).lower()
        self.assertIn(mine, detector.running_process_names())

    @unittest.skipUnless(sys.platform == "win32", "usa a API do Windows")
    def test_system_times_grow_and_kernel_includes_idle(self):
        idle, kernel, user = detector.get_system_times()
        self.assertGreater(kernel, 0)
        self.assertLessEqual(idle, kernel)
        self.assertGreater(user, 0)

    @unittest.skipUnless(sys.platform == "win32", "usa a API do Windows")
    def test_visible_window_names_are_sorted_lowercase_exe_names(self):
        names = detector.visible_window_process_names()
        self.assertEqual(names, sorted(names))
        self.assertTrue(all(n == n.lower() and n.endswith(".exe") for n in names))


class ConfigTest(unittest.TestCase):
    def load_with(self, payload):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            d = os.path.join(tmp, "like-move")
            os.makedirs(d)
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                fh.write(payload)
            return config.JigglerState()

    def test_defaults_are_off(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertEqual(st.watched_processes, [])
            self.assertEqual(st.cpu_threshold, 0)

    def test_values_persist(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            st.watched_processes = ["blender.exe"]
            st.cpu_threshold = 75
            st.save()
            again = config.JigglerState()
            self.assertEqual((again.watched_processes, again.cpu_threshold), (["blender.exe"], 75))

    def test_corrupt_values_fall_back_with_a_warning(self):
        with self.assertLogs(config.logger, "WARNING") as logs:
            st = self.load_with('{"watched_processes": "blender", "cpu_threshold": "alto"}')
        self.assertEqual((st.watched_processes, st.cpu_threshold), ([], 0))
        self.assertEqual(len(logs.records), 2)

    def test_out_of_range_threshold_is_rejected(self):
        with self.assertLogs(config.logger, "WARNING"):
            self.assertEqual(self.load_with('{"cpu_threshold": 250}').cpu_threshold, 0)


if __name__ == "__main__":
    unittest.main()
