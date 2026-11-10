"""Eccezioni della pipeline.

Averne di specifiche permette all'app di distinguere i casi e mostrare il
messaggio giusto (es. chiave mancante vs limite giornaliero vs annullo).
"""
from __future__ import annotations


class ErrorePipeline(Exception):
    """Base di tutti gli errori previsti dalla pipeline."""


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

    def __init__(self, modello: str):
        self.modello = modello
        super().__init__(f"Il modello Gemini '{modello}' non è più disponibile "
                         "(Google l'ha ritirato).")
