"""Strategie scritte in YAML: partite su cui operare, condizione di ingresso, esecuzione, uscita."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .context import ENTRY_VARIABLES, EXIT_VARIABLES, POSITION_VARIABLES, VARIABLES
from .errors import InputError, format_errors, load_yaml
from .expr import Expression
from .market import Match, eur

_PRICE = re.compile(r"migliore(?:\s*\+\s*(\d+))?")
_EXIT_ONLY = {
    name: "si può usare solo in uscita.quando, perché richiede una posizione aperta"
    for name in POSITION_VARIABLES
}


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class MarketFilter(_Section):
    """Su quali partite opera la strategia."""

    sport: Literal["tennis"] = "tennis"
    market_type: Literal["MATCH_ODDS"] = Field("MATCH_ODDS", alias="tipo_mercato")
    circuits: list[str] = Field(default_factory=list, alias="circuito")
    """La competizione deve contenere almeno uno di questi testi (es. WTA)."""
    exclude: list[str] = Field(default_factory=list, alias="escludi")
    singles_only: bool = Field(True, alias="solo_singolare")
    players: list[str] = Field(default_factory=list, alias="solo_giocatori")
    """Se indicato, la strategia entra solo su questi giocatori (anche parte del nome)."""

    @field_validator("circuits", "exclude", "players", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    def rejects(self, match: Match) -> str | None:
        """Motivo per cui la partita va ignorata, oppure None."""
        competition = (match.competition or "").lower()
        if self.circuits and not any(c.lower() in competition for c in self.circuits):
            return f"competizione '{match.competition}' fuori da {_alternatives(self.circuits)}"
        for word in self.exclude:
            if word.lower() in competition or word.lower() in match.event.lower():
                return f"esclusa per '{word}'"
        if self.singles_only and any("/" in p.name for p in match.players):
            return "doppio"
        return None

    def allows_player(self, name: str) -> bool:
        return not self.players or any(p.lower() in name.lower() for p in self.players)

    def describe(self) -> str:
        parts = [f"tennis, mercato {self.market_type}"]
        parts.append(
            f"competizioni che contengono {_alternatives(self.circuits)}" if self.circuits else "tutte le competizioni"
        )
        if self.exclude:
            parts.append(f"escluse quelle con {_alternatives(self.exclude)}")
        if self.singles_only:
            parts.append("solo singolare")
        if self.players:
            parts.append(f"solo su {_alternatives(self.players)}")
        return ", ".join(parts) + "."


class Entry(_Section):
    """Come entrare quando la condizione è vera."""

    side: Literal["BACK", "LAY"] = Field("BACK", alias="lato")
    price: str = Field("migliore", alias="prezzo")
    """'migliore' = prende la migliore quota; 'migliore+N' = chiede N tick in più e resta in attesa."""
    min_market_volume: float = Field(0.0, ge=0, alias="liquidita_minima")
    """€ abbinati in totale sul mercato perché la strategia entri: tiene lontane le partite poco trattate."""
    min_price_liquidity: float = Field(0.0, ge=0, alias="liquidita_minima_quota")
    """€ che devono essere disponibili alla migliore quota."""
    stake: float = Field(gt=0, alias="puntata")
    stake_mode: Literal["fissa", "percentuale_bankroll", "responsabilita"] = Field("fissa", alias="tipo_puntata")
    cancel_after: float = Field(10.0, ge=0, alias="annulla_non_abbinato_dopo")
    max_entries: int = Field(1, ge=1, alias="max_ingressi_per_match")

    @field_validator("side", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("price")
    @classmethod
    def _check_price(cls, value: str) -> str:
        text = value.strip().lower()
        if _PRICE.fullmatch(text) is None:
            raise ValueError("usa 'migliore' oppure 'migliore+N' (N tick più vantaggiosi, ordine in attesa)")
        return text

    @property
    def improve_ticks(self) -> int:
        m = _PRICE.fullmatch(self.price)
        return int(m.group(1) or 0) if m else 0

    def describe(self) -> str:
        if self.improve_ticks:
            price = f"chiedendo {self.improve_ticks} tick più della migliore quota (l'ordine resta in attesa)"
        else:
            price = "alla migliore quota disponibile"
        stake = {
            "fissa": f"{self.stake:g} €",
            "percentuale_bankroll": f"{self.stake:g}% del bankroll",
            "responsabilita": f"rischio massimo {self.stake:g} €",
        }[self.stake_mode]
        requirements = []
        if self.min_market_volume:
            requirements.append(f"sul mercato sono abbinati almeno {eur(self.min_market_volume)}")
        if self.min_price_liquidity:
            requirements.append(f"alla migliore quota ci sono almeno {eur(self.min_price_liquidity)} disponibili")
        liquidity = f", solo se {' e '.join(requirements)}" if requirements else ""
        entries = "1 ingresso" if self.max_entries == 1 else f"{self.max_entries} ingressi"
        return (
            f"{self.side} sul giocatore che soddisfa la condizione, {price}{liquidity}; "
            f"puntata {stake}; parte non abbinata annullata dopo {self.cancel_after:g} s; "
            f"al massimo {entries} per partita."
        )


class Exit(_Section):
    """Quando chiudere la posizione in green (stesso risultato su entrambi gli esiti)."""

    when: Expression = Field(alias="quando")
    cancel_after: float = Field(10.0, ge=0, alias="annulla_non_abbinato_dopo")

    @field_validator("when", mode="before")
    @classmethod
    def _compile(cls, value: Any) -> Expression:
        return Expression.compile(value, EXIT_VARIABLES)


class Strategy(_Section):
    id: str | None = None
    """Nome breve usato nei log; se manca si usa il nome del file."""
    name: str = Field(alias="nome")
    outlook: str = Field("", alias="andamento")
    """L'andamento che ti aspetti, in parole tue: serve a ricordare il perché della strategia."""
    enabled: bool = Field(True, alias="attiva")
    market: MarketFilter = Field(default_factory=MarketFilter, alias="mercato")
    when: Expression = Field(alias="quando")
    entry: Entry = Field(alias="ingresso")
    exit: Exit | None = Field(None, alias="uscita")

    @field_validator("when", mode="before")
    @classmethod
    def _compile(cls, value: Any) -> Expression:
        return Expression.compile(value, ENTRY_VARIABLES, unavailable=_EXIT_ONLY)

    @property
    def label(self) -> str:
        return self.id or re.sub(r"\W+", "_", self.name.lower()).strip("_")


