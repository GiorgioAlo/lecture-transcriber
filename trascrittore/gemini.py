"""Client Gemini e gestione dei ritentativi.

Un punto solo per: creare il client dalla chiave, e riprovare in automatico
quando l'API risponde con un errore temporaneo (limite, server sovraccarico...).
"""
from __future__ import annotations

import logging
import math
import random
import time
from typing import Callable, TypeVar

from google import genai
from google.genai import types

from . import config
from .errors import ChiaveMancante, ContenutoBloccato, Interrotto, LimiteGiornaliero

# Nasconde i warning rumorosi del client (AFC / non-text-parts).
for _n in ("google_genai.models", "google_genai.types", "google_genai"):
    logging.getLogger(_n).setLevel(logging.ERROR)

T = TypeVar("T")

# Filtri di sicurezza su BLOCK_NONE. Stiamo TRASCRIVENDO e traducendo FEDELMENTE
# cio' che viene detto (in aula o in un video): parolacce, bestemmie e volgarita'
# incluse. Coi filtri di DEFAULT Gemini a volte RIFIUTA un blocco con contenuti
# che considera "sensibili" e torna una risposta VUOTA (nessun candidato) -> la
# trascrizione di quel pezzo andava persa (e prima mandava l'app in crash). Non
# siamo noi a generare quei contenuti: li riportiamo e basta, quindi disattiviamo
# il blocco. (Restano fuori dal nostro controllo casi come il copyright.)
IMPOSTAZIONI_SICUREZZA = [
    types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
    for c in (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]


def crea_client(chiave: str, timeout_s: float | None = None) -> genai.Client:
    """Crea il client Gemini. Solleva ChiaveMancante se la chiave e vuota.

    `timeout_s`: timeout di rete (in secondi) per OGNI richiesta fatta da questo
    client. Senza, una richiesta che stalla resta appesa all'infinito; col
    timeout alza un errore dopo N secondi e con_retry puo' gestirlo. L'SDK vuole
    il timeout in millisecondi (HttpOptions)."""
    chiave = (chiave or "").strip()
    if not chiave:
        raise ChiaveMancante("Manca la chiave API di Gemini.")
    http_options = types.HttpOptions(timeout=int(timeout_s * 1000)) if timeout_s else None
    return genai.Client(api_key=chiave, http_options=http_options)


def _attendi_annullabile(secondi: float, interrotto: Callable[[], bool] | None) -> None:
    """Dorme `secondi` ma a passi di 1s controllando l'annullo.

    Sostituisce un `time.sleep(secondi)` secco: un'attesa di retry puo' durare
    ~60s e prima "ingoiava" l'Annulla (si controllava solo DOPO l'attesa). Ora,
    se nel frattempo l'utente annulla, solleva Interrotto entro ~1s."""
    passi = max(1, int(math.ceil(secondi)))
    for _ in range(passi):
        if interrotto is not None and interrotto():
            raise Interrotto()
        time.sleep(1)


def _classifica_errore(e: Exception) -> str:
    """Per errori NON-429: motivo leggibile per il log."""
    err = str(e).lower()
    if any(x in err for x in ("503", "500", "unavailable", "overloaded", "internal")):
        return "SERVER SOVRACCARICO"
    return f"ERRORE: {str(e)[:80]}"


def _attesa_backoff(tentativo: int) -> float:
    """Attesa per un errore temporaneo SENZA retryDelay dall'API (tipico del 503
    'high demand', che non porta RetryInfo). Variante "B" scelta il 2026-10-15.

    `min(CAP, BASE*2^(n-1))` con "equal jitter" (meta' fissa + meta' casuale):
    - esponenziale con un TETTO (`BACKOFF_CAP_S`): la vecchia `10*tentativo` lineare
      saliva a 40/50s senza motivo (un 503 'high demand' si libera in pochi secondi,
      aspettare 50s non aiuta) -> erano quelli i "minuti" di attesa;
    - il JITTER sparpaglia i ritentativi dei blocchi paralleli (ASR 12 worker, testo
      4): senza, riproverebbero tutti nello stesso istante ri-scontrandosi sul server
      carico (lockstep). La meta' fissa garantisce comunque un'attesa minima.
    Confronto a numeri (simulazione) nella memoria del progetto."""
    nominale = min(config.BACKOFF_CAP_S, config.BACKOFF_BASE_S * 2 ** (tentativo - 1))
    return nominale / 2 + random.uniform(0, nominale / 2)


def _dettagli_errore(e: Exception) -> tuple[int | None, bool]:
    """Legge un errore Gemini: (secondi di retryDelay o None, e_limite_giornaliero).

    Vale per QUALSIASI errore, non solo il 429: anche un 503/overloaded puo'
    portare un RetryInfo col tempo da aspettare, e noi vogliamo rispettarlo.
    Il corpo e in APIError.details["error"]["details"]: RetryInfo porta il
    retryDelay ("27s"), QuotaFailure dice quale quota (id con PerDay = RPD).
    Errori non-API (es. RuntimeError nostro) non hanno details -> (None, False).
    """
    rd: int | None = None
    per_giorno = False
    det = getattr(e, "details", None) or {}
    err = det.get("error", det) if isinstance(det, dict) else {}
    for d in (err.get("details") or []) if isinstance(err, dict) else []:
        tipo = d.get("@type", "")
        if "RetryInfo" in tipo:
            v = d.get("retryDelay")
            if isinstance(v, str) and v.endswith("s"):
                try:
                    rd = int(float(v[:-1]))
                except ValueError:
                    pass
        if "QuotaFailure" in tipo:
            for viol in d.get("violations", []):
                qid = viol.get("quotaId", "") or ""
                if "PerDay" in qid or "PerModelPerDay" in qid:
                    per_giorno = True
    return rd, per_giorno


def con_retry(
    azione: Callable[[], T],
    descrizione: str,
    log: Callable[[str], None] = lambda _m: None,
    interrotto: Callable[[], bool] | None = None,
    max_tentativi: int = config.MAX_TENTATIVI,
) -> T:
    """Esegue `azione()` riprovando sugli errori temporanei.

    Rispetta SEMPRE il `retryDelay` indicato dall'API quando c'e' (sia sul 429
    "al minuto" sia su un 503/overloaded che lo porta con se'), + un margine, e
    lo rilegge ad ogni giro. Sul 429 "al giorno" (RPD) si ferma subito con
    LimiteGiornaliero (inutile aspettare ore). Se l'API non da' un tempo, usa
    un'attesa crescente nostra. Dopo `max_tentativi` rilancia.

    `interrotto`: se fornita, l'attesa tra un tentativo e l'altro e' annullabile
    (solleva Interrotto entro ~1s invece di dormire l'intero ritardo).
    """
    for tentativo in range(1, max_tentativi + 1):
        try:
            return azione()
        except ContenutoBloccato:
            raise               # Gemini ha rifiutato il contenuto: inutile ritentare
        except Exception as e:
            rd, per_giorno = _dettagli_errore(e)
            if per_giorno:
                log(f"🛑 [{descrizione}] quota giornaliera esaurita")
                raise LimiteGiornaliero(
                    "Hai finito le trascrizioni gratuite di oggi. Riprova domani: "
                    "il lavoro gia fatto viene ripreso da dove si era fermato."
                )
            if getattr(e, "code", None) == 429:
                # rate limit al minuto: l'API di solito da' il retryDelay (se no, 30s)
                attesa = (rd if rd is not None else 30) + config.MARGINE_RETRY_S
                motivo = "LIMITE al minuto (TPM)"
            elif rd is not None:
                # anche un 503/overloaded puo' portare un RetryInfo: lo rispettiamo
                motivo = _classifica_errore(e)
                attesa = rd + config.MARGINE_RETRY_S
            else:
                # nessun tempo dall'API (tipico del 503 'high demand'): backoff
                # nostro capato + esponenziale + jitter (vedi _attesa_backoff)
                motivo = _classifica_errore(e)
                attesa = _attesa_backoff(tentativo)
            if tentativo == max_tentativi:
                raise
            log(f"⏳ [{descrizione}] {motivo} — riprovo tra {attesa:.0f}s ({tentativo}/{max_tentativi})")
            _attendi_annullabile(attesa, interrotto)
    # Irraggiungibile: il loop o ritorna o rilancia.
    raise RuntimeError(f"{descrizione}: tentativi esauriti")
