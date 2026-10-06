import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bet.errors import InputError
from bet.market import Match, Player
from bet.strategy import Strategy, describe, load_strategies

ROOT = Path(__file__).resolve().parents[1]

MINIMAL = """
nome: Prova
quando: set_sotto >= 1
ingresso:
  puntata: 10
"""


def write(tmp_path, text, name="prova.yaml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def minimal(**changes):
    data = yaml.safe_load(MINIMAL)
    data.update(changes)
    return data


def test_example_strategies_load_and_describe():
    strategies = load_strategies(ROOT / "strategie")
    assert [s.label for s in strategies] == ["wta_rimonta", "wta_rimonta_favorita"]
    for strategy in strategies:
        assert strategy.name in describe(strategy)


def test_defaults(tmp_path):
    [strategy] = load_strategies(write(tmp_path, MINIMAL))
    assert strategy.label == "prova"
    assert strategy.entry.side == "BACK"
    assert strategy.entry.improve_ticks == 0
    assert strategy.entry.max_entries == 1
    assert strategy.exit is None
    assert strategy.market.circuits == []


def test_errors_name_the_field_in_italian(tmp_path):
    path = write(
        tmp_path,
        """
        nome: Prova
        quandoo: set_sotto >= 1
        ingresso:
          lato: PUNTA
          puntata: -5
        """,
    )
    with pytest.raises(InputError) as info:
        load_strategies(path)
    message = str(info.value)
    assert "quando: campo obbligatorio mancante" in message
    assert "quandoo: campo non previsto" in message
    assert "ingresso.lato: valore non ammesso" in message
    assert "ingresso.puntata: deve essere maggiore di 0" in message


def test_bad_condition_is_reported_with_a_suggestion(tmp_path):
    with pytest.raises(InputError, match="forse 'break_sotto'"):
        load_strategies(write(tmp_path, MINIMAL.replace("set_sotto >= 1", "brek_sotto >= 1")))


@pytest.mark.parametrize("text, ticks", [("migliore", 0), ("migliore+2", 2), ("Migliore + 3", 3)])
def test_entry_price_modes(text, ticks):
    data = minimal()
    data["ingresso"]["prezzo"] = text
    assert Strategy.model_validate(data).entry.improve_ticks == ticks


def test_unknown_entry_price_mode():
    data = minimal()
    data["ingresso"]["prezzo"] = "massima"
    with pytest.raises(ValidationError, match="migliore"):
        Strategy.model_validate(data)


def test_position_variables_only_in_exit():
    with pytest.raises(ValidationError, match="uscita.quando"):
        Strategy.model_validate(minimal(quando="pl_green > 0"))
    strategy = Strategy.model_validate(minimal(uscita={"quando": "pl_green > 0 o break_sotto >= 2"}))
    assert strategy.exit.when.names == {"pl_green", "break_sotto"}


def test_several_strategies_in_one_file(tmp_path):
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump({"strategie": [minimal(), minimal()]}), encoding="utf-8")
    assert [s.label for s in load_strategies(path)] == ["multi-1", "multi-2"]


def test_duplicate_ids_are_rejected(tmp_path):
    first = write(tmp_path, MINIMAL + "id: doppione\n", "a.yaml")
    second = write(tmp_path, MINIMAL + "id: doppione\n", "b.yaml")
    with pytest.raises(InputError, match="id 'doppione'"):
        load_strategies(first, second)


def test_market_filter():
    strategy = Strategy.model_validate(
        minimal(mercato={"circuito": "WTA", "escludi": ["Qualif"], "solo_giocatori": ["Rossi"]})
    )

    def match(competition, a="Anna Rossi", b="Bea Bianchi"):
        return Match("1.1", f"{a} v {b}", competition, (Player(a, 1), Player(b, 2)))

    assert strategy.market.rejects(match("WTA Tokyo")) is None
    assert "fuori" in strategy.market.rejects(match("ATP Tokyo"))
    assert "Qualif" in strategy.market.rejects(match("WTA Tokyo Qualifiers"))
    assert strategy.market.rejects(match("WTA Tokyo", "Rossi/Verdi", "Bianchi/Neri")) == "doppio"
    assert strategy.market.allows_player("Anna Rossi")
    assert not strategy.market.allows_player("Bea Bianchi")
