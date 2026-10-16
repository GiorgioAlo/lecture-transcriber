"""Costanti e configurazione della pipeline.

Qui stanno tutti i "numeri" e i nomi dei modelli: cambiarli in un punto solo
basta per tutta l'app. Niente logica, solo valori.
"""
from __future__ import annotations

# Versione dell'app (semver). La mostra la UI e serve al controllo aggiornamenti
# (Step 3): viene confrontata col tag dell'ultima Release su GitHub.
VERSION = "1.2.0"

# --- Aggiornamenti dell'app (Step 3) --------------------------------------
# Repo PUBBLICO su cui stanno le Release (gli .exe nuovi). Finche' sono vuote la
# feature e' DORMIENTE (aggiornamenti.controlla() torna None): l'app non cerca
# nulla. Riempirle con owner/repo reali per attivarla.
GITHUB_OWNER = "GiorgioAlo"
GITHUB_REPO = "lecture-transcriber"
# Google Form per "Segnala un problema" (niente mail esposta, nessun account per
# l'amico). URL del form (`.../viewform`). Vuoto = pulsante nascosto.
URL_FORM_SEGNALAZIONE = "https://docs.google.com/forms/d/e/1FAIpQLSfDRTTnAdLGVp0TZk4yZDSmfs6IN-5jiuf5aYvSi7rMIpGd6Q/viewform"
# Campo del form in cui pre-compilare la versione dell'app (dal "link precompilato"
# di Google Form, es. "entry.123456789"). Vuoto = form aperto senza pre-compilare.
FORM_CAMPO_VERSIONE = "entry.625561092"
# Timeout del controllo aggiornamenti: corto perche' gira all'avvio (in un thread)
# e un GitHub lento non deve mai far aspettare. In caso di scadenza: no-op silenzioso.
TIMEOUT_CHECK_UPDATE_S = 5

# --- Modelli Gemini -------------------------------------------------------
ASR_MODEL = "gemini-3.5-flash-lite"               # FASE 1 PRIMARIA: trascrive blocchi da 10 min IN PARALLELO.
                                                  # Molto piu' veloce e con quota larga (RPD 500 vs 25), ma puo'
                                                  # allucinare/loopare/troncare un blocco → serve la guardia (transcribe.py).
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"        # trascrizione DEDICATA: usata SOLO come FALLBACK sui blocchi
                                                  # che falliscono la guardia 3 volte (affidabile, ma RPD 25).
TEXT_MODEL = "gemini-3.1-flash-lite-preview"      # pulizia + traduzione del testo
# Tetto di token in USCITA per pulizia/traduzione. Va alzato: col default
# (~8K token) un blocco grande verrebbe TRONCATO a meta' output (sembra un
# riassunto ma e' un taglio tecnico). Misurato: a blocchi grandi flash-lite
# resta fedele purche' abbia spazio per rispondere. (vedi esperimenti blocchi)
MAX_OUTPUT_TOKENS = 65535

# --- Trascrizione: temperatura + guardia anti-loop -------------------------
# Default BASSO = fedelta' verbatim (il modello non "inventa" parole). A volte,
# quando l'audio continua oltre il parlato (tipico nell'ULTIMO blocco: coda di
# silenzio/outro di fine lezione), il modello entra in loop e RICOPIA lo stesso
# pezzo finale decine di volte. Misurato: ri-trascrivere lo stesso audio ad
# altra temperatura NON rompe il loop (il trigger e' nell'audio, non nel
# sampling), costa solo richieste e attese. Quindi: una sola chiamata e, se la
# guardia (sotto) sospetta un loop, si SFOLTISCONO le ripetizioni sul testo.
TEMP_TRASCRIZIONE = 0.1               # temperatura normale (fedele)
# Soglia di sospetto loop: parole/minuto del blocco. Un parlato umano sta sui
# ~130-150 wpm; nemmeno un oratore veloce regge 300 wpm → oltre = quasi certo loop.
SOGLIA_LOOP_WPM = 300
# La guardia wpm si applica solo a blocchi abbastanza lunghi: su una coda di
# pochi secondi di parlato veloce il rapporto parole/minuto e' inaffidabile
# (falso positivo). Sotto questa durata trascrivo e basta, senza retry.
MIN_MIN_GUARDIA_LOOP = 3.0
# Ultima spiaggia, se anche i retry loopano: tengo al massimo N occorrenze della
# STESSA frase (il prof che ripete 2-3 volte resta; un loop di 21 volte no).
MAX_RIPETIZIONI_FRASE = 3

# --- Audio / blocchi -------------------------------------------------------
# Blocchi "bilanciati": N = ceil(durata / MAX_BLOCCO_MIN), poi tutti uguali
# (durata/N). Con ASR_MODEL (flash-lite) la taglia VINCENTE e' ~10 min: misurato
# che a 10 min allucina/loopa molto meno che a blocchi grandi, e i blocchi
# piccoli si trascrivono IN PARALLELO (vedi transcribe.trascrivi_chunks). Quindi
# una lezione = tanti blocchi da ~10 min tutti insieme, non pochi blocchi grandi.
MAX_BLOCCO_MIN = 10            # taglia di un blocco audio (minuti)

