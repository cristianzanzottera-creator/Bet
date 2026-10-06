"""Scala delle quote (tick) dell'exchange Betfair."""

from __future__ import annotations

from bisect import bisect_left

# Fasce di quota in centesimi: (da, a escluso, passo)
_BANDS = (
    (101, 200, 1),
    (200, 300, 2),
    (300, 400, 5),
    (400, 600, 10),
    (600, 1000, 20),
    (1000, 2000, 50),
    (2000, 3000, 100),
    (3000, 5000, 200),
    (5000, 10000, 500),
    (10000, 100000, 1000),
)

LADDER: tuple[float, ...] = tuple(
    [cents / 100 for start, end, step in _BANDS for cents in range(start, end, step)] + [1000.0]
)


def index(price: float) -> int:
    """Posizione di `price` nella scala; errore se non è una quota valida."""
    rounded = round(price, 2)
    i = bisect_left(LADDER, rounded)
    if i == len(LADDER) or LADDER[i] != rounded:
        raise ValueError(f"{price} non è una quota della scala Betfair")
    return i


def is_valid(price: float) -> bool:
    try:
        index(price)
    except ValueError:
        return False
    return True


def move(price: float, ticks: int) -> float:
    """Sposta la quota di `ticks` tick (positivo = quota più alta), entro i limiti della scala."""
    i = min(max(index(price) + ticks, 0), len(LADDER) - 1)
    return LADDER[i]


def ticks_between(low: float, high: float) -> int:
    return index(high) - index(low)
