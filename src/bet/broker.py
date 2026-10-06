"""Esecuzione simulata (paper trading) degli ordini contro le quote osservate."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .market import MarketBook

PENDING, OPEN, DONE, CANCELLED = "in_ritardo", "aperto", "eseguito", "annullato"


@dataclass(eq=False)
class Order:
    id: int
    market_id: str
    selection_id: int
    side: str
    price: float
    size: float
    strategy: str
    purpose: str
    """'ingresso' o 'uscita'."""
    placed_at: float
    active_at: float
    """Istante in cui l'ordine entra nel mercato, dopo il ritardo in-play."""
    cancel_after: float | None
    """Secondi dopo l'attivazione oltre i quali la parte non abbinata viene annullata."""
    matched: float = 0.0
    status: str = PENDING
    rested: bool = False
    """Vero dopo il primo tentativo di abbinamento: da lì l'ordine aspetta nel book al suo prezzo."""

    @property
    def is_open(self) -> bool:
        return self.status in (PENDING, OPEN)

    @property
    def remaining(self) -> float:
        return round(self.size - self.matched, 2)

    @property
    def cancel_at(self) -> float | None:
        return None if self.cancel_after is None else self.active_at + self.cancel_after


@dataclass(frozen=True)
class Fill:
    order: Order
    price: float
    size: float
    time: float


@dataclass(frozen=True)
class Cancelled:
    order: Order
    time: float


class PaperBroker:
    """Abbina gli ordini contro il primo livello del book.

    Approssimazioni (ottimistiche, da tenere presenti leggendo i risultati):
    - all'attivazione l'ordine trova tutta la liquidità mostrata alla migliore quota, o a una migliore;
    - un ordine rimasto in attesa viene abbinato al suo prezzo appena il mercato lo raggiunge,
      senza la coda di chi era già a quel prezzo.
    """

    def __init__(self) -> None:
        self.orders: list[Order] = []
        self._ids = itertools.count(1)
        self._used: dict[str, tuple[MarketBook, dict[tuple[int, str], float]]] = {}

    def place(
        self,
        *,
        market_id: str,
        selection_id: int,
        side: str,
        price: float,
        size: float,
        strategy: str,
        purpose: str,
        now: float,
        delay: float,
        cancel_after: float | None,
    ) -> Order:
        order = Order(
            next(self._ids), market_id, selection_id, side, price, round(size, 2),
            strategy, purpose, now, now + delay, cancel_after,
        )
        self.orders.append(order)
        return order

    def cancel(self, order: Order, now: float) -> Cancelled:
        order.status = CANCELLED
        return Cancelled(order, now)

    def cancel_all(self, market_id: str, now: float) -> list[Cancelled]:
        return [self.cancel(o, now) for o in self.orders if o.is_open and o.market_id == market_id]

    def next_time(self, before: float) -> float | None:
        """Primo istante prima di `before` in cui un ordine si attiva o va annullato."""
        times = [o.active_at for o in self.orders if o.status == PENDING]
        times += [o.cancel_at for o in self.orders if o.status == OPEN and o.cancel_at is not None]
        return min((t for t in times if t < before), default=None)

    def process(self, book: MarketBook, now: float) -> list[Fill | Cancelled]:
        """Attiva, abbina e annulla gli ordini del mercato di `book` all'istante `now`."""
        events: list[Fill | Cancelled] = []
        used = self._liquidity_used(book)
        for order in self.orders:
            if order.market_id != book.market_id or not order.is_open:
                continue
            if order.status == PENDING:
                if now < order.active_at:
                    continue
                order.status = OPEN
            if book.status == "CLOSED":
                events.append(self.cancel(order, now))
                continue
            if book.status == "OPEN":
                fill = self._match(order, book, used, now)
                if fill is not None:
                    events.append(fill)
            if order.is_open and order.cancel_at is not None and now >= order.cancel_at:
                events.append(self.cancel(order, now))
        return events

    def _liquidity_used(self, book: MarketBook) -> dict[tuple[int, str], float]:
        """Liquidità già presa dagli ordini simulati su questa fotografia del book."""
        seen = self._used.get(book.market_id)
        if seen is None or seen[0] is not book:
            seen = (book, {})
            self._used[book.market_id] = seen
        return seen[1]

    def _match(self, order: Order, book: MarketBook, used: dict[tuple[int, str], float], now: float) -> Fill | None:
        first_try = not order.rested
        order.rested = True
        runner = book.runners.get(order.selection_id)
        if runner is None:
            return None
        if order.side == "BACK":
            best, size = runner.back_price, runner.back_size
            reachable = best is not None and best >= order.price
        else:
            best, size = runner.lay_price, runner.lay_size
            reachable = best is not None and best <= order.price
        if not reachable:
            return None
        key = (order.selection_id, order.side)
        quantity = round(min(order.remaining, size - used.get(key, 0.0)), 2)
        if quantity <= 0:
            return None
        used[key] = used.get(key, 0.0) + quantity
        order.matched = round(order.matched + quantity, 2)
        if order.remaining <= 0:
            order.status = DONE
        return Fill(order, best if first_try else order.price, quantity, now)
