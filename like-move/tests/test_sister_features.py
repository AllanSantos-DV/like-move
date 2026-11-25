"""Testes das funções irmãs: prazo, bloqueio ao sair da rede, vigia do pedido, só na tomada, status e diagnóstico.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import datetime as dt
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, diagnose, timer  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402


def state(**kw):
    base = dict(
        enabled=True, trusted_only=False, trigger_mode=TriggerMode.IDLE, idle_threshold=30,
        ac_only=False, lock_on_untrusted=False, awake_until=0.0, notify_transitions=False,
        trusted_networks=[{"ssid": "casa", "bssid": ""}], watched_processes=[], cpu_threshold=0,
    )
    base.update(kw)
    st = SimpleNamespace(**base)
    st.save = mock.Mock()
    return st


def decide(st, idle=0.0, kvm=False, trusted=False, locked=False, on_ac=True, timed=False):
    return awake.decide_keep_awake(
        st, idle_seconds=idle, device_disconnected=kvm, trusted=trusted, locked=locked, on_ac=on_ac, timed=timed,
    )


class TimerTest(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 25, 15, 0, 0)

    def test_status_while_waiting_in_kvm_mode_does_not_mention_idle_seconds(self):
        st = state(trigger_mode=TriggerMode.KVM)
        self.assertEqual(awake.status_text(awake.REASON_WAITING, st, idle_seconds=0), "Aguardando: dispositivo monitorado conectado")

    def test_deadline_after_minutes(self):
        self.assertEqual(timer.deadline_after(60, self.NOW), self.NOW.timestamp() + 3600)

    def test_clock_time_later_today(self):
        self.assertEqual(timer.deadline_until(18, 0, self.NOW), dt.datetime(2026, 11, 25, 18, 0).timestamp())

    def test_clock_time_already_passed_goes_to_tomorrow(self):
        self.assertEqual(timer.deadline_until(12, 0, self.NOW), dt.datetime(2026, 11, 26, 12, 0).timestamp())

    def test_clock_time_equal_to_now_goes_to_tomorrow(self):
        self.assertEqual(timer.deadline_until(15, 0, self.NOW), dt.datetime(2026, 11, 26, 15, 0).timestamp())

    def test_is_active_only_before_deadline(self):
        now = self.NOW.timestamp()
        self.assertTrue(timer.is_active(now + 1, now))
        self.assertFalse(timer.is_active(now, now))
        self.assertFalse(timer.is_active(0.0, now))

    def test_remaining_text(self):
        now = self.NOW.timestamp()
        self.assertEqual(timer.remaining_text(now + 45 * 60, now), "45 min")
        self.assertEqual(timer.remaining_text(now + 90 * 60, now), "1h30")
        self.assertEqual(timer.remaining_text(now + 30, now), "menos de 1 min")


class TimedKeepAwakeTest(unittest.TestCase):
    def test_timed_holds_even_in_idle_mode_without_conditions(self):
        self.assertTrue(decide(state(), idle=0, timed=True).wanted)

    def test_timed_still_respects_locked_screen(self):
        self.assertFalse(decide(state(), timed=True, locked=True).wanted)

    def test_timed_still_respects_disabled(self):
        self.assertFalse(decide(state(enabled=False), timed=True).wanted)

    def test_timed_still_respects_trusted_only(self):
        self.assertFalse(decide(state(trusted_only=True), timed=True, trusted=False).wanted)

    def test_without_timed_behaviour_is_unchanged(self):
        self.assertFalse(decide(state(), idle=0).wanted)


class AcOnlyTest(unittest.TestCase):
    def test_on_battery_blocks_when_ac_only(self):
        st = state(ac_only=True, trigger_mode=TriggerMode.ALWAYS)
        self.assertFalse(decide(st, on_ac=False).wanted)
        self.assertTrue(decide(st, on_ac=True).wanted)

    def test_battery_ignored_when_ac_only_is_off(self):
        self.assertTrue(decide(state(trigger_mode=TriggerMode.ALWAYS), on_ac=False).wanted)

    def test_ac_only_also_blocks_timed(self):
        self.assertFalse(decide(state(ac_only=True), timed=True, on_ac=False).wanted)


class ReasonTest(unittest.TestCase):
    def test_reason_for_each_outcome(self):
        always = state(trigger_mode=TriggerMode.ALWAYS)
        self.assertEqual(decide(state(enabled=False)).reason, awake.REASON_DISABLED)
        self.assertEqual(decide(always, locked=True).reason, awake.REASON_LOCKED)
        self.assertEqual(decide(state(trusted_only=True, trigger_mode=TriggerMode.ALWAYS)).reason, awake.REASON_UNTRUSTED)
        self.assertEqual(decide(state(ac_only=True, trigger_mode=TriggerMode.ALWAYS), on_ac=False).reason, awake.REASON_BATTERY)
        self.assertEqual(decide(state(), timed=True).reason, awake.REASON_TIMED)
        self.assertEqual(decide(always).reason, awake.REASON_ALWAYS)
        self.assertEqual(decide(state(), idle=30).reason, awake.REASON_IDLE)
        self.assertEqual(decide(state(trigger_mode=TriggerMode.KVM), kvm=True).reason, awake.REASON_KVM)

    def test_waiting_reason_when_no_condition_holds(self):
        self.assertEqual(decide(state(), idle=5).reason, awake.REASON_WAITING)

    def test_should_keep_awake_matches_decision(self):
        st = state(trigger_mode=TriggerMode.ALWAYS)
        self.assertEqual(
            awake.should_keep_awake(st, idle_seconds=0, device_disconnected=False, trusted=False, locked=False),
            decide(st).wanted,
        )

    def test_status_text_waiting_shows_seconds_left(self):
        text = awake.status_text(awake.REASON_WAITING, state(idle_threshold=30), idle_seconds=12)
        self.assertEqual(text, "Aguardando: faltam 18s")

    def test_status_text_holding_and_blocked(self):
        st = state()
        self.assertEqual(awake.status_text(awake.REASON_KVM, st, idle_seconds=0), "Acordado agora: KVM")
        self.assertEqual(awake.status_text(awake.REASON_UNTRUSTED, st, idle_seconds=0), "Parado: fora de rede confiável")


class LockOnLeaveTest(unittest.TestCase):
    def test_locks_on_edge_from_trusted_to_untrusted_when_opted_in(self):
        st = state(lock_on_untrusted=True)
        self.assertTrue(awake.should_lock_on_leave(st, was_trusted=True, trusted=False, locked=False))

    def test_off_by_default(self):
        self.assertFalse(awake.should_lock_on_leave(state(), was_trusted=True, trusted=False, locked=False))

    def test_no_lock_without_the_edge(self):
        st = state(lock_on_untrusted=True)
        self.assertFalse(awake.should_lock_on_leave(st, was_trusted=False, trusted=False, locked=False))
        self.assertFalse(awake.should_lock_on_leave(st, was_trusted=True, trusted=True, locked=False))

    def test_no_lock_when_already_locked(self):
        st = state(lock_on_untrusted=True)
        self.assertFalse(awake.should_lock_on_leave(st, was_trusted=True, trusted=False, locked=True))

    def test_no_lock_without_any_saved_network(self):
        st = state(lock_on_untrusted=True, trusted_networks=[])
        self.assertFalse(awake.should_lock_on_leave(st, was_trusted=True, trusted=False, locked=False))


class RequestLostTest(unittest.TestCase):
    BOTH = awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED

    def test_lost_when_holding_but_system_lacks_the_bits(self):
        self.assertTrue(awake.request_lost(True, 0))
        self.assertTrue(awake.request_lost(True, awake.ES_SYSTEM_REQUIRED))

    def test_not_lost_when_bits_are_present(self):
        self.assertFalse(awake.request_lost(True, self.BOTH))

    def test_not_lost_when_not_holding(self):
        self.assertFalse(awake.request_lost(False, 0))

    def test_unreadable_state_is_not_a_loss(self):
        self.assertFalse(awake.request_lost(True, None))


class MonitorUpdateTest(unittest.TestCase):
    def setUp(self):
        patches = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "is_on_trusted_network": mock.patch.object(awake, "is_on_trusted_network", return_value=True),
            "is_on_ac_power": mock.patch.object(awake, "is_on_ac_power", return_value=True),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "lock_workstation": mock.patch.object(awake, "lock_workstation"),
            "get_execution_state": mock.patch.object(awake, "get_execution_state", return_value=awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        st = state(**kw)
        mon = awake.MonitorThread(st)
        mon.notifier = mock.Mock()
        return st, mon

    def test_expired_deadline_is_cleared_and_saved(self):
        st, mon = self.monitor(trigger_mode=TriggerMode.IDLE, awake_until=100.0)
        with mock.patch.object(awake.time, "time", return_value=200.0):
            mon._update()
        self.assertEqual(st.awake_until, 0.0)
        st.save.assert_called()
        self.m["set_keep_awake"].assert_not_called()

    def test_deadline_expired_while_closed_is_cleared_without_a_toast(self):
        st, mon = self.monitor(awake_until=100.0)
        with mock.patch.object(awake.time, "time", return_value=200.0):
            mon._update()
        mon.notifier.assert_not_called()

    def test_deadline_expiring_while_running_toasts_once(self):
        st, mon = self.monitor(awake_until=100.0)
        mon._first_tick = False
        with mock.patch.object(awake.time, "time", return_value=200.0):
            mon._update()
        mon.notifier.assert_called_once()

    def test_a_deadline_set_during_the_tick_is_not_wiped(self):
        class Racing(SimpleNamespace):
            reads = 0

            @property
            def awake_until(self):
                Racing.reads += 1
                return 100.0 if Racing.reads == 1 else 5000.0

            @awake_until.setter
            def awake_until(self, value):
                self.written = value

        st = Racing(save=mock.Mock())
        mon = awake.MonitorThread(st)
        mon._timer_active(200.0)
        self.assertFalse(hasattr(st, "written"))

    def test_failing_notifier_does_not_break_the_tick(self):
        st, mon = self.monitor(notify_transitions=True, trigger_mode=TriggerMode.ALWAYS)
        mon.notifier.side_effect = RuntimeError("icon not ready")
        mon._update()
        self.m["set_keep_awake"].assert_called_with(True)

    def test_deadline_within_two_minutes_warns_once_and_keeps_holding(self):
        st, mon = self.monitor(awake_until=1000.0)
        mon._first_tick = False
        with mock.patch.object(awake.time, "time", return_value=900.0):
            mon._update()
            mon._update()
        mon.notifier.assert_called_once()
        self.assertIn("prorrogar", mon.notifier.call_args[0][0])
        self.m["set_keep_awake"].assert_called_once_with(True)

    def test_deadline_warning_is_logged(self):
        st, mon = self.monitor(awake_until=1000.0)
        mon._first_tick = False
        with mock.patch.object(awake.time, "time", return_value=900.0), self.assertLogs(awake.logger, "INFO") as logs:
            mon._update()
        self.assertTrue(any("avisando" in r.getMessage() for r in logs.records))

    def test_deadline_far_away_does_not_warn(self):
        st, mon = self.monitor(awake_until=1000.0)
        mon._first_tick = False
        with mock.patch.object(awake.time, "time", return_value=500.0):
            mon._update()
        mon.notifier.assert_not_called()

    def test_a_new_deadline_warns_again(self):
        st, mon = self.monitor(awake_until=1000.0)
        mon._first_tick = False
        with mock.patch.object(awake.time, "time", return_value=900.0):
            mon._update()
            st.awake_until = 1010.0
            mon._update()
        self.assertEqual(mon.notifier.call_count, 2)

    def test_active_deadline_holds_the_request(self):
        st, mon = self.monitor(awake_until=1000.0)
        with mock.patch.object(awake.time, "time", return_value=500.0):
            mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True)
        self.assertEqual(mon.status, "Acordado agora: prazo")

    def test_lock_fires_once_after_debounce_when_leaving_trusted_network(self):
        st, mon = self.monitor(trusted_only=True, lock_on_untrusted=True, trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        self.m["is_on_trusted_network"].return_value = False
        for _ in range(awake.LOCK_DEBOUNCE_TICKS - 1):
            mon._update()
        self.m["lock_workstation"].assert_not_called()
        mon._update()
        self.m["lock_workstation"].assert_called_once_with()
        mon._update()
        self.m["lock_workstation"].assert_called_once_with()

    def test_short_network_blip_does_not_lock(self):
        st, mon = self.monitor(trusted_only=True, lock_on_untrusted=True, trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        self.m["is_on_trusted_network"].return_value = False
        mon._update()
        self.m["is_on_trusted_network"].return_value = True
        for _ in range(awake.LOCK_DEBOUNCE_TICKS * 2):
            mon._update()
        self.m["lock_workstation"].assert_not_called()

    def test_lock_works_with_trusted_only_off(self):
        st, mon = self.monitor(trusted_only=False, lock_on_untrusted=True, trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        self.m["is_on_trusted_network"].return_value = False
        for _ in range(awake.LOCK_DEBOUNCE_TICKS):
            mon._update()
        self.m["lock_workstation"].assert_called_once_with()

    def test_lost_request_is_reasserted_and_reported_once(self):
        st, mon = self.monitor(trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        self.m["set_keep_awake"].reset_mock()
        self.m["get_execution_state"].return_value = 0
        with self.assertLogs(awake.logger, level="WARNING") as logs:
            mon._update()
            mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True)
        self.assertEqual(len([r for r in logs.records if "perdido" in r.getMessage()]), 1)

    def test_unreadable_execution_state_is_logged_not_swallowed(self):
        st, mon = self.monitor(trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        self.m["get_execution_state"].side_effect = OSError("falhou")
        with self.assertLogs(awake.logger, level="WARNING") as logs:
            mon._update()
        self.assertTrue(any("estado de energia" in r.getMessage() for r in logs.records))

    def test_transition_toast_only_when_opted_in(self):
        st, mon = self.monitor(trigger_mode=TriggerMode.ALWAYS)
        mon._update()
        mon.notifier.assert_not_called()
        st2, mon2 = self.monitor(trigger_mode=TriggerMode.ALWAYS, notify_transitions=True)
        mon2._update()
        mon2.notifier.assert_called_once_with("Acordado agora: Sempre")

    def test_status_is_published_every_tick(self):
        st, mon = self.monitor(trigger_mode=TriggerMode.IDLE)
        mon._update()
        self.assertTrue(mon.status.startswith("Aguardando: faltam"))


class ConfigDefaultsTest(unittest.TestCase):
    def test_corrupt_deadline_in_config_falls_back_to_no_deadline(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            d = os.path.join(tmp, "like-move")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                fh.write('{"awake_until": "amanhã"}')
            self.assertEqual(config.JigglerState().awake_until, 0.0)

    def test_new_options_are_off_by_default_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertFalse(st.ac_only)
            self.assertFalse(st.lock_on_untrusted)
            self.assertFalse(st.notify_transitions)
            self.assertEqual(st.awake_until, 0.0)
            st.ac_only = True
            st.lock_on_untrusted = True
            st.notify_transitions = True
            st.awake_until = 123.5
            st.save()
            again = config.JigglerState()
            self.assertTrue(again.ac_only and again.lock_on_untrusted and again.notify_transitions)
            self.assertEqual(again.awake_until, 123.5)


class DiagnoseTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "o diagnóstico usa o PowerShell do Windows")
    def test_real_run_writes_a_report_without_the_home_awake_enrollment_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = diagnose.run(out_path=os.path.join(tmp, "diagnostico.txt"))
            with open(out, encoding="utf-8-sig") as fh:
                text = fh.read()
        self.assertIn("Diagnóstico do bloqueio de tela", text)
        self.assertNotIn("Rede de casa:", text)

    def test_command_imports_the_module_and_writes_the_report_to_the_given_path(self):
        cmd = diagnose.build_command(r"C:\x\HomeAwake.psm1", r"C:\x\out.txt")
        self.assertEqual(cmd[0], "powershell.exe")
        joined = " ".join(cmd)
        self.assertIn("Get-LockDiagnosis", joined)
        self.assertIn("Format-LockDiagnosis", joined)
        self.assertIn(r"C:\x\out.txt", joined)

    def test_run_returns_the_report_path_and_hides_the_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            psm1 = os.path.join(tmp, "HomeAwake.psm1")
            out = os.path.join(tmp, "diagnostico.txt")
            open(psm1, "w", encoding="utf-8").close()
            with open(out, "w", encoding="utf-8") as f:
                f.write("ok")
            with mock.patch.object(diagnose.subprocess, "run") as run:
                run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
                path = diagnose.run(psm1=psm1, out_path=out)
            self.assertEqual(path, out)
            self.assertEqual(run.call_args.kwargs["creationflags"], diagnose.CREATE_NO_WINDOW)

    def test_failure_raises_with_the_powershell_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            psm1 = os.path.join(tmp, "HomeAwake.psm1")
            open(psm1, "w", encoding="utf-8").close()
            with mock.patch.object(diagnose.subprocess, "run") as run:
                run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="boom")
                with self.assertRaises(RuntimeError) as ctx:
                    diagnose.run(psm1=psm1, out_path=os.path.join(tmp, "out.txt"))
        self.assertIn("boom", str(ctx.exception))

    def test_success_without_a_written_report_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            psm1 = os.path.join(tmp, "HomeAwake.psm1")
            open(psm1, "w", encoding="utf-8").close()
            with mock.patch.object(diagnose.subprocess, "run") as run:
                run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
                with self.assertRaises(RuntimeError):
                    diagnose.run(psm1=psm1, out_path=os.path.join(tmp, "out.txt"))

    def test_missing_module_raises(self):
        with self.assertRaises(FileNotFoundError):
            diagnose.run(psm1=os.path.join(tempfile.gettempdir(), "nao-existe", "HomeAwake.psm1"))


class PackagingTest(unittest.TestCase):
    def test_spec_ships_the_home_awake_module_used_by_the_diagnosis(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "like-move.spec"), encoding="utf-8") as f:
            spec = f.read()
        self.assertIn("('home-awake/HomeAwake.psm1', 'home-awake')", spec)
        self.assertTrue(os.path.isfile(os.path.join(root, "home-awake", "HomeAwake.psm1")))


if __name__ == "__main__":
    unittest.main()
