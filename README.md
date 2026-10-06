# Bet: strategie in-play su Betfair Exchange

Descrivi in un file YAML l'andamento che ti aspetti e le regole per entrare e uscire.
Il motore le controlla a ogni aggiornamento di punteggio e quote e piazza gli ordini.

> **Stato attuale: solo simulazione** (paper trading su scenari di partita).
> Il collegamento a Betfair in tempo reale è il passo successivo: vedi [Verso il live](#verso-il-live).

## Avvio rapido

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

bet controlla strategie/                                          # valida le strategie e spiega cosa faranno
bet simula strategie/ --scenario scenari/ --config config.yaml   # le prova sugli scenari di esempio
bet variabili                                                     # variabili utilizzabili nelle condizioni
pytest
```

## Scrivere una strategia

Esempio: *"mi aspetto la rimonta in WTA. Quando una delle due va sotto di un set e un break,
entra alla quota migliore se ci sono almeno 50 € disponibili"*.

```yaml
nome: Rimonta WTA — sotto di un set e un break
andamento: >
  Mi aspetto la rimonta: in WTA chi perde il primo set e va sotto di un break
  nel secondo viene quotata troppo alta.

mercato:
  circuito: WTA
  escludi: [ITF, Doubles]

quando: set_sotto >= 1 e break_sotto >= 1

ingresso:
  lato: BACK
  prezzo: migliore
  liquidita_minima: 50
  puntata: 10

uscita:                                    # facoltativa
  quando: pl_green_pct >= 40 o break_sotto >= 2
```

Altri esempi sono in [`strategie/`](strategie/). Con `bet controlla` ottieni la spiegazione in
italiano di quello che la strategia farà: rileggila prima di usarla.

### Sezioni

| Campo | Significato | Predefinito |
|---|---|---|
| `nome` | nome della strategia | obbligatorio |
| `andamento` | la tua aspettativa, in parole tue (non influisce sulle regole) | |
| `attiva` | `false` per spegnerla senza cancellarla | `true` |
| `id` | nome breve nei log | nome del file |
| `mercato.circuito` | la competizione deve contenere uno di questi testi (es. `WTA`) | tutte |
| `mercato.escludi` | scarta le partite la cui competizione o il cui evento contengono questi testi | |
| `mercato.solo_singolare` | scarta i doppi | `true` |
| `mercato.solo_giocatori` | entra solo su questi giocatori (basta parte del nome) | tutti |
| `quando` | condizione di ingresso (vedi sotto) | obbligatorio |
| `ingresso.lato` | `BACK` (punti sul giocatore) o `LAY` (banchi il giocatore) | `BACK` |
| `ingresso.prezzo` | `migliore` = prende la quota migliore disponibile; `migliore+N` = chiede N tick in più e resta in attesa | `migliore` |
| `ingresso.liquidita_minima` | € che devono esserci alla quota migliore, altrimenti aspetta | `0` |
| `ingresso.puntata` | importo | obbligatorio |
| `ingresso.tipo_puntata` | `fissa` (€), `percentuale_bankroll` (% del bankroll in `config.yaml`), `responsabilita` (€ di perdita massima: per il LAY calcola la puntata) | `fissa` |
| `ingresso.annulla_non_abbinato_dopo` | secondi dopo i quali la parte non abbinata viene annullata (`0` = abbina subito quello che c'è e annulla il resto) | `10` |
| `ingresso.max_ingressi_per_match` | quante volte può entrare nella stessa partita | `1` |
| `uscita.quando` | condizione per chiudere la posizione in green alla quota migliore | nessuna uscita |
| `uscita.annulla_non_abbinato_dopo` | come sopra, per gli ordini di chiusura | `10` |

### Come vengono valutate le regole

- **Su entrambi i giocatori.** `quando` viene controllata separatamente per ciascuno dei due
  giocatori, dal suo punto di vista. "Una delle due va sotto di un set e un break" si scrive
  quindi `set_sotto >= 1 e break_sotto >= 1`, e la strategia entra sul giocatore per cui la
  condizione è vera.
- **A ogni aggiornamento.** La condizione non deve diventare vera in un istante preciso: basta
  che lo sia. Se è vera ma la liquidità alla quota migliore è sotto il minimo, la strategia
  aspetta e riprova al prossimo aggiornamento.
- **Dati mancanti = falso.** Se un dato non c'è (punteggio non ancora disponibile, servizio non
  fornito dal feed, nessuna quota) la condizione è falsa. Così non si entra mai "al buio".
- **Ritardo in-play.** In gioco Betfair trattiene gli ordini per alcuni secondi prima di
  inserirli nel mercato (il `betDelay` del mercato). Se in quel tempo la quota peggiora, l'ordine
  resta in attesa al suo prezzo e viene annullato dopo `annulla_non_abbinato_dopo`. Se la
  condizione è ancora vera, la strategia riprova alla nuova quota migliore.
- **Uscita in green.** Quando `uscita.quando` diventa vera, la strategia annulla l'eventuale
  ingresso ancora in attesa e piazza la scommessa opposta che rende uguale il risultato su
  entrambi gli esiti. Continua finché la posizione non è chiusa, anche se nel frattempo la
  condizione torna falsa.
- **Rischio.** Con `esposizione_massima` in `config.yaml` nessun nuovo ingresso può portare la
  perdita massima possibile (posizioni più ordini aperti) oltre quel limite.

### Variabili

Punteggio, dal punto di vista del giocatore valutato:

| Variabile | Significato |
|---|---|
| `set_giocatore`, `set_avversario` | set vinti |
| `set_sotto` | set di svantaggio (0 se non è sotto) |
| `set_corrente` | numero del set in corso |
| `game_giocatore`, `game_avversario` | game nel set in corso |
| `break_sotto`, `break_sopra` | break netti di svantaggio / vantaggio nel set in corso |
| `al_servizio` | vero se il giocatore è al servizio |
| `palla_break_contro`, `palla_break_a_favore` | palla break sul suo servizio / a suo favore |
| `tiebreak` | vero durante il tiebreak |

Mercato:

| Variabile | Significato |
|---|---|
| `giocatore`, `avversario`, `competizione` | nomi (testo), es. `"Swiatek" in giocatore` |
| `in_play` | vero se il mercato è in gioco |
| `quota_back`, `liquidita_back` | migliore quota per puntare e € disponibili a quella quota |
| `quota_lay`, `liquidita_lay` | migliore quota per bancare e € disponibili a quella quota |
| `spread_tick` | tick tra quota back e lay (misura quanto è liquido il mercato) |
| `ultima_quota` | ultima quota abbinata |
| `quota_prematch`, `quota_prematch_avversario` | quote back prima dell'inizio |
| `favorito_prematch` | vero se era il favorito della vigilia |
| `variazione_quota_pct` | variazione % della quota rispetto al prematch |
| `volume_mercato` | € abbinati sul mercato |

Posizione (solo in `uscita.quando`):

| Variabile | Significato |
|---|---|
| `puntata`, `quota_ingresso` | € abbinati in ingresso e quota media |
| `pl_se_vince`, `pl_se_perde` | profitto per esito, senza chiudere |
| `pl_green`, `pl_green_pct` | risultato garantito chiudendo ora alla quota migliore (€ e % della puntata) |

**Break netti.** Con il servizio noto il conto è esatto: i game serviti dal giocatore nel set
meno quelli che ha vinto. Se il feed non indica chi serve si usa una stima prudente (metà dello
svantaggio in game, arrotondata per difetto): sotto 1-3 conta come un break, 2-3 no.

### Operatori

- Confronti: `>= <= > < == !=`, anche a catena: `2.5 <= quota_back <= 6`
- Logica: `e`, `o`, `non` (oppure `and`, `or`, `not`); `vero` / `falso`
- Calcoli: `+ - * /`, `abs()`, `min()`, `max()`
- Testi tra virgolette: `"Swiatek" in giocatore`

Esempi:

```text
set_sotto >= 1 e break_sotto >= 1 e favorito_prematch
set_corrente == 3 e break_sotto >= 1 e non al_servizio e quota_back <= 5
palla_break_contro e liquidita_lay >= 200 e spread_tick <= 2
variazione_quota_pct >= 80 e set_sotto == 1 e volume_mercato >= 20000
```

## Scenari di simulazione

Uno scenario descrive una partita nel tempo: quote, punteggio, servizio. Vedi
[`scenari/`](scenari/) per il formato completo. In sintesi:

```yaml
partita:
  mercato_id: "1.900000001"
  evento: Anna Rossi v Bea Bianchi
  competizione: WTA Tokyo 2026
  ritardo_inplay: 3
  giocatori:
    A: {nome: Anna Rossi, id: 101}
    B: {nome: Bea Bianchi, id: 102}
eventi:
  - t: "-10:00"
    quote: {A: "1.55/1.56 @ 900/1200", B: "2.80/2.82 @ 700/650"}
  - t: 0
    in_play: true
    punteggio: "0-0"
    servizio: A                 # basta una volta: poi si alterna da solo a ogni game
  - t: "44:00"
    punteggio: "4-6 0-2"
    punti: "0-15"
    quote: {A: "3.40/3.45 @ 30/90"}
  - t: "1:52:00"
    vincitore: A
```

Le quote si scrivono `back/lay @ €back/€lay` e devono stare sulla scala dei tick di Betfair.

## Limiti della simulazione

La simulazione è **ottimista**. Prima di fidarti dei numeri tieni conto che:

- vede solo il primo livello del book;
- un ordine che entra trova tutta la liquidità mostrata;
- un ordine in attesa viene abbinato appena il mercato raggiunge il suo prezzo, senza la coda
  di chi c'era prima.

Sul mercato reale gli abbinamenti degli ordini in attesa saranno meno frequenti. Gli scenari di
esempio sono inventati: servono a verificare che le regole facciano ciò che intendi, non a
stimare il rendimento.

## Verso il live

1. **Accesso API Betfair**: app key (quella "delayed" basta per sviluppare) e login con
   certificato. Le credenziali restano fuori dal repository. Va scelto l'exchange (betfair.it
   o .com): la liquidità è diversa.
2. **Adattatore Betfair**: lo stream delle quote (Exchange Stream API) viene convertito in
   `MarketBook`, con il `betDelay` letto dalla definizione del mercato. Gli ordini del
   `PaperBroker` diventano ordini limite reali. Il motore e le strategie restano gli stessi.
   Base consigliata: `betfairlightweight` / `flumine`.
3. **Feed dei punteggi tennis**: è la scelta più delicata. Le regole su set e break dipendono
   da un punteggio punto per punto, con il servizio, affidabile e veloce. Il mercato si muove
   prima del tuo feed: le strategie come la rimonta non sono una gara di velocità, ma un feed
   lento significa entrare a quote già peggiorate. Le opzioni (fornitori a pagamento, servizi
   di Betfair) vanno valutate per copertura WTA/ATP/ITF, latenza e costo.
4. **Registrazione**: ogni partita seguita (quote e punteggi) va salvata nel formato scenario,
   così si possono provare le strategie su partite vere e non solo su scenari inventati.
5. **Gradualità**: prima settimane di paper trading sul mercato reale, poi puntate minime, con
   un limite di perdita giornaliera e un interruttore di emergenza.

## Struttura del codice

| Modulo | Contenuto |
|---|---|
| `src/bet/strategy.py` | formato delle strategie, caricamento, spiegazione in italiano |
| `src/bet/expr.py` | linguaggio delle condizioni (interpretato in modo sicuro, senza `eval`) |
| `src/bet/context.py` | elenco e calcolo delle variabili |
| `src/bet/tennis.py` | punteggio: set, break netti, palle break |
| `src/bet/engine.py` | motore: valuta le regole, piazza e segue gli ordini, chiude le posizioni |
| `src/bet/broker.py` | esecuzione simulata (paper trading) con ritardo in-play |
| `src/bet/position.py` | profitto per esito e calcolo del green |
| `src/bet/ladder.py` | scala dei tick Betfair |
| `src/bet/replay.py` | scenari di partita |
| `src/bet/cli.py` | comandi `bet controlla`, `bet simula`, `bet variabili` |
