"""Prazo para manter o PC acordado: cálculo puro do fim e do texto restante (sem relógio próprio).

O prazo é um instante em epoch (``0.0`` = sem prazo). Quem chama passa o "agora", o que mantém as
funções testáveis e sem depender do relógio do sistema.
"""

import datetime as dt
import re
from typing import Optional

_CLOCK = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def deadline_after(minutes: int, now: dt.datetime) -> float:
    """Instante (epoch) em que termina um prazo de ``minutes`` minutos contados a partir de ``now``."""
    return now.timestamp() + minutes * 60


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


def _clock_minutes(value: object) -> Optional[int]:
    """Minutos desde 00:00 de um texto ``HH:MM`` (00:00 a 23:59); ``None`` se o formato não é esse."""
    match = _CLOCK.fullmatch(value) if isinstance(value, str) else None
    return int(match[1]) * 60 + int(match[2]) if match else None


def parse_work_hours(cfg: object) -> Optional[dict]:
    """Horário de trabalho validado e normalizado (dias ordenados e sem repetição); ``None`` se a configuração está malformada."""
    if not isinstance(cfg, dict):
        return None
    enabled, days = cfg.get("enabled"), cfg.get("days")
    if not isinstance(enabled, bool) or not isinstance(days, list):
        return None
    if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        return None
    start, end = cfg.get("start"), cfg.get("end")
    if _clock_minutes(start) is None or _clock_minutes(end) is None:
        return None
    return {"enabled": enabled, "days": sorted(set(days)), "start": start, "end": end}


def in_work_hours(cfg: object, now: dt.datetime) -> bool:
    """True se ``now`` cai dentro do horário de trabalho ligado: início inclusivo, fim exclusivo, dias da semana de 0 (segunda) a 6.

    Com ``end <= start`` a janela termina no dia seguinte e pertence ao dia em que começou. Configuração desligada ou malformada dá False.
    """
    parsed = parse_work_hours(cfg)
    if not parsed or not parsed["enabled"]:
        return False
    start, end = _clock_minutes(parsed["start"]), _clock_minutes(parsed["end"])
    minute = now.hour * 60 + now.minute
    today = now.weekday()
    if start < end:
        return today in parsed["days"] and start <= minute < end
    if minute >= start:
        return today in parsed["days"]
    return minute < end and (today - 1) % 7 in parsed["days"]
