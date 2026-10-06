"""Condizioni delle strategie: espressioni in stile Python con parole chiave italiane.

Esempio: ``set_sotto >= 1 e break_sotto >= 1 e non al_servizio``

L'espressione è interpretata su un albero sintattico filtrato: niente ``eval``, solo
confronti, operatori logici e aritmetici e le funzioni abs, min e max.
"""

from __future__ import annotations

import ast
import difflib
import operator
import re
from collections.abc import Collection, Mapping
from typing import Any

_ITALIAN = {"e": "and", "o": "or", "non": "not", "vero": "True", "falso": "False"}
_ITALIAN_WORD = re.compile(r"\b(?:e|o|non|vero|falso)\b")
_STRING = re.compile(r"(\"[^\"]*\"|'[^']*')")
_SINGLE_EQUALS = re.compile(r"(?<![=!<>])=(?!=)")

_FUNCTIONS = {"abs": abs, "min": min, "max": max}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Compare, ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List, ast.Call,
    *_BINARY, *_COMPARE,
)


class ExpressionError(ValueError):
    """Condizione non valida o non valutabile."""


class Expression:
    """Condizione compilata, valutabile su un dizionario di variabili."""

    def __init__(self, source: str, tree: ast.Expression, names: frozenset[str]) -> None:
        self.source = source
        self.names = names
        self._tree = tree

    @classmethod
    def compile(
        cls, source: Any, variables: Collection[str], unavailable: Mapping[str, str] | None = None
    ) -> Expression:
        """Controlla la sintassi e che ogni variabile usata sia in `variables`.

        `unavailable` associa a variabili note, ma non utilizzabili in questo punto, il motivo da mostrare.
        """
        if not isinstance(source, str):
            raise ExpressionError("la condizione deve essere un testo, es. set_sotto >= 1 e break_sotto >= 1")
        text = " ".join(source.split())
        if not text:
            raise ExpressionError("condizione vuota")
        try:
            tree = ast.parse(_translate(text), mode="eval")
        except SyntaxError:
            hint = " (per l'uguaglianza si usa ==)" if _SINGLE_EQUALS.search(text) else ""
            raise ExpressionError(f"sintassi non valida: {text}{hint}") from None

        functions = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        names = set()
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED):
                raise ExpressionError(f"costrutto non ammesso in: {text}")
            if isinstance(node, ast.Constant) and not isinstance(node.value, (bool, int, float, str)):
                raise ExpressionError(f"valore non ammesso in: {text}")
            if isinstance(node, ast.Call):
                if not (isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS) or node.keywords:
                    raise ExpressionError("le uniche funzioni ammesse sono abs, min e max")
            elif isinstance(node, ast.Name) and id(node) not in functions:
                names.add(node.id)

        for name in sorted(names):
            if name in variables:
                continue
            if unavailable and name in unavailable:
                raise ExpressionError(f"'{name}' {unavailable[name]}")
            close = difflib.get_close_matches(name, list(variables), n=1)
            hint = f" (forse '{close[0]}'?)" if close else " (elenco completo: bet variabili)"
            raise ExpressionError(f"variabile sconosciuta '{name}'{hint}")
        return cls(text, tree, frozenset(names))

    def evaluate(self, values: Mapping[str, Any]) -> bool:
        """Vero se la condizione è soddisfatta; falso se manca anche uno solo dei dati che usa."""
        if any(values.get(name) is None for name in self.names):
            return False
        try:
            return bool(_eval(self._tree.body, values))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ExpressionError(f"impossibile valutare '{self.source}': {exc}") from None

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"


def _translate(text: str) -> str:
    """Sostituisce e/o/non/vero/falso con gli equivalenti Python, fuori dai testi tra virgolette."""
    parts = _STRING.split(text)
    for k in range(0, len(parts), 2):
        parts[k] = _ITALIAN_WORD.sub(lambda m: _ITALIAN[m.group()], parts[k])
    return "".join(parts)


def _eval(node: ast.AST, values: Mapping[str, Any]) -> Any:
    match node:
        case ast.Constant(value=value):
            return value
        case ast.Name(id=name):
            return values[name]
        case ast.BoolOp(op=ast.And(), values=items):
            return all(_eval(item, values) for item in items)
        case ast.BoolOp(values=items):
            return any(_eval(item, values) for item in items)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            return not _eval(operand, values)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_eval(operand, values)
        case ast.UnaryOp(operand=operand):
            return +_eval(operand, values)
        case ast.BinOp(left=left, op=op, right=right):
            return _BINARY[type(op)](_eval(left, values), _eval(right, values))
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            current = _eval(left, values)
            for op, comparator in zip(ops, comparators):
                following = _eval(comparator, values)
                if not _COMPARE[type(op)](current, following):
                    return False
                current = following
            return True
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return [_eval(item, values) for item in items]
        case ast.Call(func=ast.Name(id=name), args=args):
            return _FUNCTIONS[name](*(_eval(arg, values) for arg in args))
    raise ExpressionError(f"costrutto non supportato: {ast.dump(node)}")
