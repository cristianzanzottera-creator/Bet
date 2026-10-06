"""Variabili utilizzabili nelle condizioni e loro valore per un giocatore."""

from __future__ import annotations

from . import ladder
from .market import Match
from .position import Position

SCORE_VARIABLES: dict[str, str] = {
    "set_giocatore": "set vinti dal giocatore valutato",
    "set_avversario": "set vinti dall'avversario",
    "set_sotto": "set di svantaggio (0 se non è sotto)",
    "set_corrente": "numero del set in corso (1, 2, 3...)",
    "game_giocatore": "game vinti dal giocatore nel set in corso",
    "game_avversario": "game vinti dall'avversario nel set in corso",
    "break_sotto": "break netti di svantaggio nel set in corso",
    "break_sopra": "break netti di vantaggio nel set in corso",
    "al_servizio": "vero se il giocatore è al servizio",
    "palla_break_contro": "vero se l'avversario ha palla break sul servizio del giocatore",
    "palla_break_a_favore": "vero se il giocatore ha palla break",
    "tiebreak": "vero durante il tiebreak",
}

MARKET_VARIABLES: dict[str, str] = {
    "giocatore": "nome del giocatore valutato (testo)",
    "avversario": "nome dell'avversario (testo)",
    "competizione": "nome della competizione (testo)",
    "in_play": "vero se il mercato è in gioco",
    "quota_back": "migliore quota disponibile per puntare (back)",
    "liquidita_back": "€ disponibili alla migliore quota back",
    "quota_lay": "migliore quota disponibile per bancare (lay)",
    "liquidita_lay": "€ disponibili alla migliore quota lay",
    "spread_tick": "distanza in tick tra quota back e quota lay",
    "ultima_quota": "ultima quota abbinata",
    "quota_prematch": "quota back del giocatore prima dell'inizio",
    "quota_prematch_avversario": "quota back dell'avversario prima dell'inizio",
    "favorito_prematch": "vero se era il favorito prima dell'inizio",
    "variazione_quota_pct": "variazione % di quota_back rispetto a quota_prematch",
    "volume_mercato": "€ abbinati in totale sul mercato",
}

POSITION_VARIABLES: dict[str, str] = {
    "puntata": "€ abbinati in ingresso",
    "quota_ingresso": "quota media di ingresso",
    "pl_se_vince": "profitto (€) se il giocatore vince, senza chiudere",
    "pl_se_perde": "profitto (€) se il giocatore perde, senza chiudere",
    "pl_green": "risultato (€) garantito chiudendo ora alla migliore quota, prima della commissione",
    "pl_green_pct": "pl_green in % della puntata",
}

ENTRY_VARIABLES = {**SCORE_VARIABLES, **MARKET_VARIABLES}
EXIT_VARIABLES = {**ENTRY_VARIABLES, **POSITION_VARIABLES}
VARIABLES = EXIT_VARIABLES


def build_context(match: Match, i: int, position: Position | None = None) -> dict[str, object]:
    """Valori delle variabili dal punto di vista del giocatore `i` (0 = A, 1 = B).

    Le variabili senza dato (punteggio non ancora noto, nessuna quota, nessuna posizione) valgono None.
    """
    me, opponent = match.players[i], match.players[1 - i]
    values: dict[str, object] = dict.fromkeys(VARIABLES)
    values.update(giocatore=me.name, avversario=opponent.name, competizione=match.competition)

    score = match.score
    if score is not None:
        won, lost = score.sets_won(i), score.sets_won(1 - i)
        breaks = score.net_breaks_against(i)
        values.update(
            set_giocatore=won,
            set_avversario=lost,
            set_sotto=max(0, lost - won),
            set_corrente=score.set_number,
            game_giocatore=score.games[i],
            game_avversario=score.games[1 - i],
            break_sotto=max(0, breaks),
            break_sopra=max(0, -breaks),
            al_servizio=score.is_serving(i),
            palla_break_contro=score.break_point_against(i),
            palla_break_a_favore=score.break_point_against(1 - i),
            tiebreak=score.in_tiebreak,
        )

    if match.book is not None:
        values.update(in_play=match.book.in_play, volume_mercato=match.book.total_matched)
    runner = match.runner(i)
    if runner is not None:
        values.update(
            quota_back=runner.back_price,
            liquidita_back=runner.back_size,
            quota_lay=runner.lay_price,
            liquidita_lay=runner.lay_size,
            ultima_quota=runner.last_traded,
        )
        if runner.back_price is not None and runner.lay_price is not None:
            values["spread_tick"] = ladder.ticks_between(runner.back_price, runner.lay_price)

    prematch = match.prematch.get(me.selection_id)
    prematch_opponent = match.prematch.get(opponent.selection_id)
    values.update(quota_prematch=prematch, quota_prematch_avversario=prematch_opponent)
    if prematch is not None and prematch_opponent is not None:
        values["favorito_prematch"] = prematch < prematch_opponent
    if prematch is not None and runner is not None and runner.back_price is not None:
        values["variazione_quota_pct"] = (runner.back_price / prematch - 1) * 100

    if position is not None and position.stake > 0:
        values.update(
            puntata=position.stake,
            quota_ingresso=position.entry_price,
            pl_se_vince=position.if_win,
            pl_se_perde=position.if_lose,
        )
        hedge = position.hedge(runner.back_price, runner.lay_price) if runner is not None else None
        if hedge is not None:
            values.update(pl_green=hedge.locked_profit, pl_green_pct=hedge.locked_profit / position.stake * 100)
    return values
