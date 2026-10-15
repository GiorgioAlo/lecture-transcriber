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
