"""Testes da opção "Tela pode apagar": o pedido de energia sem ES_DISPLAY_REQUIRED, desligada por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config  # noqa: E402
from tests.test_sister_features import state  # noqa: E402

SYSTEM = awake.ES_SYSTEM_REQUIRED
BOTH = awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED


class RequestBitsTest(unittest.TestCase):
    def test_default_request_holds_system_and_display(self):
        self.assertEqual(awake.required_bits(True), BOTH)

    def test_display_may_sleep_requests_only_the_system(self):
        self.assertEqual(awake.required_bits(False), SYSTEM)

    def test_set_keep_awake_passes_the_flags_to_windows(self):
        with mock.patch.object(awake, "_kernel32") as k32:
            k32.SetThreadExecutionState.return_value = 1
            awake.set_keep_awake(True)
            awake.set_keep_awake(True, display=False)
            awake.set_keep_awake(False, display=False)
        flags = [c.args[0] for c in k32.SetThreadExecutionState.call_args_list]
        self.assertEqual(flags, [awake.ES_CONTINUOUS | BOTH, awake.ES_CONTINUOUS | SYSTEM, awake.ES_CONTINUOUS])

    def test_system_only_request_is_not_lost_without_the_display_bit(self):
        self.assertFalse(awake.request_lost(True, SYSTEM, display=False))

    def test_default_request_is_lost_without_the_display_bit(self):
        self.assertTrue(awake.request_lost(True, SYSTEM))


class MonitorDisplayTest(unittest.TestCase):
    def setUp(self):
        patches = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "get_execution_state": mock.patch.object(awake, "get_execution_state", return_value=SYSTEM),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        st = state(trigger_mode=awake.TriggerMode.ALWAYS, **kw)
        return st, awake.MonitorThread(st)

    def test_default_keeps_the_display_on(self):
        _, mon = self.monitor()
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_option_on_requests_the_system_only(self):
        _, mon = self.monitor(display_may_sleep=True)
        mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, False)

    def test_system_only_request_is_not_reasserted_when_the_display_bit_is_absent(self):
        _, mon = self.monitor(display_may_sleep=True)
        mon._update()
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_count, 1)

    def test_toggling_while_holding_refreshes_the_request_once(self):
        st, mon = self.monitor()
        self.m["get_execution_state"].return_value = BOTH
        mon._update()
        st.display_may_sleep = True
        mon._update()
        mon._update()
        self.assertEqual([c.args for c in self.m["set_keep_awake"].call_args_list], [(True, True), (True, False)])

    def test_system_request_lost_is_reasserted_without_the_display(self):
        _, mon = self.monitor(display_may_sleep=True)
        mon._update()
        self.m["get_execution_state"].return_value = 0
        mon._update()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (True, False))


class OptionPersistenceTest(unittest.TestCase):
    def test_defaults_off_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            st = config.JigglerState()
            self.assertFalse(st.display_may_sleep)
            st.display_may_sleep = True
            st.save()
            self.assertTrue(config.JigglerState().display_may_sleep)


if __name__ == "__main__":
    unittest.main()
