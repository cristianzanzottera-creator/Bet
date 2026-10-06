"""Stato del mercato (quote e liquidità) e anagrafica della partita."""

from __future__ import annotations

from dataclasses import dataclass, field

from .tennis import TennisScore


@dataclass(frozen=True)
class RunnerBook:
    """Migliori prezzi di un giocatore (selezione) sul mercato."""

    selection_id: int
    back_price: float | None = None
    """Migliore quota a cui si può puntare (back)."""
    back_size: float = 0.0
    """€ disponibili a back_price."""
    lay_price: float | None = None
    """Migliore quota a cui si può bancare (lay)."""
    lay_size: float = 0.0
    last_traded: float | None = None


@dataclass(frozen=True, eq=False)
class MarketBook:
    """Fotografia del mercato in un istante."""

    market_id: str
    runners: dict[int, RunnerBook]
    in_play: bool = False
    status: str = "OPEN"
    """OPEN, SUSPENDED o CLOSED."""
    total_matched: float = 0.0
    bet_delay: float = 0.0
    """Secondi di attesa prima che un ordine entri nel mercato (betDelay di Betfair, in-play)."""


@dataclass(frozen=True)
class Player:
    name: str
    selection_id: int


@dataclass
class Match:
    """Partita seguita dal motore: anagrafica e ultimo stato noto di quote e punteggio."""

    market_id: str
    event: str
    competition: str | None
    players: tuple[Player, Player]
    book: MarketBook | None = None
    score: TennisScore | None = None
    prematch: dict[int, float] = field(default_factory=dict)
    """Ultima quota back vista prima dell'inizio, per selezione."""

    def update_book(self, book: MarketBook) -> None:
        self.book = book
        if not book.in_play:
            for selection_id, runner in book.runners.items():
                if runner.back_price is not None:
                    self.prematch[selection_id] = runner.back_price

    def runner(self, i: int) -> RunnerBook | None:
        if self.book is None:
            return None
        return self.book.runners.get(self.players[i].selection_id)

    def player_name(self, selection_id: int) -> str:
        return next((p.name for p in self.players if p.selection_id == selection_id), str(selection_id))
