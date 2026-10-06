import pytest

from bet import ladder


def test_ladder_has_all_betfair_prices():
    assert len(ladder.LADDER) == 350
    assert ladder.LADDER[0] == 1.01
    assert ladder.LADDER[-1] == 1000.0


def test_move_across_bands():
    assert ladder.move(1.99, 1) == 2.0
    assert ladder.move(2.0, 1) == 2.02
    assert ladder.move(3.95, 1) == 4.0
    assert ladder.move(4.0, -1) == 3.95
    assert ladder.move(3.4, 2) == 3.5


def test_move_stops_at_the_ends():
    assert ladder.move(1.01, -3) == 1.01
    assert ladder.move(1000, 2) == 1000.0


def test_invalid_prices():
    assert not ladder.is_valid(2.01)
    assert not ladder.is_valid(3.42)
    with pytest.raises(ValueError):
        ladder.index(3.42)


def test_ticks_between():
    assert ladder.ticks_between(3.40, 3.50) == 2
    assert ladder.ticks_between(1.99, 2.02) == 2
