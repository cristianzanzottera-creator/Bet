from pathlib import Path

import pytest

from bet.cli import main
from bet.context import VARIABLES
from bet.errors import InputError
from bet.replay import format_time, load_scenario, parse_time

ROOT = Path(__file__).resolve().parents[1]


def test_times():
    assert parse_time("44:40") == 2680
    assert parse_time("-10:00") == -600
    assert parse_time("1:52:00") == 6720
    assert parse_time(90) == 90
    assert format_time(-600) == "-10:00"
    assert format_time(6720) == "1:52:00"
    with pytest.raises(ValueError):
        parse_time("1h")


def test_scenario_errors_are_readable(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
partita:
  mercato_id: "1.1"
  evento: A v B
  giocatori:
    A: {nome: A, id: 1}
    B: {nome: B, id: 2}
eventi:
  - t: 0
    punteggio: "4-5 1-0"
    quote:
      A: "3.42/3.45 @ 10/10"
""",
        encoding="utf-8",
    )
    with pytest.raises(InputError) as info:
        load_scenario(path)
    message = str(info.value)
    assert "eventi.0.punteggio" in message and "non è concluso" in message
    assert "3.42 non è una quota della scala Betfair" in message


def test_cli_check_and_simulate(capsys):
    assert main(["controlla", str(ROOT / "strategie")]) == 0
    assert "set_sotto >= 1 e break_sotto >= 1" in capsys.readouterr().out
    args = ["simula", str(ROOT / "strategie"), "--scenario", str(ROOT / "scenari"), "--config", str(ROOT / "config.yaml")]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Riepilogo su 2 scenari" in out
    assert "ABBINATO BACK 10.00 € @ 3.45" in out


def test_cli_reports_input_errors(tmp_path, capsys):
    bad = tmp_path / "rotta.yaml"
    bad.write_text("nome: x\n", encoding="utf-8")
    assert main(["controlla", str(bad)]) == 1
    assert "campo obbligatorio mancante" in capsys.readouterr().err


def test_readme_documents_every_variable():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [name for name in VARIABLES if f"`{name}`" not in readme]
    assert missing == []
