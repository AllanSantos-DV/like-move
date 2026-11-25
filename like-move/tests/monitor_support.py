"""Apoio dos testes de monitor e de menu: Win32 simulado e um TrayApp isolado em um APPDATA temporário."""

import os
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, tray  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402
from test_sister_features import state  # noqa: E402


class MonitorMixin:
    """Mistura para ``unittest.TestCase``: toda chamada ao Windows de ``awake`` é simulada em ``self.m``."""

    def setUp(self):
        super().setUp()
        patches = {
            "get_idle_time_ms": mock.patch.object(awake, "get_idle_time_ms", return_value=0),
            "is_screen_locked": mock.patch.object(awake, "is_screen_locked", return_value=False),
            "is_on_trusted_network": mock.patch.object(awake, "is_on_trusted_network", return_value=True),
            "is_on_ac_power": mock.patch.object(awake, "is_on_ac_power", return_value=True),
            "battery_percent": mock.patch.object(awake, "battery_percent", return_value=50),
            "get_interface_octets": mock.patch.object(awake, "get_interface_octets", return_value={1: (0, 0)}),
            "get_monitor_count": mock.patch.object(awake, "get_monitor_count", return_value=1),
            "set_keep_awake": mock.patch.object(awake, "set_keep_awake"),
            "get_execution_state": mock.patch.object(
                awake, "get_execution_state", return_value=awake.ES_SYSTEM_REQUIRED | awake.ES_DISPLAY_REQUIRED
            ),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def monitor(self, **kw):
        st = state(**kw)
        mon = awake.MonitorThread(st)
        mon.notifier = mock.Mock()
        return st, mon


class TrayMixin:
    """Mistura para ``unittest.TestCase``: ``self.app`` é um TrayApp que grava em um APPDATA temporário."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = tray.TrayApp()
        self.app._icon = mock.Mock()
        self.app._monitor = SimpleNamespace(status="x", notifier=None)

    def top(self):
        return {(i.text(i) if callable(i.text) else i.text): i for i in self.app._build_menu().items}
