"""Testes do menu da bandeja para "Programas vigiados" e "CPU ocupada".

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import tray  # noqa: E402


def text_of(item):
    return item.text(item) if callable(item.text) else item.text


class TrayTriggersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = tray.TrayApp()
        self.app._icon = mock.Mock()
        self.app._monitor = SimpleNamespace(status="x", notifier=None)

    def top(self):
        return {text_of(i): i for i in self.app._build_menu().items}

    def watched_labels(self):
        return [text_of(i) for i in self.top()["Programas vigiados"].submenu.items]

    def test_menu_has_both_entries(self):
        top = self.top()
        self.assertIn("Programas vigiados", top)
        self.assertIn("CPU ocupada", top)

    def test_empty_watch_list_says_so_and_hides_the_clear_item(self):
        items = self.top()["Programas vigiados"].submenu.items
        self.assertEqual(text_of(items[0]), "Nenhum programa vigiado")
        clear = next(i for i in items if text_of(i) == "Parar de vigiar todos")
        self.assertFalse(clear.visible)

    def test_choosing_a_program_watches_it_and_saves(self):
        self.app._on_watch("Blender")(None, None)
        self.assertEqual(self.app._state.watched_processes, ["blender.exe"])
        self.assertIn("blender.exe", self.watched_labels())
        self.app._icon.update_menu.assert_called()

    def test_clicking_a_watched_program_stops_watching_it(self):
        self.app._state.watched_processes = ["blender.exe", "code.exe"]
        item = next(i for i in self.top()["Programas vigiados"].submenu.items if text_of(i) == "blender.exe")
        self.assertTrue(item.checked)
        item(self.app._icon)
        self.assertEqual(self.app._state.watched_processes, ["code.exe"])

    def test_clear_all(self):
        self.app._state.watched_processes = ["a.exe", "b.exe"]
        self.app._on_clear_watched(None, None)
        self.assertEqual(self.app._state.watched_processes, [])

    def test_candidates_skip_programs_already_watched(self):
        self.app._state.watched_processes = ["chrome.exe"]
        with mock.patch.object(tray, "visible_window_process_names", return_value=["chrome.exe", "code.exe"]):
            labels = [text_of(i) for i in self.app._candidate_menu_items()]
        self.assertEqual(labels, ["code.exe"])

    def test_candidates_say_so_when_there_is_none(self):
        with mock.patch.object(tray, "visible_window_process_names", return_value=[]):
            items = self.app._candidate_menu_items()
        self.assertEqual([text_of(i) for i in items], ["Nenhum programa com janela aberta"])
        self.assertFalse(items[0].enabled)

    def test_failure_to_list_windows_is_logged_and_shown(self):
        with mock.patch.object(tray, "visible_window_process_names", side_effect=OSError("x")), \
                self.assertLogs(tray.logger, "ERROR"):
            items = self.app._candidate_menu_items()
        self.assertEqual([text_of(i) for i in items], ["Não consegui listar os programas"])

    def test_candidate_list_is_capped_and_says_how_many_were_left_out(self):
        names = [f"p{i}.exe" for i in range(40)]
        with mock.patch.object(tray, "visible_window_process_names", return_value=names):
            items = self.app._candidate_menu_items()
        self.assertEqual(len(items), tray.MAX_CANDIDATE_PROGRAMS + 1)
        self.assertEqual(text_of(items[-1]), "… e mais 10")
        self.assertFalse(items[-1].enabled)

    def test_windows_shell_programs_are_not_offered(self):
        with mock.patch.object(tray, "visible_window_process_names", return_value=["applicationframehost.exe", "code.exe"]):
            self.assertEqual([text_of(i) for i in self.app._candidate_menu_items()], ["code.exe"])

    def test_watching_the_same_program_twice_keeps_one_entry(self):
        self.app._on_watch("code")(None, None)
        self.app._on_watch("Code.exe")(None, None)
        self.assertEqual(self.app._state.watched_processes, ["code.exe"])

    def test_cpu_options_are_radio_items_with_the_current_one_checked(self):
        items = self.top()["CPU ocupada"].submenu.items
        self.assertEqual([text_of(i) for i in items], ["Desligado", "Acima de 25%", "Acima de 50%", "Acima de 75%"])
        self.assertTrue(items[0].checked)
        self.app._on_set_cpu_threshold(50)(None, None)
        self.assertEqual(self.app._state.cpu_threshold, 50)
        items = self.top()["CPU ocupada"].submenu.items
        self.assertTrue(items[2].checked)
        self.assertFalse(items[0].checked)


if __name__ == "__main__":
    unittest.main()
