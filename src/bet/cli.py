"""Comandi: bet controlla | bet simula | bet variabili."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .broker import PaperBroker
from .config import load_settings
from .context import MARKET_VARIABLES, POSITION_VARIABLES, SCORE_VARIABLES
from .engine import Engine, Result
from .errors import InputError
from .replay import format_time, load_scenario, run_scenario
from .strategy import describe, load_strategies


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bet", description="Strategie in-play su Betfair Exchange (tennis)")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("controlla", help="valida le strategie e spiega cosa faranno")
    check.add_argument("strategie", nargs="+", type=Path, help="file .yaml o cartelle")

    simulate = commands.add_parser("simula", help="fa girare le strategie su scenari di partita")
    simulate.add_argument("strategie", nargs="+", type=Path, help="file .yaml o cartelle")
    simulate.add_argument("-s", "--scenario", nargs="+", type=Path, required=True, help="file .yaml o cartelle")
    simulate.add_argument("-c", "--config", type=Path, help="impostazioni (bankroll, commissione, limiti)")

    commands.add_parser("variabili", help="elenca le variabili utilizzabili nelle condizioni")

    args = parser.parse_args(argv)
    try:
        if args.command == "variabili":
            _print_variables()
        elif args.command == "controlla":
            for strategy in load_strategies(*args.strategie):
                print(describe(strategy), end="\n\n")
        else:
            _simulate(args.strategie, args.scenario, args.config)
    except InputError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


def _simulate(strategy_paths: list[Path], scenario_paths: list[Path], config: Path | None) -> None:
    strategies = load_strategies(*strategy_paths)
    settings = load_settings(config)
    files = [f for p in scenario_paths for f in (sorted(p.glob("*.y*ml")) if p.is_dir() else [p])]
    if not files:
        raise InputError("nessuno scenario trovato")
    scenarios = [(f, load_scenario(f)) for f in files]
    results: list[Result] = []
    for path, scenario in scenarios:
        print(f"\n=== {path.name} ===")
        engine = Engine(strategies, settings, PaperBroker(), _log)
        results += run_scenario(scenario, engine, _log)

    count = "1 scenario" if len(scenarios) == 1 else f"{len(scenarios)} scenari"
    commission = f"{settings.commission * 100:g}".replace(".", ",")
    print(f"\n=== Riepilogo su {count} (commissione {commission}%) ===")
    width = max(len(s.label) for s in strategies)
    for strategy in strategies:
        if not strategy.enabled:
            print(f"  {strategy.label:<{width}}  disattivata")
            continue
        mine = [r for r in results if r.strategy == strategy.label]
        traded = [r for r in mine if r.fills]
        net = sum(r.net for r in mine)
        print(
            f"  {strategy.label:<{width}}  partite con scommesse {len(traded)}/{len(mine)}  "
            f"netto {net:+.2f} €  (lordo {sum(r.gross for r in mine):+.2f} €, "
            f"commissioni {sum(r.commission for r in mine):.2f} €)"
        )


def _log(t: float, message: str) -> None:
    print(f"[{format_time(t):>8}] {message}")


def _print_variables() -> None:
    groups = [
        ("Punteggio, dal punto di vista del giocatore valutato", SCORE_VARIABLES),
        ("Mercato", MARKET_VARIABLES),
        ("Posizione (solo in uscita.quando)", POSITION_VARIABLES),
    ]
    for title, variables in groups:
        print(title)
        width = max(map(len, variables))
        for name, text in variables.items():
            print(f"  {name:<{width}}  {text}")
        print()
    print("Operatori: >= <= > < == !=  ·  e / o / non (oppure and / or / not)  ·  + - * /  ·  abs() min() max()")
    print('Testi tra virgolette, es.: "Swiatek" in giocatore')


if __name__ == "__main__":
    sys.exit(main())
