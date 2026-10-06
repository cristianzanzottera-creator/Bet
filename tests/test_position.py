import pytest

from bet.position import Position


def test_green_after_back():
    position = Position("BACK")
    position.add("BACK", 3.0, 10)
    assert position.if_win == 20 and position.if_lose == -10
    hedge = position.hedge(back_price=2.0, lay_price=2.02)
    assert hedge.side == "LAY"
    assert hedge.price == 2.02
    assert hedge.stake == 14.85
    assert hedge.locked_profit == pytest.approx(4.85)


def test_green_after_lay():
    position = Position("LAY")
    position.add("LAY", 2.0, 10)
    hedge = position.hedge(back_price=3.0, lay_price=3.05)
    assert hedge.side == "BACK"
    assert hedge.stake == 6.67
    assert hedge.locked_profit == pytest.approx(3.33)


def test_hedged_position_needs_nothing_more():
    position = Position("BACK")
    position.add("BACK", 3.0, 10)
    position.add("LAY", 2.0, 15)
    assert position.if_win == position.if_lose == 5
    assert position.hedge(back_price=1.9, lay_price=2.0).stake == 0
    assert position.stake == 10
    assert position.entry_price == 3.0


def test_missing_price_means_no_hedge():
    position = Position("BACK")
    position.add("BACK", 3.0, 10)
    assert position.hedge(back_price=2.9, lay_price=None) is None
