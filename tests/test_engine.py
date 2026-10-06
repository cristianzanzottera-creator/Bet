import textwrap
from pathlib import Path

import pytest
import yaml

from bet.broker import PaperBroker
from bet.config import Settings
from bet.engine import Engine
from bet.market import MarketBook, Match, Player, RunnerBook
from bet.replay import load_scenario, run_scenario
from bet.strategy import Strategy, load_strategies
from bet.tennis import parse_score

ROOT = Path(__file__).resolve().parents[1]
ROSSI, BIANCHI = Player("Anna Rossi", 101), Player("Bea Bianchi", 102)

COMEBACK = """
nome: Rimonta
quando: set_sotto >= 1 e break_sotto >= 1
ingresso:
  puntata: 10
  liquidita_minima: 10000
  liquidita_minima_quota: 50
  annulla_non_abbinato_dopo: 15
"""
# Rossi (A) ha perso il primo set e ha appena perso il servizio nel secondo
DOWN_SET_AND_BREAK = parse_score("4-6 0-2", server=0)


def strategy(text: str) -> Strategy:
    s = Strategy.model_validate(yaml.safe_load(textwrap.dedent(text)))
    s.id = "test"
    return s


def book(a, b, delay=0.0, market_id="1.1", volume=20000):
    """Quote di Rossi (a) e Bianchi (b) come (back, € back, lay, € lay); volume = € abbinati sul mercato."""
    runners = {
        player.selection_id: RunnerBook(player.selection_id, *prices)
        for player, prices in ((ROSSI, a), (BIANCHI, b))
    }
    return MarketBook(market_id, runners, in_play=True, total_matched=volume, bet_delay=delay)


class Harness:
    def __init__(self, *strategies, competition="WTA Tokyo", **settings):
        self.lines = []
        self.engine = Engine(
            list(strategies), Settings.model_validate(settings), PaperBroker(), lambda t, m: self.lines.append(m)
        )
        self.engine.add_match(Match("1.1", "Anna Rossi v Bea Bianchi", competition, (ROSSI, BIANCHI)), 0)

    def update(self, t, book=None, score=None):
        self.engine.advance_to(t)
        self.engine.update("1.1", t, book=book, score=score)

    def fills(self):
        return [(f.order.selection_id, f.order.side, f.price, f.size) for f in self.engine.fills("1.1")]

    def logged(self, text):
        return any(text in line for line in self.lines)


def test_waits_for_market_volume():
    h = Harness(strategy(COMEBACK))
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300), volume=8900), DOWN_SET_AND_BREAK)
    assert h.engine.broker.orders == []
    assert h.logged("sul mercato sono abbinati solo 8.900 € (minimo 10.000 €)")
    h.update(10, book((3.45, 140, 3.50, 60), (1.40, 420, 1.41, 500), volume=10400))
    assert h.fills() == [(ROSSI.selection_id, "BACK", 3.45, 10)]


def test_waits_for_liquidity_at_the_best_price():
    h = Harness(strategy(COMEBACK))
    h.update(0, book((3.40, 30, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    assert h.engine.broker.orders == []
    assert h.logged("a 3.40 ci sono solo 30 € (minimo 50 €)")
    h.update(10, book((3.45, 140, 3.50, 60), (1.40, 420, 1.41, 500)))
    assert h.fills() == [(ROSSI.selection_id, "BACK", 3.45, 10)]


def test_condition_is_checked_for_both_players():
    h = Harness(strategy(COMEBACK))
    # Bianchi (B) ha perso il primo set ed è sotto di un break: 2-0 dopo aver servito per prima
    h.update(0, book((1.41, 500, 1.42, 300), (3.40, 200, 3.45, 90)), parse_score("6-4 2-0", server=1))
    assert h.fills() == [(BIANCHI.selection_id, "BACK", 3.40, 10)]


def test_order_missed_during_the_delay_is_cancelled_and_retried():
    h = Harness(strategy(COMEBACK))
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300), delay=3), DOWN_SET_AND_BREAK)
    [order] = h.engine.broker.orders
    assert order.price == 3.40 and order.active_at == 3
    # durante il ritardo la quota scende: all'attivazione 3.40 non c'è più e l'ordine resta in attesa
    falling = ((3.20, 200, 3.25, 90), (1.45, 500, 1.46, 300))
    h.update(2, book(*falling, delay=3))
    h.update(20, book(*falling, delay=3))
    assert order.status == "annullato" and order.matched == 0
    assert h.logged("annullato, non abbinato")
    # la condizione è ancora vera: nuovo ordine alla nuova quota migliore
    h.update(30, book(*falling, delay=3))
    assert h.fills() == [(ROSSI.selection_id, "BACK", 3.20, 10)]


