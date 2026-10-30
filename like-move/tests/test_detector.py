"""Testes da detecção de inatividade (cálculo em 32 bits do tick).

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from like_move import detector  # noqa: E402
from like_move.detector import idle_ms_since  # noqa: E402

DWORD = 2**32


class IdleMsSince(unittest.TestCase):
    def test_intervalo_normal(self):
        self.assertEqual(idle_ms_since(1_000, 31_000), 30_000)

    def test_sem_inatividade(self):
        self.assertEqual(idle_ms_since(5_000, 5_000), 0)

    def test_tick_atual_passou_da_volta_do_dword(self):
        # Último input pouco antes da volta (49,7 dias); agora, 40 s depois, o tick de 32 bits já recomeçou.
        last_input = DWORD - 10_000
        now = DWORD + 30_000   # GetTickCount64 não volta; só a visão de 32 bits volta
        self.assertEqual(idle_ms_since(last_input, now), 40_000)

    def test_uptime_de_meses_com_input_recente(self):
        # 100 dias de uptime: o tick de 64 bits é grande e o último input foi há 5 s.
        now = 100 * 24 * 3600 * 1000
        self.assertEqual(idle_ms_since((now - 5_000) % DWORD, now), 5_000)

    def test_uptime_de_meses_sem_input_ha_dois_minutos(self):
        now = 200 * 24 * 3600 * 1000
        self.assertEqual(idle_ms_since((now - 120_000) % DWORD, now), 120_000)


class GetIdleTimeMs(unittest.TestCase):
    def _idle(self, last_input_tick, current_tick):
        def fill(byref_arg):
            byref_arg._obj.dwTime = last_input_tick
            return 1

        with mock.patch.object(detector.user32, "GetLastInputInfo", side_effect=fill), \
                mock.patch.object(detector.kernel32, "GetTickCount64", return_value=current_tick):
            return detector.get_idle_time_ms()

    def test_usa_os_dois_ticks_com_a_volta_do_dword(self):
        self.assertEqual(self._idle(DWORD - 10_000, DWORD + 30_000), 40_000)

    def test_falha_de_leitura_conta_como_sem_inatividade(self):
        with mock.patch.object(detector.user32, "GetLastInputInfo", return_value=0):
            self.assertEqual(detector.get_idle_time_ms(), 0)


if __name__ == "__main__":
    unittest.main()
