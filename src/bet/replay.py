"""Simulazione: riproduce uno scenario di partita (punteggio e quote nel tempo) e fa girare le strategie."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import ladder
from .engine import Engine, Log, Result
from .errors import InputError, format_errors, load_yaml
from .market import MarketBook, Match, Player, RunnerBook, eur
from .tennis import TennisScore, format_score, parse_points, parse_score

Side = Literal["A", "B"]
_SIDES: tuple[Side, Side] = ("A", "B")
_NUMBER = r"(\d+(?:\.\d+)?)"
_PRICES = re.compile(rf"{_NUMBER}\s*/\s*{_NUMBER}(?:\s*@\s*{_NUMBER}\s*/\s*{_NUMBER})?")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Prices(_Model):
    """Migliori quote di un giocatore. In forma breve: '3.40/3.45 @ 120/80' (back/lay @ € back/€ lay)."""

    back: float | None = None
    lay: float | None = None
    liq_back: float = Field(0.0, ge=0)
    liq_lay: float = Field(0.0, ge=0)
    ltp: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        m = _PRICES.fullmatch(value.strip())
        if m is None:
            raise ValueError(f"quote non valide '{value}': formato 'back/lay @ €back/€lay', es. '3.40/3.45 @ 120/80'")
        back, lay, liq_back, liq_lay = m.groups()
        return {"back": float(back), "lay": float(lay), "liq_back": float(liq_back or 0), "liq_lay": float(liq_lay or 0)}

    @model_validator(mode="after")
    def _check(self) -> Prices:
        for price in (self.back, self.lay, self.ltp):
            if price is not None and not ladder.is_valid(price):
                raise ValueError(f"{price} non è una quota della scala Betfair")
        if self.back is not None and self.lay is not None and self.back >= self.lay:
            raise ValueError(f"la quota back ({self.back}) deve essere minore della quota lay ({self.lay})")
        return self


class PlayerSpec(_Model):
    nome: str
    id: int


class MatchSpec(_Model):
    mercato_id: str
    evento: str
    competizione: str | None = None
    ritardo_inplay: float = Field(0.0, ge=0)
    giocatori: dict[Side, PlayerSpec]

    @field_validator("giocatori")
    @classmethod
    def _both_players(cls, value: dict[Side, PlayerSpec]) -> dict[Side, PlayerSpec]:
        if set(value) != {"A", "B"}:
            raise ValueError("servono i giocatori A e B")
        return value


class Event(_Model):
    t: float
    """Secondi dall'inizio, oppure 'mm:ss' / 'h:mm:ss'; negativo = prima dell'inizio."""
    in_play: bool | None = None
    stato: Literal["OPEN", "SUSPENDED", "CLOSED"] | None = None
    punteggio: str | None = None
    punti: str | None = None
    servizio: Side | None = None
    quote: dict[Side, Prices] | None = None
    volume: float | None = Field(None, ge=0)
    nota: str | None = None
    vincitore: Side | None = None

    @field_validator("t", mode="before")
    @classmethod
    def _time(cls, value: Any) -> float:
        return parse_time(value)

    @field_validator("punteggio")
    @classmethod
    def _score(cls, value: str | None) -> str | None:
        if value is not None:
            parse_score(value)
        return value


class Scenario(_Model):
    partita: MatchSpec
    eventi: list[Event] = Field(min_length=1)


def parse_time(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("tempo non valido")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    sign = -1.0 if text.startswith("-") else 1.0
    parts = text.lstrip("+-").split(":")
    try:
        if len(parts) > 3:
            raise ValueError
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
    except ValueError:
        raise ValueError(f"tempo non valido '{value}': usa i secondi oppure 'mm:ss' / 'h:mm:ss'") from None
    return sign * seconds


def format_time(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    hours, rest = divmod(int(round(abs(seconds))), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{sign}{hours}:{minutes:02d}:{secs:02d}" if hours else f"{sign}{minutes:02d}:{secs:02d}"


def load_scenario(path: Path) -> Scenario:
    try:
        return Scenario.model_validate(load_yaml(path))
    except ValidationError as exc:
        raise InputError(f"{path}: scenario non valido\n{format_errors(exc)}") from None


def run_scenario(scenario: Scenario, engine: Engine, log: Log) -> list[Result]:
    """Riproduce gli eventi in ordine di tempo e, all'evento con il vincitore, chiude la partita."""
    spec = scenario.partita
    players = {side: Player(spec.giocatori[side].nome, spec.giocatori[side].id) for side in _SIDES}
    match = Match(spec.mercato_id, spec.evento, spec.competizione, (players["A"], players["B"]))
    events = sorted(scenario.eventi, key=lambda e: e.t)
    log(events[0].t, f"{spec.evento} — {spec.competizione or 'competizione non indicata'} — mercato {spec.mercato_id}")
    engine.add_match(match, events[0].t)
    market = _MarketState(spec)
    score = _ScoreState()
    for event in events:
        engine.advance_to(event.t)
        book = market.apply(event)
        new_score = score.apply(event)
        log(event.t, _describe(event, new_score, market, players))
        if event.vincitore is not None:
            return engine.settle(spec.mercato_id, players[event.vincitore].selection_id, event.t)
        engine.update(spec.mercato_id, event.t, book=book, score=new_score)
    raise InputError("lo scenario non indica il vincitore: aggiungi 'vincitore: A' (o B) all'ultimo evento")


