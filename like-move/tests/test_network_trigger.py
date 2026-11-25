"""Testes da "Rede ocupada": mantém acordado enquanto o tráfego de rede fica acima do limite, desligada por padrão.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import ctypes
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, config, detector, tray, triggers  # noqa: E402
from monitor_support import MonitorMixin, TrayMixin  # noqa: E402
from test_sister_features import state  # noqa: E402

WRAP = 1 << 32


class BytesPerSecondTest(unittest.TestCase):
    def test_sums_received_and_sent_over_the_interval(self):
        self.assertEqual(triggers.bytes_per_second({1: (100, 50)}, {1: (400, 250)}, 2.0), 250.0)

    def test_sums_every_interface(self):
        previous = {1: (0, 0), 2: (0, 0)}
        self.assertEqual(triggers.bytes_per_second(previous, {1: (100, 0), 2: (0, 300)}, 1.0), 400.0)

    def test_a_counter_that_went_back_is_not_counted_as_a_burst(self):
        self.assertEqual(triggers.bytes_per_second({1: (WRAP - 100, 0)}, {1: (400, 0)}, 1.0), 0.0)
        self.assertEqual(triggers.bytes_per_second({1: (0, 5000)}, {1: (0, 90)}, 2.0), 0.0)

    def test_an_interface_that_appeared_is_not_counted(self):
        previous, current = {1: (0, 0)}, {1: (100, 0), 2: (9_000_000, 9_000_000)}
        self.assertEqual(triggers.bytes_per_second(previous, current, 1.0), 100.0)

    def test_an_interface_that_disappeared_is_not_counted(self):
        previous, current = {1: (0, 0), 2: (5, 5)}, {1: (100, 0)}
        self.assertEqual(triggers.bytes_per_second(previous, current, 1.0), 100.0)

    def test_no_interface_in_common_measures_zero(self):
        self.assertEqual(triggers.bytes_per_second({1: (0, 0)}, {2: (10, 10)}, 1.0), 0.0)
        self.assertEqual(triggers.bytes_per_second({}, {}, 1.0), 0.0)

    def test_no_time_elapsed_gives_none(self):
        self.assertIsNone(triggers.bytes_per_second({1: (0, 0)}, {1: (5, 5)}, 0))
        self.assertIsNone(triggers.bytes_per_second({1: (0, 0)}, {1: (5, 5)}, -1.0))


class LoadGateTest(unittest.TestCase):
    def test_the_ticks_are_the_ones_given(self):
        gate = triggers.LoadGate(2, 3)
        gate.update(10, 5)
        self.assertFalse(gate.busy)
        gate.update(10, 5)
        self.assertTrue(gate.busy)
        for _ in range(2):
            gate.update(0, 5)
        self.assertTrue(gate.busy)
        gate.update(0, 5)
        self.assertFalse(gate.busy)

    def test_network_gate_uses_the_network_ticks(self):
        gate = triggers.NetworkLoadGate()
        for _ in range(triggers.NETWORK_ON_TICKS - 1):
            gate.update(500, 100)
        self.assertFalse(gate.busy)
        gate.update(500, 100)
        self.assertTrue(gate.busy)
        for _ in range(triggers.NETWORK_OFF_TICKS - 1):
            gate.update(0, 100)
        self.assertTrue(gate.busy)
        gate.update(0, 100)
        self.assertFalse(gate.busy)

    def test_a_missing_reading_keeps_the_state(self):
        gate = triggers.NetworkLoadGate()
        gate.busy = True
        self.assertTrue(gate.update(None, 100))


def row(index, kind=6, flags=detector._IF_FLAG_HARDWARE, received=0, sent=0):
    r = detector.MIB_IF_ROW2()
    r.InterfaceIndex, r.Type, r.InterfaceAndOperStatusFlags, r.InOctets, r.OutOctets = index, kind, flags, received, sent
    return r


class InterfaceOctetsTest(unittest.TestCase):
    def test_struct_matches_the_documented_size(self):
        self.assertEqual(ctypes.sizeof(detector.MIB_IF_ROW2), 1352)

    def test_only_physical_non_loopback_interfaces_count(self):
        rows = [
            row(1, received=10, sent=20),
            row(2, kind=24, received=99, sent=99),
            row(3, flags=detector._IF_FLAG_HARDWARE | detector._IF_FLAG_FILTER, received=99, sent=99),
            row(4, flags=0, received=99, sent=99),
        ]
        self.assertEqual(detector.physical_octets(rows), {1: (10, 20)})

    def test_counters_keep_their_64_bits(self):
        self.assertEqual(detector.physical_octets([row(1, received=WRAP + 7)]), {1: (WRAP + 7, 0)})

    def test_a_failed_call_is_an_error_with_its_code(self):
        fake = mock.Mock()
        fake.GetIfTable2.return_value = 87
        with mock.patch.object(detector, "_iphlpapi", fake):
            with self.assertRaisesRegex(OSError, "87"):
                detector.get_interface_octets()
        fake.FreeMibTable.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "usa a API do Windows")
    def test_the_real_call_returns_counters_per_interface(self):
        octets = detector.get_interface_octets()
        self.assertIsInstance(octets, dict)
        for index, (received, sent) in octets.items():
            self.assertIsInstance(index, int)
            self.assertGreaterEqual(received, 0)
            self.assertGreaterEqual(sent, 0)


class DecisionTest(unittest.TestCase):
    def decide(self, st=None, **kw):
        return awake.decide_keep_awake(
            st or state(), idle_seconds=0, device_disconnected=False, trusted=kw.pop("trusted", True),
            locked=kw.pop("locked", False), **kw,
        )

    def test_busy_network_holds_with_its_reason(self):
        d = self.decide(network_busy=True)
        self.assertEqual((d.wanted, d.reason), (True, awake.REASON_NETWORK))
        self.assertIn(awake.REASON_NETWORK, awake._HOLDING_REASONS)
        self.assertEqual(awake.status_text(d.reason, state(), idle_seconds=0), "Acordado agora: rede em uso")

    def test_gates_win(self):
        self.assertEqual(self.decide(network_busy=True, locked=True).reason, awake.REASON_LOCKED)
        self.assertEqual(self.decide(state(trusted_only=True), network_busy=True, trusted=False).reason, awake.REASON_UNTRUSTED)
        self.assertEqual(self.decide(state(ac_only=True), network_busy=True, on_ac=False).reason, awake.REASON_BATTERY)
        self.assertEqual(self.decide(network_busy=True, battery_low=True).reason, awake.REASON_LOW_BATTERY)

    def test_it_sits_below_the_other_triggers(self):
        self.assertEqual(self.decide(network_busy=True, cpu_busy=True).reason, awake.REASON_CPU)
        self.assertEqual(self.decide(network_busy=True, process_running=True).reason, awake.REASON_PROCESS)
        self.assertEqual(self.decide(network_busy=True, timed=True).reason, awake.REASON_TIMED)

    def test_default_decision_is_unchanged(self):
        self.assertEqual(self.decide().reason, awake.REASON_WAITING)

    def test_should_keep_awake_follows_it(self):
        self.assertTrue(awake.should_keep_awake(
            state(), idle_seconds=0, device_disconnected=False, trusted=True, locked=False, network_busy=True,
        ))


class MonitorNetworkTest(MonitorMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.clock = [100.0]
        self.received = [0]
        patcher = mock.patch.object(awake.time, "monotonic", side_effect=lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tick(self, mon, per_second=300_000):
        self.clock[0] += 1.0
        self.received[0] += per_second
        self.m["get_interface_octets"].return_value = {1: (self.received[0], 0)}
        mon._update()

    def hold(self, mon):
        for _ in range(triggers.NETWORK_ON_TICKS):
            self.tick(mon)
        self.m["set_keep_awake"].assert_not_called()
        self.tick(mon)
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_off_by_default_nothing_is_read(self):
        _, mon = self.monitor()
        for _ in range(3):
            self.tick(mon)
        self.m["get_interface_octets"].assert_not_called()
        self.m["set_keep_awake"].assert_not_called()
        self.assertTrue(mon.status.startswith("Aguardando"))

    def test_traffic_above_the_limit_holds_after_the_debounce(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.hold(mon)
        self.assertEqual(mon.status, "Acordado agora: rede em uso")

    def test_traffic_below_the_limit_does_not_hold(self):
        _, mon = self.monitor(network_threshold_kbps=500)
        for _ in range(triggers.NETWORK_ON_TICKS + 3):
            self.tick(mon, per_second=100_000)
        self.m["set_keep_awake"].assert_not_called()

    def test_the_limit_is_in_kilobytes_per_second(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        for _ in range(triggers.NETWORK_ON_TICKS + 3):
            self.tick(mon, per_second=100 * 1024 - 1)
        self.m["set_keep_awake"].assert_not_called()
        for _ in range(triggers.NETWORK_ON_TICKS):
            self.tick(mon, per_second=100 * 1024)
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_a_counter_reset_does_not_hold_the_request(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.received[0] = WRAP - 600_000
        for _ in range(triggers.NETWORK_ON_TICKS + 1):
            self.clock[0] += 1.0
            self.received[0] = 1_000
            self.m["get_interface_octets"].return_value = {1: (self.received[0], 0)}
            mon._update()
        self.m["set_keep_awake"].assert_not_called()

    def test_it_releases_only_after_the_slow_exit(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.hold(mon)
        for _ in range(triggers.NETWORK_OFF_TICKS - 1):
            self.tick(mon, per_second=0)
        self.m["set_keep_awake"].assert_called_once_with(True, True)
        self.tick(mon, per_second=0)
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (False, True))

    def test_a_failed_read_is_logged_once_and_counts_as_not_busy(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.m["get_interface_octets"].side_effect = OSError("GetIfTable2 falhou (erro 5)")
        with self.assertLogs(awake.logger, "WARNING") as logs:
            for _ in range(triggers.NETWORK_ON_TICKS + 2):
                mon._update()
        self.assertEqual(len(logs.records), 1)
        self.m["set_keep_awake"].assert_not_called()

    def test_a_failed_read_while_holding_keeps_holding(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.hold(mon)
        self.m["get_interface_octets"].side_effect = OSError("falhou")
        with self.assertLogs(awake.logger, "WARNING"):
            mon._update()
        self.m["set_keep_awake"].assert_called_once_with(True, True)

    def test_changing_the_limit_clears_the_history(self):
        st, mon = self.monitor(network_threshold_kbps=100)
        self.hold(mon)
        st.network_threshold_kbps = 500
        self.tick(mon)
        self.assertFalse(mon._network_gate.busy)

    def test_turning_it_off_stops_reading(self):
        st, mon = self.monitor(network_threshold_kbps=100)
        self.hold(mon)
        st.network_threshold_kbps = 0
        self.m["get_interface_octets"].reset_mock()
        self.tick(mon)
        self.m["get_interface_octets"].assert_not_called()
        self.assertEqual(self.m["set_keep_awake"].call_args.args, (False, True))

    def test_locked_screen_wins(self):
        _, mon = self.monitor(network_threshold_kbps=100)
        self.m["is_screen_locked"].return_value = True
        for _ in range(triggers.NETWORK_ON_TICKS + 1):
            self.tick(mon)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: tela bloqueada")

    def test_untrusted_network_wins(self):
        _, mon = self.monitor(network_threshold_kbps=100, trusted_only=True)
        self.m["is_on_trusted_network"].return_value = False
        for _ in range(triggers.NETWORK_ON_TICKS + 1):
            self.tick(mon)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: fora de rede confiável")

    def test_ac_only_on_battery_wins(self):
        _, mon = self.monitor(network_threshold_kbps=100, ac_only=True)
        self.m["is_on_ac_power"].return_value = False
        for _ in range(triggers.NETWORK_ON_TICKS + 1):
            self.tick(mon)
        self.m["set_keep_awake"].assert_not_called()
        self.assertEqual(mon.status, "Parado: na bateria")


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
            self.assertEqual(st.network_threshold_kbps, 0)
            st.network_threshold_kbps = 500
            st.save()
            self.assertEqual(config.JigglerState().network_threshold_kbps, 500)

    def test_invalid_values_fall_back_with_a_warning(self):
        for payload in ('{"network_threshold_kbps": "rápido"}', '{"network_threshold_kbps": -1}',
                        '{"network_threshold_kbps": true}', '{"network_threshold_kbps": 1.5}'):
            with self.subTest(payload), self.assertLogs(config.logger, "WARNING"):
                self.assertEqual(self.load_with(payload).network_threshold_kbps, 0)


class TrayNetworkMenuTest(TrayMixin, unittest.TestCase):
    def items(self):
        return self.top()["Rede ocupada"].submenu.items

    def test_options_are_radio_items_with_off_checked_by_default(self):
        items = self.items()
        self.assertEqual([i.text for i in items], ["Desligado", "Acima de 100 KB/s", "Acima de 500 KB/s", "Acima de 2 MB/s"])
        self.assertTrue(all(i.radio for i in items))
        self.assertEqual([bool(i.checked) for i in items], [True, False, False, False])

    def test_choosing_a_limit_persists_and_moves_the_check(self):
        self.app._on_set_network_threshold(500)(None, None)
        self.assertEqual(tray.JigglerState().network_threshold_kbps, 500)
        self.assertEqual([bool(i.checked) for i in self.items()], [False, False, True, False])
        self.app._on_set_network_threshold(2048)(None, None)
        self.assertEqual(tray.JigglerState().network_threshold_kbps, 2048)
        self.app._on_set_network_threshold(0)(None, None)
        self.assertEqual(tray.JigglerState().network_threshold_kbps, 0)


if __name__ == "__main__":
    unittest.main()
