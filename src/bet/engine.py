"""Motore: a ogni aggiornamento di quote o punteggio valuta le strategie, piazza gli ordini,
segue gli abbinamenti e chiude le posizioni."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import ladder
from .broker import Cancelled, Fill, Order, PaperBroker
from .config import Settings
from .context import build_context
from .expr import Expression, ExpressionError
from .market import MarketBook, Match
from .position import Position
from .strategy import Entry, Strategy
from .tennis import TennisScore

Log = Callable[[float, str], None]
ENTRY, EXIT = "ingresso", "uscita"


@dataclass
class _State:
    """Stato di una strategia su una partita."""

    excluded: str | None = None
    settled: bool = False
    positions: dict[int, Position] = field(default_factory=dict)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    exiting: set[int] = field(default_factory=set)

    def open_orders(self, purpose: str, selection_id: int | None = None) -> list[Order]:
        return [
            o for o in self.orders
            if o.is_open and o.purpose == purpose and selection_id in (None, o.selection_id)
        ]


@dataclass(frozen=True)
class Result:
    """Esito di una strategia su una partita conclusa."""

    strategy: str
    market_id: str
    gross: float
    commission: float
    fills: tuple[Fill, ...]

    @property
    def net(self) -> float:
        return round(self.gross - self.commission, 2)


class Engine:
    def __init__(self, strategies: Sequence[Strategy], settings: Settings, broker: PaperBroker, log: Log) -> None:
        self.strategies = [s for s in strategies if s.enabled]
        self.settings = settings
        self.broker = broker
        self.log = log
        self.matches: dict[str, Match] = {}
        self._states: dict[tuple[str, str], _State] = {}
        self._reasons: dict[tuple[Any, ...], str] = {}

    def add_match(self, match: Match, now: float) -> None:
        self.matches[match.market_id] = match
        for s in self.strategies:
            reason = s.market.rejects(match)
            self._states[match.market_id, s.label] = _State(excluded=reason)
            if reason:
                self.log(now, f"{s.label}: partita ignorata ({reason})")

    def update(
        self, market_id: str, now: float, book: MarketBook | None = None, score: TennisScore | None = None
    ) -> None:
        """Nuove quote e/o nuovo punteggio per una partita."""
        match = self.matches[market_id]
        if book is not None:
            match.update_book(book)
        if score is not None:
            match.score = score
        self._sync(match, now)
        if match.book is None or match.book.status != "OPEN":
            return
        for s in self.strategies:
            state = self._states[market_id, s.label]
            if state.excluded is None and not state.settled:
                self._manage_exits(s, state, match, now)
                self._try_entry(s, state, match, now)
        self._sync(match, now)

    def advance_to(self, now: float) -> None:
        """Esegue le attivazioni e gli annullamenti di ordini previsti prima di `now`, sulle quote correnti."""
        last = None
        while (t := self.broker.next_time(before=now)) is not None and t != last:
            last = t
            for match in self.matches.values():
                self._sync(match, t)

    def fills(self, market_id: str) -> list[Fill]:
        """Abbinamenti di tutte le strategie su una partita, in ordine di tempo."""
        fills = [f for (mid, _), state in self._states.items() if mid == market_id for f in state.fills]
        return sorted(fills, key=lambda f: f.time)

    def settle(self, market_id: str, winner_id: int, now: float) -> list[Result]:
        """Chiude la partita: annulla gli ordini aperti e calcola il risultato di ogni strategia.

        La commissione è calcolata per strategia; Betfair la applica al netto del mercato per
        conto, quindi con più strategie sulla stessa partita il valore reale può essere minore.
        """
        match = self.matches[market_id]
        for event in self.broker.cancel_all(market_id, now):
            self._on_order_event(match, event)
        results = []
        for s in self.strategies:
            state = self._states[market_id, s.label]
            if state.excluded is not None:
                continue
            state.settled = True
            gross = round(sum(p.profit(sid == winner_id) for sid, p in state.positions.items()), 2)
            commission = round(gross * self.settings.commission, 2) if gross > 0 else 0.0
            result = Result(s.label, market_id, gross, commission, tuple(state.fills))
            results.append(result)
            if state.fills:
                self.log(
                    now,
                    f"{s.label}: risultato {gross:+.2f} € lordi, commissione {commission:.2f} €, "
                    f"netto {result.net:+.2f} €",
                )
            else:
                self.log(now, f"{s.label}: nessuna scommessa su questa partita")
        return results

    # --- ingresso -----------------------------------------------------------------------

    def _try_entry(self, s: Strategy, state: _State, match: Match, now: float) -> None:
        entry = s.entry
        if state.open_orders(ENTRY):
            return
        if sum(1 for o in state.orders if o.purpose == ENTRY and o.matched > 0) >= entry.max_entries:
            return
        for i, player in enumerate(match.players):
            if not s.market.allows_player(player.name) or player.selection_id in state.exiting:
                continue
            key = (s.label, match.market_id, player.selection_id, ENTRY)
            values = build_context(match, i, state.positions.get(player.selection_id))
            if not self._holds(s, s.when, values, now):
                self._reasons.pop(key, None)
                continue
            who = f"{s.label} · {player.name}"
            runner = match.runner(i)
            if runner is None:
                continue
            if entry.side == "BACK":
                price, size = runner.back_price, runner.back_size
            else:
                price, size = runner.lay_price, runner.lay_size
            if price is None:
                self._note(key, "quota", now, f"{who}: condizione vera ma nessuna quota {entry.side} disponibile")
                continue
            if size < entry.min_liquidity:
                self._note(
                    key, "liquidita", now,
                    f"{who}: condizione vera, ma a {price:.2f} ci sono solo {size:.0f} € "
                    f"(minimo {entry.min_liquidity:g} €): attendo",
                )
                continue
            ticks = entry.improve_ticks if entry.side == "BACK" else -entry.improve_ticks
            target = ladder.move(price, ticks)
            stake = self._stake(entry, target)
            if stake < self.settings.min_stake:
                self._note(
                    key, "minimo", now,
                    f"{who}: puntata {stake:.2f} € sotto il minimo di {self.settings.min_stake:.2f} €",
                )
                continue
            liability = stake if entry.side == "BACK" else stake * (target - 1)
            limit = self.settings.max_exposure
            if limit is not None and self._exposure() + liability > limit:
                self._note(key, "esposizione", now, f"{who}: condizione vera, ma supererei l'esposizione massima di {limit:g} €")
                continue
            self._reasons.pop(key, None)
            delay = match.book.bet_delay if match.book else 0.0
            order = self.broker.place(
                market_id=match.market_id, selection_id=player.selection_id, side=entry.side,
                price=target, size=stake, strategy=s.label, purpose=ENTRY, now=now, delay=delay,
                cancel_after=entry.cancel_after,
            )
            state.orders.append(order)
            timing = f"entra nel mercato dopo {delay:g} s di ritardo in-play" if delay else "immediato"
            self.log(
                now,
                f"{who}: ORDINE {entry.side} {stake:.2f} € @ {target:.2f} "
                f"(liquidità {size:.0f} €, {timing}) — condizione: {s.when.source}",
            )
            return

    def _stake(self, entry: Entry, price: float) -> float:
        if entry.stake_mode == "percentuale_bankroll":
            stake = self.settings.bankroll * entry.stake / 100
        elif entry.stake_mode == "responsabilita" and entry.side == "LAY":
            stake = entry.stake / (price - 1)
        else:
            stake = entry.stake
        return round(stake, 2)

    def _exposure(self) -> float:
        """Perdita massima possibile: posizioni aperte più ordini non ancora abbinati (stima prudente)."""
        total = 0.0
        for state in self._states.values():
            if state.settled:
                continue
            total += sum(max(0.0, -min(p.if_win, p.if_lose)) for p in state.positions.values())
            for o in state.orders:
                if o.is_open:
                    total += o.remaining if o.side == "BACK" else o.remaining * (o.price - 1)
        return total

    # --- uscita -------------------------------------------------------------------------

    def _manage_exits(self, s: Strategy, state: _State, match: Match, now: float) -> None:
        if s.exit is None:
            return
        for i, player in enumerate(match.players):
            sid = player.selection_id
            position = state.positions.get(sid)
            if position is None or state.open_orders(EXIT, sid):
                continue
            runner = match.runner(i)
            hedge = position.hedge(runner.back_price, runner.lay_price) if runner is not None else None
            if hedge is not None and hedge.stake < 0.01:
                state.exiting.discard(sid)
                continue
            who = f"{s.label} · {player.name}"
            key = (s.label, match.market_id, sid, EXIT)
            if sid not in state.exiting:
                if not self._holds(s, s.exit.when, build_context(match, i, position), now):
                    continue
                state.exiting.add(sid)
                self.log(now, f"{who}: condizione di uscita vera ({s.exit.when.source}), chiudo la posizione")
                for order in state.open_orders(ENTRY, sid):
                    self._on_order_event(match, self.broker.cancel(order, now))
            if hedge is None:
                self._note(key, "quota", now, f"{who}: nessuna quota per chiudere, riprovo al prossimo aggiornamento")
                continue
            if hedge.stake < self.settings.min_stake:
                self._note(
                    key, "minimo", now,
                    f"{who}: per chiudere servirebbero {hedge.stake:.2f} €, sotto la puntata minima: resta aperta",
                )
                continue
            self._reasons.pop(key, None)
            order = self.broker.place(
                market_id=match.market_id, selection_id=sid, side=hedge.side, price=hedge.price,
                size=hedge.stake, strategy=s.label, purpose=EXIT, now=now,
                delay=match.book.bet_delay if match.book else 0.0, cancel_after=s.exit.cancel_after,
            )
            state.orders.append(order)
            self.log(
                now,
                f"{who}: ORDINE {hedge.side} {hedge.stake:.2f} € @ {hedge.price:.2f} per chiudere "
                f"(risultato garantito {hedge.locked_profit:+.2f} €)",
            )

    # --- ordini e messaggi --------------------------------------------------------------

    def _sync(self, match: Match, now: float) -> None:
        if match.book is None:
            return
        for event in self.broker.process(match.book, now):
            self._on_order_event(match, event)

    def _on_order_event(self, match: Match, event: Fill | Cancelled) -> None:
        order = event.order
        state = self._states[order.market_id, order.strategy]
        who = f"{order.strategy} · {match.player_name(order.selection_id)}"
        if isinstance(event, Cancelled):
            if order.matched:
                self.log(event.time, f"{who}: annullata la parte non abbinata ({order.remaining:.2f} €)")
            else:
                self.log(event.time, f"{who}: ordine {order.side} @ {order.price:.2f} annullato, non abbinato")
            return
        position = state.positions.setdefault(order.selection_id, Position(order.side))
        position.add(order.side, event.price, event.size)
        state.fills.append(event)
        self.log(event.time, f"{who}: ABBINATO {order.side} {event.size:.2f} € @ {event.price:.2f} ({order.purpose})")
        if order.purpose == EXIT:
            residual = position.hedge(event.price, event.price)
            if residual is not None and residual.stake < 0.01:
                state.exiting.discard(order.selection_id)
                locked = min(position.if_win, position.if_lose)
                self.log(event.time, f"{who}: posizione chiusa, risultato garantito {locked:+.2f} € prima della commissione")

    def _holds(self, s: Strategy, expression: Expression, values: dict[str, object], now: float) -> bool:
        try:
            return expression.evaluate(values)
        except ExpressionError as exc:
            self._note((s.label, expression.source), "errore", now, f"{s.label}: {exc} — la considero falsa")
            return False

    def _note(self, key: tuple[Any, ...], reason: str, now: float, message: str) -> None:
        """Scrive un messaggio di attesa solo quando il motivo cambia, per non ripeterlo a ogni aggiornamento."""
        if self._reasons.get(key) != reason:
            self._reasons[key] = reason
            self.log(now, message)
