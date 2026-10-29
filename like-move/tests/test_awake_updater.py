"""Testes do like-move: decisão de manter acordado e atualização sem script auxiliar.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import awake, updater  # noqa: E402
from like_move.config import TriggerMode  # noqa: E402


def state(**kw):
    base = dict(enabled=True, trusted_only=False, trigger_mode=TriggerMode.IDLE, idle_threshold=30)
    base.update(kw)
    return SimpleNamespace(**base)


def decide(st, idle=0.0, kvm=False, trusted=False, locked=False):
    return awake.should_keep_awake(st, idle_seconds=idle, device_disconnected=kvm, trusted=trusted, locked=locked)


class ShouldKeepAwakeTest(unittest.TestCase):
    def test_idle_mode_holds_only_after_threshold(self):
        self.assertFalse(decide(state(), idle=29.9))
        self.assertTrue(decide(state(), idle=30))

    def test_kvm_mode_holds_only_while_device_disconnected(self):
        st = state(trigger_mode=TriggerMode.KVM)
        self.assertFalse(decide(st, idle=999))
        self.assertTrue(decide(st, kvm=True))

    def test_both_mode_holds_on_either_condition(self):
        st = state(trigger_mode=TriggerMode.BOTH)
        self.assertTrue(decide(st, idle=30))
        self.assertTrue(decide(st, kvm=True))
        self.assertFalse(decide(st, idle=1))

    def test_always_mode_holds_without_conditions(self):
        self.assertTrue(decide(state(trigger_mode=TriggerMode.ALWAYS)))

    def test_disabled_never_holds(self):
        self.assertFalse(decide(state(enabled=False, trigger_mode=TriggerMode.ALWAYS)))

    def test_locked_screen_never_holds(self):
        self.assertFalse(decide(state(trigger_mode=TriggerMode.ALWAYS), locked=True))

    def test_trusted_only_blocks_on_untrusted_network(self):
        st = state(trusted_only=True, trigger_mode=TriggerMode.ALWAYS)
        self.assertFalse(decide(st, trusted=False))
        self.assertTrue(decide(st, trusted=True))

    def test_network_ignored_when_trusted_only_is_off(self):
        self.assertTrue(decide(state(trigger_mode=TriggerMode.ALWAYS), trusted=False))


class SetKeepAwakeTest(unittest.TestCase):
    def test_on_requests_display_and_system_continuously(self):
        with mock.patch.object(awake._kernel32, "SetThreadExecutionState", return_value=1) as stes:
            awake.set_keep_awake(True)
        stes.assert_called_once_with(0x80000003)

    def test_off_clears_with_continuous_only(self):
        with mock.patch.object(awake._kernel32, "SetThreadExecutionState", return_value=1) as stes:
            awake.set_keep_awake(False)
        stes.assert_called_once_with(0x80000000)

    def test_api_failure_raises(self):
        with mock.patch.object(awake._kernel32, "SetThreadExecutionState", return_value=0):
            with self.assertRaises(OSError):
                awake.set_keep_awake(True)


class NoInputInjectionTest(unittest.TestCase):
    def test_package_never_calls_sendinput(self):
        pkg = os.path.dirname(awake.__file__)
        for name in os.listdir(pkg):
            if name.endswith(".py"):
                with open(os.path.join(pkg, name), encoding="utf-8") as f:
                    self.assertNotIn("SendInput", f.read(), name)


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


class PickAssetTest(unittest.TestCase):
    def test_picks_the_zip_and_ignores_old_exe_assets(self):
        assets = [
            {"name": "like-move.exe", "browser_download_url": "u1"},
            {"name": "like-move-win64.zip", "browser_download_url": "u2"},
        ]
        self.assertEqual(updater._pick_asset(assets)["browser_download_url"], "u2")

    def test_no_zip_means_no_asset(self):
        self.assertIsNone(updater._pick_asset([{"name": "like-move.exe", "browser_download_url": "u"}]))


class StageUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.install = os.path.join(self.root, "like-move")
        os.makedirs(os.path.join(self.install, "_internal"))
        open(os.path.join(self.install, "like-move.exe"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_extracts_next_to_current_install_without_touching_it(self):
        z = os.path.join(self.root, "u.zip")
        make_zip(z, {"like-move/like-move.exe": "new", "like-move/_internal/x.dll": "d"})
        exe = updater.stage_update(z, self.install, "1.2.0")
        self.assertEqual(exe, os.path.join(self.root, "like-move-1.2.0", "like-move.exe"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "like-move-1.2.0", "_internal", "x.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install, "like-move.exe")))

    def test_existing_target_gets_a_new_name(self):
        os.makedirs(os.path.join(self.root, "like-move-1.2.0"))
        z = os.path.join(self.root, "u.zip")
        make_zip(z, {"like-move/like-move.exe": "new"})
        exe = updater.stage_update(z, self.install, "1.2.0")
        self.assertEqual(exe, os.path.join(self.root, "like-move-1.2.0-2", "like-move.exe"))

    def test_zip_without_exe_is_refused(self):
        z = os.path.join(self.root, "u.zip")
        make_zip(z, {"like-move/readme.txt": "x"})
        with self.assertRaises(ValueError):
            updater.stage_update(z, self.install, "1.2.0")

    def test_no_helper_script_is_written(self):
        z = os.path.join(self.root, "u.zip")
        make_zip(z, {"like-move/like-move.exe": "new"})
        updater.stage_update(z, self.install, "1.2.0")
        for _, _, files in os.walk(self.root):
            self.assertFalse([f for f in files if f.endswith((".bat", ".cmd"))])


class CleanupPreviousTest(unittest.TestCase):
    def test_removes_only_like_move_files_and_keeps_user_files(self):
        with tempfile.TemporaryDirectory() as root:
            old = os.path.join(root, "Downloads")
            os.makedirs(os.path.join(old, "_internal"))
            open(os.path.join(old, "like-move.exe"), "w").close()
            open(os.path.join(old, "foto.jpg"), "w").close()
            self.assertTrue(updater.cleanup_previous(old, timeout=1))
            self.assertEqual(os.listdir(old), ["foto.jpg"])

    def test_removes_the_folder_when_it_holds_only_like_move(self):
        with tempfile.TemporaryDirectory() as root:
            old = os.path.join(root, "like-move")
            os.makedirs(os.path.join(old, "_internal"))
            open(os.path.join(old, "like-move.exe"), "w").close()
            updater.cleanup_previous(old, timeout=1)
            self.assertFalse(os.path.exists(old))


if __name__ == "__main__":
    unittest.main()