# --- Guardia ASR (flash-lite): rileva e corregge i blocchi "venuti male" ---
# flash-lite e' un ASR stocastico: su qualche blocco puo' (a) andare in RUNAWAY
# (loop/allucinazione: wpm altissima, o tetto token raggiunto, o una filata di
# numeri inventati), (b) TRONCARE (si ferma presto: wpm bassissima). La guardia
# ritenta il blocco (i fallimenti sono stocastici: un retry quasi sempre esce
# pulito) e, solo se TUTTI i tentativi sono runaway, ripiega su TRANSCRIBE_MODEL.
ASR_WORKER = 12                # blocchi audio trascritti IN PARALLELO (sotto l'RPM 15 di flash-lite)
ASR_MAX_TENTATIVI = 3          # tentativi flash-lite su un blocco prima del fallback transcribe
ASR_THINKING_BUDGET = 128      # budget di "thinking" basso = meno loop (0 e' VIETATO dal modello; alto = instabile)
ASR_CAP_WPM = 300              # cap max_output_tokens ~ durata*ASR_CAP_WPM*1.4: un runaway si ferma subito invece di sfornare 50K token
ASR_SOGLIA_RUNAWAY_WPM = 300   # oltre = quasi certo loop/allucinazione (parlato umano ~130-200 wpm)
ASR_SOGLIA_CORTO_WPM = 40      # sotto = sospetto troncamento (soglia bassa: il parlato rado reale sta sopra)
ASR_MIN_MIN_GUARDIA = 3.0      # le soglie wpm si applicano solo a blocchi piu' lunghi di tot (altrimenti wpm inaffidabile)
ASR_SOGLIA_RUN_NUMERI = 30     # una sequenza di piu' di N numeri consecutivi = runaway numerico (una tabella vera di 10-20 valori non scatta)

# --- Limiti API / ritmo ----------------------------------------------------
# Nessun pacing proattivo: i blocchi girano in parallelo e gli errori temporanei
# (429/503) li gestisce con_retry in modo REATTIVO, rispettando il retryDelay
# indicato dall'API (vedi gemini.con_retry). MARGINE_RETRY_S e' il piccolo
# cuscinetto aggiunto a quel tempo (il retryDelay e' un minimo: aspettare esatto
# puo' ribeccare il 429 al confine della finestra).
MARGINE_RETRY_S = 5            # secondi aggiunti al retryDelay dell'API
# Backoff per gli errori temporanei che NON portano un retryDelay (tipico del 503
# "high demand"): attesa = min(CAP, BASE*2^(tentativo-1)) + equal jitter. Tarati il
# 2026-10-15 (variante "B") da una simulazione: cap+jitter curano i "minuti" che
# faceva la vecchia 10*tentativo (saliva a 40/50s senza tetto, e i blocchi paralleli
# riprovavano in lockstep). Vedi gemini._attesa_backoff. BASE piccolo = riprova
# presto (il 503 spesso e' gia' passato); CAP basso = niente attese inutili da 50s.
BACKOFF_BASE_S = 2            # prima attesa nominale del backoff (poi raddoppia)
BACKOFF_CAP_S = 20           # tetto dell'attesa nominale del backoff

# --- Quota giornaliera (free tier) ----------------------------------------
# Ora la trascrizione primaria gira su ASR_MODEL (flash-lite): RPD 500, e ogni
# richiesta copre ~MAX_BLOCCO_MIN (10) minuti di audio. L'API free non da' un
# contatore, quindi contiamo noi le richieste fatte (1 per blocco trascritto) e
# le mostriamo come ore di audio ancora trascrivibili oggi. Con 500 e blocchi da
# 10 min sono ~83 ore/giorno = praticamente illimitato per l'uso normale.
RPD_TRASCRIZIONE = 500             # richieste/giorno sul modello ASR primario (flash-lite, free)
RICHIESTE_PER_LEZIONE_STIMA = 10   # ~richieste (blocchi) per una lezione tipica di ~100 min