def test_partial_fill_then_the_rest_is_cancelled():
    h = Harness(strategy(COMEBACK.replace("liquidita_minima_quota: 50", "liquidita_minima_quota: 4")))
    h.update(0, book((3.40, 6, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    assert h.fills() == [(ROSSI.selection_id, "BACK", 3.40, 6)]
    h.update(20, book((3.30, 6, 3.35, 90), (1.43, 500, 1.44, 300)))
    assert h.logged("annullata la parte non abbinata (4.00 €)")
    # un ingresso con abbinamento è già stato fatto: niente secondo ordine
    assert len(h.engine.broker.orders) == 1


def test_green_exit_locks_the_result():
    h = Harness(strategy(COMEBACK + "uscita:\n  quando: pl_green >= 2\n"))
    h.update(0, book((3.0, 100, 3.05, 100), (1.5, 100, 1.52, 100)), DOWN_SET_AND_BREAK)
    h.update(5, book((2.0, 300, 2.02, 300), (1.98, 300, 2.0, 300)), parse_score("4-6 2-2", server=0))
    assert h.fills() == [(ROSSI.selection_id, "BACK", 3.0, 10), (ROSSI.selection_id, "LAY", 2.02, 14.85)]
    assert h.logged("posizione chiusa, risultato garantito +4.85 €")
    [result] = h.engine.settle("1.1", BIANCHI.selection_id, 60)
    assert result.gross == pytest.approx(4.85)
    assert result.commission == pytest.approx(0.22)  # 4,5% di betfair.it
    assert result.net == pytest.approx(4.63)


def test_no_new_entry_while_closing_the_position():
    h = Harness(strategy(COMEBACK.replace("puntata: 10", "puntata: 10\n  max_ingressi_per_match: 2") + "uscita:\n  quando: pl_green >= 2\n"))
    h.update(0, book((3.0, 100, 3.05, 100), (1.5, 100, 1.52, 100), delay=3), DOWN_SET_AND_BREAK)
    # la quota scende mentre la condizione di ingresso resta vera: parte la chiusura, non un secondo ingresso
    h.update(5, book((2.0, 300, 2.02, 300), (1.98, 300, 2.0, 300), delay=3))
    assert [o.purpose for o in h.engine.broker.orders] == ["ingresso", "uscita"]


def test_settled_matches_free_their_exposure():
    h = Harness(strategy(COMEBACK), esposizione_massima=15)
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    h.engine.settle("1.1", ROSSI.selection_id, 100)
    h.engine.add_match(Match("1.2", "Anna Rossi v Bea Bianchi", "WTA Tokyo", (ROSSI, BIANCHI)), 200)
    h.engine.update("1.2", 200, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300), market_id="1.2"), DOWN_SET_AND_BREAK)
    assert [f.price for f in h.engine.fills("1.2")] == [3.40]


def test_lay_entry_with_liability_stake():
    lay = strategy(
        """
        nome: Lay sulla palla break
        quando: palla_break_contro
        ingresso:
          lato: lay
          puntata: 20
          tipo_puntata: responsabilita
        """
    )
    h = Harness(lay)
    h.update(0, book((4.9, 100, 5.0, 100), (1.25, 100, 1.26, 100)), parse_score("2-2", points="30-40", server=0))
    assert h.fills() == [(ROSSI.selection_id, "LAY", 5.0, 5.0)]


def test_exposure_limit_blocks_new_entries():
    h = Harness(strategy(COMEBACK), esposizione_massima=5)
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    assert h.engine.broker.orders == []
    assert h.logged("esposizione massima di 5 €")


def test_minimum_stake():
    h = Harness(strategy(COMEBACK), puntata_minima=20)
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    assert h.engine.broker.orders == []
    assert h.logged("sotto il minimo")


def test_ignored_match_never_trades():
    h = Harness(strategy(COMEBACK + "mercato:\n  circuito: WTA\n"), competition="ITF W25 Roma")
    h.update(0, book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300)), DOWN_SET_AND_BREAK)
    assert h.logged("partita ignorata")
    assert h.engine.broker.orders == []


def test_suspended_market_places_nothing():
    h = Harness(strategy(COMEBACK))
    suspended = MarketBook("1.1", book((3.40, 140, 3.45, 90), (1.41, 500, 1.42, 300)).runners, in_play=True, status="SUSPENDED")
    h.update(0, suspended, DOWN_SET_AND_BREAK)
    assert h.engine.broker.orders == []


@pytest.mark.parametrize(
    "scenario, expected",
    [
        ("wta_rimonta_riuscita", {"wta_rimonta": 24.50, "wta_rimonta_favorita": 11.08}),
        ("wta_rimonta_fallita", {"wta_rimonta": -10.0, "wta_rimonta_favorita": -10.42}),
    ],
)
def test_example_scenarios(scenario, expected):
    lines = []
    engine = Engine(load_strategies(ROOT / "strategie"), Settings(), PaperBroker(), lambda t, m: None)
    results = run_scenario(load_scenario(ROOT / "scenari" / f"{scenario}.yaml"), engine, lambda t, m: lines.append(m))
    assert {r.strategy: r.gross for r in results} == pytest.approx(expected)
    # il servizio indicato a inizio partita si alterna da solo
    assert any(line.startswith("4-6 0-2, serve Anna Rossi") for line in lines)
