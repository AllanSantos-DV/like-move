"""Testes da detecção de inatividade (cálculo em 32 bits do tick).

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


if __name__ == "__main__":
    unittest.main()