# --- Elaborazione testo ---------------------------------------------------
# Blocchi GRANDI: misurato che flash-lite non riassume/inventa/loopa nemmeno con
# l'intera lezione in un blocco (serve solo MAX_OUTPUT_TOKENS alto). 20K char =
# ~3-4 blocchi per lezione invece di ~14 -> meno richieste, piu' veloce, meno cuciture.
MAX_CARATTERI_BLOCCO = 20000   # dimensione dei blocchi di testo mandati a Gemini
# Una lezione tipica (~67K char puliti) = ~4 blocchi: con 4 worker li elabora in
# UNA sola ondata (piu' veloce). 4 richieste insieme restano larghe sotto i tetti
# flash-lite (RPM 15, TPM 250K), quindi nessun rischio di 429 in uso normale.
WORKER_PARALLELI = 4           # blocchi di testo elaborati in parallelo
# MAX_TENTATIVI = budget di ritentativi su errori temporanei (429/503/...). Alzato
# 6->8 il 2026-10-15: col nuovo backoff capato (max ~20s/attesa) servono piu' giri
# per attraversare una contesa "high demand" lunga senza arrendersi. Simulazione: con
# cap 20 + jitter + 8 tentativi, l'ASR regge un'interruzione da 40s a 0% arrese tenendo
# la mediana ~41s (vs 62s della vecchia 10*tentativo). Vale per ASR (cuore del lavoro)
# e per lingua/materia. La FASE TESTO usa meno tentativi (vedi MAX_TENTATIVI_TESTO).
MAX_TENTATIVI = 8             # ritentativi su errori temporanei (429/503/...)
# La fase testo (pulizia/traduzione) si arrende PRIMA dell'ASR: se Google e' giu'
# (o rifiuta un blocco) meglio fallire in fretta, mettere un marcatore visibile nel
# Word al posto del blocco e avvisare l'utente, che insistere a lungo. L'ASR col budget
# pieno (8) tiene duro sul lavoro vero. Abbassato 5->3 il 2026-10-16: un blocco che non
# passa la pulizia e' quasi sempre un problema persistente (raro: il testo ha gia'
# passato la trascrizione) -> 3 giri bastano, poi si segna il buco e si prosegue.
MAX_TENTATIVI_TESTO = 3       # ritentativi nella fase testo (piu' bassi di MAX_TENTATIVI)
# Pausa PROATTIVA tra pulizia (FASE 2) e traduzione (FASE 3). DISATTIVATA (=0) il
# 2026-10-11 dopo misura su 4 lezioni reali: pulizia->traduzione SENZA pausa non
# ha mai preso un 429 TPM. Motivo: il TPM conta i soli token di INPUT (doc Gemini)
# e il burst di input della pulizia e' ~17K token/min = ~7% del limite da 250K →
# nessuna saturazione da evitare. Gli unici intoppi erano 503 "server sovraccarico",
# lato Google e indipendenti dal ritmo: nessuna pausa fissa li previene, li gestisce
# gia' con_retry in modo REATTIVO (aspetta il retryDelay indicato dall'API, o un
# backoff crescente se l'API non lo da'). Tenuta come costante: rimettere >0 la
# riattiva all'istante se un domani i limiti cambiano.
PAUSA_TESTO_S = 0              # secondi; 0 = nessuna pausa (vedi sopra)

# --- Timeout di rete delle chiamate API (secondi) --------------------------
# SENZA timeout, una richiesta che si pianta a livello di connessione (tipico
# quando il modello e' sovraccarico: il server accetta ma non risponde) resta
# appesa ALL'INFINITO, e nemmeno l'annullo la sblocca (con_retry aspetta un
# errore, non uno stallo muto). Col timeout la richiesta alza un errore dopo N
# secondi -> con_retry ritenta o si arrende in modo pulito. Valori generosi per
# non abortire chiamate lente ma legittime (un blocco audio lungo o un blocco di
# testo grande possono richiedere parecchi secondi).
# TIMEOUT_TESTO_S tarato a 40 il 2026-10-14 da una diagnostica (80 chiamate al
# modello di testo in parallelo): le chiamate LEGITTIME tornano in ~23s mediana,
# MAX osservato 33.5s (blocco reale da 20K char). 90s era 3x troppo: su una
# chiamata che si impianta sprecavamo 90s x tentativo. 40s sta sopra il max reale
# (margine) ma fa fallire in fretta un hang. NB: il grosso dei "minuti" di attesa
# NON era il timeout ma le raffiche di 503 "high demand" (senza retryDelay ->
# backoff nostro) che la diagnostica ha mostrato essere il vero intoppo comune.
TIMEOUT_TRASCRIZIONE_S = 180   # chiamate al modello transcribe (audio, piu' lente)
TIMEOUT_TESTO_S = 40           # chiamate al modello di testo (flash-lite) — vedi nota sopra

# --- Parallelizzazione della coda (pipeline tra lezioni) -------------------
# Mentre una lezione viene elaborata, lo Stadio 0 (download + estrazione audio,
# nessuna API) delle lezioni SUCCESSIVE in coda viene preparato in anticipo, in
# un thread a parte, cosi quando la trascrizione passa alla prossima l'audio e'
# gia' pronto. Il collo di bottiglia resta la trascrizione (1 sola alla volta,
# API transcribe), quindi tenere poche lezioni "avanti" basta: oltre si occupa
# solo disco senza guadagno. 2 = lezione corrente + 1 pronta in anticipo.
PREFETCH_LEZIONI = 2

# Marcatore inserito nel testo quando un blocco non si riesce a elaborare:
# serve a riconoscere un risultato incompleto (per ripresa / avvisi).
MARCATORE_ERRORE = "[⚠️ ERRORE CRITICO"

# --- Le 5 fasi mostrate dalla barra di avanzamento ------------------------
# L'ordine e il testo DEVONO combaciare con la UI (ui/index.html) e con
# gli indici usati da pipeline.py.
FASI = [
    "Scarico l'audio",      # 0 — per un file locale = estrazione/preparazione audio
    "Trascrivo il parlato",  # 1
    "Pulisco il testo",      # 2
    "Traduco",               # 3
    "Creo i documenti",      # 4
]
