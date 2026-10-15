"""Trascrittore — pipeline per trasformare una lezione in documenti Word.

Uso tipico (da codice):

    from trascrittore import Job, esegui
    from trascrittore.progress import ReporterConsole
    from trascrittore.config import FASI

    job = Job(sorgente=Path("lezione.mp4"), nome="Lezione 1", lingue_output=["it", "en"])
    risultato = esegui(job, chiave, ReporterConsole(FASI), work_base=Path("cache"))

Moduli:
    config      costanti e nomi dei modelli
    languages   lingue supportate
    errors      eccezioni della pipeline
    progress    Reporter (come comunica l'avanzamento)
    audio       ffmpeg (estrazione/segmentazione)
    gemini      client + retry
    transcribe  FASE 0-1 (audio → testo grezzo)
    textproc    FASE 2-3 (rileva lingua, pulisci, traduci)
    documents   FASE 4 (Word)
    pipeline    orchestratore (Job → Risultato)
"""
from __future__ import annotations

from .pipeline import Job, Risultato, esegui
from .progress import Reporter, ReporterConsole
from .errors import (
    ErrorePipeline,
    ChiaveMancante,
    LimiteGiornaliero,
    Interrotto,
    FfmpegMancante,
)

__all__ = [
    "Job", "Risultato", "esegui",
    "Reporter", "ReporterConsole",
    "ErrorePipeline", "ChiaveMancante", "LimiteGiornaliero", "Interrotto", "FfmpegMancante",
]
