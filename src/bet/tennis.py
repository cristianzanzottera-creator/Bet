"""Punteggio del tennis e grandezze derivate: set, break, palle break."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SET = re.compile(r"(\d+)-(\d+)(?:\(\d+\))?")
_POINT_VALUES = {"0": 0, "15": 1, "30": 2, "40": 3, "A": 4, "AD": 4, "V": 4}
_POINT_TEXT = ("0", "15", "30", "40", "A")


@dataclass(frozen=True)
class TennisScore:
    """Punteggio di una partita di singolare. Indice 0 = giocatore A, 1 = giocatore B."""

    sets: tuple[tuple[int, int], ...] = ()
    """Set conclusi, in game: ((4, 6),) = primo set vinto 6-4 da B."""
    games: tuple[int, int] = (0, 0)
    """Game nel set in corso."""
    points: tuple[int, int] = (0, 0)
    """Punti nel game in corso: 0..3 = 0/15/30/40, 4 = vantaggio. Nel tiebreak i punti reali."""
    server: int | None = None
    """Chi serve il game in corso; None se il feed non lo fornisce."""

    @property
    def set_number(self) -> int:
        return len(self.sets) + 1

    @property
    def in_tiebreak(self) -> bool:
        return self.games == (6, 6)

    @property
    def total_games(self) -> int:
        """Game giocati nella partita (il tiebreak conta come un game, come per l'alternanza al servizio)."""
        return sum(a + b for a, b in self.sets) + sum(self.games)

    def sets_won(self, i: int) -> int:
        return sum(1 for s in self.sets if s[i] > s[1 - i])

    def net_breaks_against(self, i: int) -> int:
        """Break netti subiti da `i` nel set in corso (negativo se è avanti di break).

        Con il servizio noto il conto è esatto: game serviti da `i` meno game vinti da `i`.
        Senza servizio si usa la stima prudente: metà dello svantaggio in game, per difetto.
        """
        mine, theirs = self.games[i], self.games[1 - i]
        if self.in_tiebreak:
            return 0
        if self.server is None:
            gap = theirs - mine
            return gap // 2 if gap >= 0 else -(-gap // 2)
        played = mine + theirs
        first_server = self.server if played % 2 == 0 else 1 - self.server
        served = (played + 1) // 2 if first_server == i else played // 2
        return served - mine

    def is_serving(self, i: int) -> bool | None:
        return None if self.server is None else self.server == i

    def break_point_against(self, i: int) -> bool | None:
        """Vero se `i` è al servizio e l'avversario può vincere il game sul prossimo punto."""
        if self.server is None:
            return None
        if self.in_tiebreak or self.server != i:
            return False
        serving, receiving = self.points[i], self.points[1 - i]
        return receiving >= 3 and receiving > serving


def parse_score(score: str, points: str | None = None, server: int | None = None) -> TennisScore:
    """Legge un punteggio come "4-6 2-3": set conclusi e, per ultimo, il set in corso.

    Se l'ultimo set risulta concluso ("4-6 6-4") si considera iniziato il successivo (0-0).
    `points` è il punteggio del game: "15-40", "40-A"; nel tiebreak "5-3".
    """
    tokens = score.replace(",", " ").split()
    if not tokens:
        raise ValueError("punteggio vuoto")
    parsed = []
    for token in tokens:
        m = _SET.fullmatch(token)
        if m is None:
            raise ValueError(f"punteggio non valido '{token}' (formato: '4-6 2-3')")
        parsed.append((int(m[1]), int(m[2])))
    *sets, games = parsed
    for s in sets:
        if not _set_over(s):
            raise ValueError(f"il set {s[0]}-{s[1]} non è concluso: solo l'ultimo set può essere in corso")
    if _set_over(games):
        sets.append(games)
        games = (0, 0)
    tiebreak = games == (6, 6)
    return TennisScore(tuple(sets), games, parse_points(points, tiebreak) if points else (0, 0), server)


def parse_points(text: str, tiebreak: bool) -> tuple[int, int]:
    parts = text.upper().replace(" ", "").split("-")
    error = ValueError(f"punti non validi '{text}' (esempi: '15-40', '40-A'; nel tiebreak '5-3')")
    if len(parts) != 2:
        raise error
    try:
        if tiebreak:
            return int(parts[0]), int(parts[1])
        a, b = _POINT_VALUES[parts[0]], _POINT_VALUES[parts[1]]
    except (KeyError, ValueError):
        raise error from None
    if 4 in (a, b) and sorted((a, b)) != [3, 4]:
        raise error
    return a, b


def format_score(score: TennisScore) -> str:
    text = " ".join(f"{a}-{b}" for a, b in (*score.sets, score.games))
    if score.points != (0, 0):
        a, b = score.points
        text += f" ({a}-{b})" if score.in_tiebreak else f" ({_POINT_TEXT[a]}-{_POINT_TEXT[b]})"
    return text


def _set_over(games: tuple[int, int]) -> bool:
    high, low = max(games), min(games)
    return (high >= 6 and high - low >= 2) or high >= 7
