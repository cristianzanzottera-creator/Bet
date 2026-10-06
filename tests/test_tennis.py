import pytest

from bet.tennis import TennisScore, format_score, parse_score

A, B = 0, 1


def test_sets_and_break_with_known_server():
    # A ha servito il primo game del set e l'ha perso, B ha tenuto: 0-2, serve di nuovo A
    score = parse_score("4-6 0-2", server=A)
    assert score.sets_won(A) == 0 and score.sets_won(B) == 1
    assert score.set_number == 2
    assert score.net_breaks_against(A) == 1
    assert score.net_breaks_against(B) == -1


def test_deficit_on_serve_is_not_a_break():
    # B ha servito per prima: 2-3 con tutti i servizi tenuti, ora serve A
    score = parse_score("2-3", server=A)
    assert score.net_breaks_against(A) == 0


def test_two_breaks_down():
    # A ha servito per prima: dopo 1-4 serve B, A ha perso due turni di servizio
    assert parse_score("4-6 1-4", server=B).net_breaks_against(A) == 2


def test_unknown_server_uses_conservative_estimate():
    assert parse_score("2-3").net_breaks_against(A) == 0
    assert parse_score("1-3").net_breaks_against(A) == 1
    assert parse_score("1-4").net_breaks_against(A) == 1
    assert parse_score("3-1").net_breaks_against(A) == -1


def test_finished_set_starts_the_next_one():
    score = parse_score("6-4")
    assert score.sets == ((6, 4),)
    assert score.games == (0, 0)
    assert parse_score("7-6(5) 1-0").sets == ((7, 6),)


def test_only_the_last_set_can_be_in_progress():
    with pytest.raises(ValueError, match="non è concluso"):
        parse_score("4-5 1-0")
    with pytest.raises(ValueError, match="non valido"):
        parse_score("4/6")


def test_break_points():
    score = parse_score("4-6 1-2", points="30-40", server=A)
    assert score.break_point_against(A) is True
    assert score.break_point_against(B) is False
    assert parse_score("1-2", points="40-A", server=A).break_point_against(A) is True
    assert parse_score("1-2", points="40-40", server=A).break_point_against(A) is False
    assert parse_score("1-2", points="30-40").break_point_against(A) is None


def test_tiebreak():
    score = parse_score("6-6", points="5-3", server=A)
    assert score.in_tiebreak
    assert score.points == (5, 3)
    assert score.net_breaks_against(A) == 0
    assert score.break_point_against(A) is False


def test_invalid_points():
    for points in ("A-15", "50-0", "15"):
        with pytest.raises(ValueError, match="punti non validi"):
            parse_score("1-1", points=points)


def test_format_score():
    assert format_score(parse_score("4-6 2-3", points="15-40")) == "4-6 2-3 (15-40)"
    assert format_score(TennisScore(games=(6, 6), points=(5, 3))) == "6-6 (5-3)"
