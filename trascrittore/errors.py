"""Eccezioni della pipeline.

Averne di specifiche permette all'app di distinguere i casi e mostrare il
messaggio giusto (es. chiave mancante vs limite giornaliero vs annullo).
"""
from __future__ import annotations


class Messaggio(str):
    """Frase per l'utente: E' la frase italiana (cosi' CLI, log e chi la usa come
    stringa non vedono differenze) ma si porta dietro il CODICE con cui l'app la
    traduce nella lingua dell'interfaccia (dizionario I18N di ui/index.html,
    chiavi `py.*`) e gli eventuali valori da inserire ({nome}, {n}...)."""

    codice: str
    valori: dict

    def __new__(cls, testo: str, codice: str, **valori):
        s = super().__new__(cls, testo)
        s.codice = codice
        s.valori = valori
        return s


class ErrorePipeline(Exception):
    """Base di tutti gli errori previsti dalla pipeline.

    Se il messaggio e' un `Messaggio`, l'errore ne ricorda codice e valori
    (`codice`/`valori`), cosi' l'app puo' mostrarlo tradotto."""

    def __init__(self, *args):
        super().__init__(*args)
        primo = args[0] if args else None
        self.codice: str | None = getattr(primo, "codice", None)
        self.valori: dict = dict(getattr(primo, "valori", None) or {})


class ChiaveMancante(ErrorePipeline):
    """Manca la chiave API di Gemini."""


class LimiteGiornaliero(ErrorePipeline):
    """Esaurita la quota giornaliera dell'API (429 persistente)."""


class Interrotto(ErrorePipeline):
    """L'utente ha annullato il lavoro."""


class FfmpegMancante(ErrorePipeline):
    """ffmpeg/ffprobe non trovati nel sistema."""


class DownloadFallito(ErrorePipeline):
    """Impossibile scaricare l'audio dal link (link protetto, cookie scaduti, rete...)."""


class ContenutoBloccato(ErrorePipeline):
    """Gemini ha RIFIUTATO di elaborare l'audio/il testo (filtro di sicurezza,
    copyright/recitation, blocklist). Non c'e' nulla da ritentare: la risposta
    torna senza candidati. Distinta dalle altre per dare un messaggio chiaro."""


class ModelloNonDisponibile(ErrorePipeline):
    """Google ha RITIRATO (o reso inaccessibile) un modello Gemini che l'app usa.
    Sollevata SOLO quando il ritiro e' CERTO: l'API risponde 404 NOT_FOUND citando
    quel modello E una verifica con `models.get` conferma che non esiste piu'
    (vedi gemini.con_retry). Ritentare e' inutile e passare alla lezione dopo
    pure: va fermata tutta la coda, come per il limite giornaliero."""

    def __init__(self, modello: str, suggerito: str | None = None):
        self.modello = modello
        self.suggerito = suggerito      # sostituto indicato da Google nel messaggio, se c'e'
        super().__init__(Messaggio(f"Il modello Gemini '{modello}' non è più disponibile "
                                   "(Google l'ha ritirato).", "py.err.model.d", modello=modello))
