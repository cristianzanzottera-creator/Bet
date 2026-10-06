import pytest

from bet.expr import Expression, ExpressionError

VARIABLES = {"set_sotto", "break_sotto", "quota_back", "al_servizio", "giocatore"}


def test_italian_keywords():
    e = Expression.compile("set_sotto >= 1 e break_sotto >= 1 e non al_servizio", VARIABLES)
    assert e.evaluate({"set_sotto": 1, "break_sotto": 1, "al_servizio": False})
    assert not e.evaluate({"set_sotto": 1, "break_sotto": 1, "al_servizio": True})
    assert e.names == {"set_sotto", "break_sotto", "al_servizio"}


def test_or_and_chained_comparisons():
    e = Expression.compile("2.5 <= quota_back <= 6 o break_sotto >= 2", VARIABLES)
    assert e.evaluate({"quota_back": 3.4, "break_sotto": 0})
    assert not e.evaluate({"quota_back": 8.0, "break_sotto": 1})
    assert e.evaluate({"quota_back": 8.0, "break_sotto": 2})


def test_multiline_text_is_accepted():
    e = Expression.compile("set_sotto >= 1\ne break_sotto >= 1\n", VARIABLES)
    assert e.source == "set_sotto >= 1 e break_sotto >= 1"


def test_missing_data_makes_the_condition_false():
    e = Expression.compile("non al_servizio", VARIABLES)
    assert not e.evaluate({"al_servizio": None})
    assert not e.evaluate({})


def test_unknown_variable_suggests_the_right_one():
    with pytest.raises(ExpressionError, match="forse 'set_sotto'"):
        Expression.compile("set_soto >= 1", VARIABLES)


def test_unavailable_variable_explains_why():
    with pytest.raises(ExpressionError, match="solo in uscita"):
        Expression.compile("pl_green > 0", VARIABLES, unavailable={"pl_green": "si può usare solo in uscita"})


def test_single_equals_gets_a_hint():
    with pytest.raises(ExpressionError, match="=="):
        Expression.compile("set_sotto = 1", VARIABLES)


@pytest.mark.parametrize(
    "source",
    ["__import__('os')", "quota_back.real", "[x for x in giocatore]", "lambda: 1", "max(quota_back, key=1)", "None"],
)
def test_only_safe_constructs_are_allowed(source):
    with pytest.raises(ExpressionError):
        Expression.compile(source, VARIABLES)


def test_italian_words_inside_strings_are_untouched():
    e = Expression.compile('"Rossi e" in giocatore', VARIABLES)
    assert e.evaluate({"giocatore": "Rossi e Bianchi"})
    assert not e.evaluate({"giocatore": "Rossi and Bianchi"})


def test_functions():
    e = Expression.compile("abs(quota_back - 3) < 0.5 e max(set_sotto, break_sotto) >= 1", VARIABLES)
    assert e.evaluate({"quota_back": 3.2, "set_sotto": 0, "break_sotto": 1})


def test_runtime_errors_are_reported():
    e = Expression.compile("quota_back / set_sotto > 1", VARIABLES)
    with pytest.raises(ExpressionError, match="impossibile valutare"):
        e.evaluate({"quota_back": 3.0, "set_sotto": 0})
