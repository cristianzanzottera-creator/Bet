"""Posizione su un giocatore: profitto per esito e chiusura in green."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Hedge:
    """Scommessa che rende uguale il risultato sui due esiti."""

    side: str
    price: float
    stake: float
    locked_profit: float
    """Risultato garantito dopo la copertura, prima della commissione."""


@dataclass
class Position:
    entry_side: str
    fills: list[tuple[str, float, float]] = field(default_factory=list)
    """Scommesse abbinate: (lato, quota, importo)."""

    def add(self, side: str, price: float, size: float) -> None:
        self.fills.append((side, price, size))

    @property
    def if_win(self) -> float:
        """Profitto se il giocatore vince."""
        return sum(size * (price - 1) * (1 if side == "BACK" else -1) for side, price, size in self.fills)

    @property
    def if_lose(self) -> float:
        """Profitto se il giocatore perde."""
        return sum(-size if side == "BACK" else size for side, _, size in self.fills)

    @property
    def stake(self) -> float:
        """€ abbinati sul lato di ingresso."""
        return sum(size for side, _, size in self.fills if side == self.entry_side)

    @property
    def entry_price(self) -> float | None:
        stake = self.stake
        if not stake:
            return None
        return sum(price * size for side, price, size in self.fills if side == self.entry_side) / stake

    def profit(self, won: bool) -> float:
        return self.if_win if won else self.if_lose

    def hedge(self, back_price: float | None, lay_price: float | None) -> Hedge | None:
        """Copertura alle quote date; None se manca la quota che servirebbe.

        Se la posizione guadagna di più con la vittoria si banca (lay), altrimenti si punta (back).
        Una posizione già pareggiata restituisce una copertura con importo 0.
        """
        gap = self.if_win - self.if_lose
        side, price = ("LAY", lay_price) if gap > 0 else ("BACK", back_price)
        if price is None:
            return None
        stake = round(abs(gap) / price, 2)
        if side == "LAY":
            win, lose = self.if_win - stake * (price - 1), self.if_lose + stake
        else:
            win, lose = self.if_win + stake * (price - 1), self.if_lose - stake
        return Hedge(side, price, stake, round(min(win, lose), 2))