class _MarketState:
    """Quote correnti: ogni evento aggiorna solo ciò che indica."""

    def __init__(self, spec: MatchSpec) -> None:
        self.spec = spec
        self.prices: dict[Side, dict[str, Any]] = {"A": {}, "B": {}}
        self.in_play = False
        self.status = "OPEN"
        self.volume = 0.0

    def apply(self, event: Event) -> MarketBook | None:
        if event.in_play is None and event.stato is None and event.volume is None and not event.quote:
            return None
        if event.in_play is not None:
            self.in_play = event.in_play
        if event.stato is not None:
            self.status = event.stato
        if event.volume is not None:
            self.volume = event.volume
        for side, prices in (event.quote or {}).items():
            merged = {**self.prices[side], **prices.model_dump(exclude_unset=True)}
            try:
                Prices.model_validate(merged)
            except ValidationError as exc:
                raise InputError(f"evento a {format_time(event.t)}, quote di {side}:\n{format_errors(exc)}") from None
            self.prices[side] = merged
        runners = {}
        for side in _SIDES:
            p, sid = self.prices[side], self.spec.giocatori[side].id
            runners[sid] = RunnerBook(
                sid, p.get("back"), p.get("liq_back", 0.0), p.get("lay"), p.get("liq_lay", 0.0), p.get("ltp")
            )
        return MarketBook(
            self.spec.mercato_id, runners, in_play=self.in_play, status=self.status, total_matched=self.volume,
            bet_delay=self.spec.ritardo_inplay if self.in_play else 0.0,
        )


class _ScoreState:
    """Punteggio corrente. Il servizio, indicato una volta, si alterna da solo a ogni game."""

    def __init__(self) -> None:
        self.score: TennisScore | None = None
        self.anchor: tuple[int, int] | None = None
        """(game giocati, chi serviva) nell'ultimo evento che indicava il servizio."""

    def apply(self, event: Event) -> TennisScore | None:
        if event.punteggio is None and event.punti is None and event.servizio is None:
            return None
        if event.punteggio is not None:
            score = parse_score(event.punteggio)
        else:
            score = self.score or TennisScore()
        if event.punti is not None:
            try:
                score = replace(score, points=parse_points(event.punti, score.in_tiebreak))
            except ValueError as exc:
                raise InputError(f"evento a {format_time(event.t)}: {exc}") from None
        if event.servizio is not None:
            self.anchor = (score.total_games, _SIDES.index(event.servizio))
        if self.anchor is not None:
            played, server = self.anchor
            score = replace(score, server=server if (score.total_games - played) % 2 == 0 else 1 - server)
        self.score = score
        return score


def _describe(event: Event, score: TennisScore | None, market: _MarketState, players: dict[Side, Player]) -> str:
    parts = []
    if event.in_play:
        parts.append("in gioco")
    if event.vincitore and event.punteggio:
        parts.append(event.punteggio)
    elif score is not None:
        text = format_score(score)
        if score.server is not None:
            text += f", serve {players[_SIDES[score.server]].name}"
        parts.append(text)
    if event.quote:
        quotes = []
        for side in _SIDES:
            p = market.prices[side]
            if p.get("back") is not None:
                quotes.append(f"{players[side].name} {p['back']:.2f} ({p.get('liq_back', 0):.0f} €)")
        parts.append("quote back " + " | ".join(quotes))
    if event.volume is not None:
        parts.append(f"abbinati {eur(event.volume)}")
    if event.stato:
        parts.append(f"mercato {event.stato}")
    if event.nota:
        parts.append(event.nota)
    if event.vincitore:
        parts.append(f"FINE: vince {players[event.vincitore].name}")
    return " · ".join(parts)