def load_strategies(*paths: Path) -> list[Strategy]:
    """Carica strategie da file YAML o da cartelle che li contengono."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted([*path.glob("*.yaml"), *path.glob("*.yml")]))
        else:
            files.append(path)
    if not files:
        raise InputError("nessun file di strategia trovato")
    strategies = [s for file in files for s in _load_file(file)]
    labels = [s.label for s in strategies]
    for label in labels:
        if labels.count(label) > 1:
            raise InputError(f"più strategie con id '{label}': usa il campo 'id' per distinguerle")
    return strategies


def _load_file(path: Path) -> list[Strategy]:
    data = load_yaml(path)
    if isinstance(data, dict) and set(data) == {"strategie"}:
        data = data["strategie"]
    items = [data] if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InputError(f"{path}: il file non contiene strategie")
    strategies = []
    for k, item in enumerate(items, 1):
        try:
            strategy = Strategy.model_validate(item)
        except ValidationError as exc:
            where = path if len(items) == 1 else f"{path} (strategia {k})"
            raise InputError(f"{where}: strategia non valida\n{format_errors(exc)}") from None
        if strategy.id is None:
            strategy.id = path.stem if len(items) == 1 else f"{path.stem}-{k}"
        strategies.append(strategy)
    return strategies


def describe(strategy: Strategy) -> str:
    """Spiegazione in italiano di cosa farà la strategia."""
    s = strategy
    lines = [f"[{s.label}] {s.name}" + ("" if s.enabled else "  (DISATTIVATA)")]
    if s.outlook.strip():
        lines += _wrap("Andamento atteso: " + " ".join(s.outlook.split()))
    lines += _wrap("Partite: " + s.market.describe())
    lines.append("  Ingresso, controllato su entrambi i giocatori a ogni aggiornamento di punteggio o quote:")
    lines.append(f"      {s.when.source}")
    lines += _variables(s.when)
    lines += _wrap("Esecuzione: " + s.entry.describe())
    if s.exit is None:
        lines += _wrap("Uscita: nessuna, la posizione resta aperta fino alla fine della partita.")
    else:
        lines.append("  Uscita: chiude in green alla migliore quota quando")
        lines.append(f"      {s.exit.when.source}")
        lines += _variables(s.exit.when)
    return "\n".join(lines)


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=96, initial_indent="  ", subsequent_indent="    ")


def _variables(expression: Expression) -> list[str]:
    return [f"        · {name}: {VARIABLES[name]}" for name in sorted(expression.names)]


def _alternatives(items: list[str]) -> str:
    return " o ".join(f"'{item}'" for item in items)
