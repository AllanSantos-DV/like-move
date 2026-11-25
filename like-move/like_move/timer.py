"""Prazo para manter o PC acordado: cálculo puro do fim e do texto restante (sem relógio próprio).

O prazo é um instante em epoch (``0.0`` = sem prazo). Quem chama passa o "agora", o que mantém as
funções testáveis e sem depender do relógio do sistema.
"""

import datetime as dt


def deadline_after(minutes: int, now: dt.datetime) -> float:
    """Instante (epoch) em que termina um prazo de ``minutes`` minutos contados a partir de ``now``."""
    return (now + dt.timedelta(minutes=minutes)).timestamp()


def deadline_until(hour: int, minute: int, now: dt.datetime) -> float:
    """Próxima ocorrência de ``hour:minute``: hoje se ainda não passou, senão amanhã."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target.timestamp()


def is_active(deadline: float, now_ts: float) -> bool:
    """True enquanto o prazo existe e ainda não chegou."""
    return deadline > 0 and now_ts < deadline


def remaining_text(deadline: float, now_ts: float) -> str:
    """Tempo que falta, em texto curto para o menu: ``45 min``, ``1h30`` ou ``menos de 1 min``."""
    minutes = int((deadline - now_ts) // 60)
    if minutes < 1:
        return "menos de 1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60}h{minutes % 60:02d}"
