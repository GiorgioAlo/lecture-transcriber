"""Orchestratore della pipeline: da un `Job` ai documenti finali.

Mette in fila le 5 fasi, aggiorna il Reporter (fase per fase + percentuale),
controlla l'annullo e riusa i risultati gia calcolati (ripresa).

E' il SOLO punto che conosce l'ordine delle fasi: i moduli transcribe/textproc/
documents fanno un lavoro ciascuno e non si parlano fra loro.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, documents, languages, textproc, transcribe, util
from .errors import Interrotto
from .gemini import crea_client, _attendi_annullabile
from .progress import Reporter

# Lingue delle 5 fasi → quota di percentuale ciascuna (5 fasi uguali = 20% l'una).
_N_FASI = len(config.FASI)


def _pct(fase: int, frazione: float = 1.0) -> float:
    """Percentuale complessiva data la fase (0..4) e quanto e avanzata (0..1)."""
    return min(100.0, (fase + max(0.0, min(1.0, frazione))) / _N_FASI * 100.0)


def nome_pulito(testo: str) -> str:
    """Rende una stringa adatta a un nome di file/cartella."""
    return re.sub(r"[^\w\-]+", "_", testo).strip("_") or "lezione"


def identita_job(job: "Job") -> str:
    """Stringa che identifica UNIVOCAMENTE la sorgente di un Job.

    E' il percorso del file, oppure l'url del link, oppure (fallback) il nome.
    Serve a dare a ogni lezione una cartella di lavoro diversa anche quando due
    sorgenti hanno lo stesso nome (es. due 'lezione.mp4' in cartelle diverse)."""
    if job.sorgente is not None:
        return str(job.sorgente)
    if job.url:
        return job.url
    return job.nome or "lezione"


def cartella_lavoro(work_base: Path, nome: str, identita: str) -> Path:
    """Cartella di lavoro per una lezione: nome leggibile + hash dell'identita'.

    L'hash (8 hex del path/url) evita le COLLISIONI: due file diversi con lo
    stesso nome finivano nella stessa cartella e il secondo riusava la
    trascrizione del primo. Con l'hash ognuno ha la sua."""
    h = hashlib.sha1(identita.encode("utf-8", "replace")).hexdigest()[:8]
    return work_base / f"{nome_pulito(nome)}_{h}"


@dataclass
class Job:
    """Tutto cio che serve per trascrivere UNA lezione."""
    sorgente: Path | None = None       # file audio/video locale (None se arriva da un link)
    nome: str = "lezione"              # nome della lezione (per file e titoli)
    lingue_output: list[str] = field(default_factory=lambda: ["it", "en"])
    corso: str = ""                    # nome del corso (aiuta Gemini), facoltativo
    inizio: float = 0.0                # minuto di partenza (per test su spezzoni)
    minuti: float | None = None        # durata da usare (None = tutta)
    testo: Path | None = None          # trascrizione gia pronta: salta FASE 0-1
    url: str | None = None             # link da scaricare (YouTube, Webex...) invece di un file
    cookies: str | None = None         # file cookies.txt (per Webex), tenuto solo in RAM
    password: str | None = None        # password del video (Webex), facoltativa


@dataclass
class Risultato:
    nome: str
    work_dir: Path
    lingua_sorgente: str               # codice della lingua parlata rilevata
    testi: dict[str, str] = field(default_factory=dict)   # codice lingua → testo finale
    documenti: list[Path] = field(default_factory=list)   # .docx generati
    blocchi_falliti: int = 0
    completo: bool = True


def _fase_valida(path: Path, rifai: bool) -> bool:
    """True se il file esiste, non va rifatto e non contiene blocchi mancanti."""
    return (not rifai) and path.exists() and config.MARCATORE_ERRORE not in path.read_text(encoding="utf-8")


def fase_trascrizione(job: Job, client, reporter: Reporter, work_dir: Path, rifai: bool = False) -> str:
    """STADIO 0-1: procura l'audio e lo trascrive. Ritorna la grezza (testo).

    E' lo stadio legato all'API transcribe. Separato da `fase_testo` cosi, nella
    coda parallela (coda.py), la trascrizione di una lezione puo' girare mentre
    il testo (flash-lite) di quella precedente viene elaborato."""
    grezza = work_dir / "grezza.txt"

    def stop_se_annullato():
        if reporter.interrotto():
            raise Interrotto()

    # ---- FASE 0-1: audio + trascrizione (o riuso) ----
    if job.testo is not None:
        reporter.fase(0, "fatta"); reporter.fase(1, "attiva")
        raw = Path(job.testo).read_text(encoding="utf-8")
        util.scrivi_testo(grezza, raw)
        reporter.fase(1, "fatta"); reporter.avanzamento(_pct(1))
    elif _fase_valida(grezza, rifai):
        reporter.log("Trascrizione gia presente, la riuso")
        reporter.fase(0, "fatta"); reporter.fase(1, "fatta")
        raw = grezza.read_text(encoding="utf-8")
        reporter.avanzamento(_pct(1))
    else:
        reporter.fase(0, "attiva")
        chunks = transcribe.prepara_audio(
            job.sorgente, work_dir, job.inizio, job.minuti, reporter,
            url=job.url, cookies=job.cookies, password=job.password,
            avanzamento=lambda fr: reporter.avanzamento(_pct(0, fr)),
        )
        reporter.fase(0, "fatta"); reporter.avanzamento(_pct(0))
        stop_se_annullato()

        reporter.fase(1, "attiva")
        raw = transcribe.trascrivi_chunks(
            client, chunks, work_dir, reporter,
            avanzamento=lambda fr: reporter.avanzamento(_pct(1, fr)),
        )
        util.scrivi_testo(grezza, raw)
        reporter.fase(1, "fatta")
    reporter.log(f"{len(raw.split())} parole trascritte")
    stop_se_annullato()
    return raw


def fase_testo(job: Job, client, reporter: Reporter, work_dir: Path, raw: str, rifai: bool = False) -> Risultato:
    """STADIO 2: lingua + materia + pulizia + traduzione + Word. Ritorna il Risultato.

    E' lo stadio legato all'API testo (flash-lite). Prende la grezza dallo stadio
    di trascrizione."""
    nome = nome_pulito(job.nome)

    def stop_se_annullato():
        if reporter.interrotto():
            raise Interrotto()

    # ---- Lingua parlata ----
    lingua_sorgente = textproc.rileva_lingua(client, raw, reporter.interrotto)
    reporter.log(f"Lingua rilevata: {languages.nome_italiano(lingua_sorgente)}")

    # ---- Materia della lezione (per affilare pulizia/traduzione) ----
    # Se l'utente non ha indicato un corso, la deduciamo dal testo con una
    # chiamata leggera (~5s). Finisce nello slot 'dominio' del prompt al posto
    # del campo corso. La salviamo su file: alla ripresa non la richiediamo.
    dominio = job.corso
    if not dominio:
        materia_file = work_dir / "materia.txt"
        if materia_file.exists() and not rifai:
            dominio = materia_file.read_text(encoding="utf-8").strip()
        else:
            dominio = textproc.deduci_materia(client, raw, reporter.interrotto)
            if dominio:
                util.scrivi_testo(materia_file, dominio)
    if dominio:
        reporter.log(f"Materia rilevata: {dominio}")
    stop_se_annullato()

    # ---- FASE 2: pulizia nella lingua sorgente ----
    pulito_file = work_dir / f"pulito_{lingua_sorgente}.txt"
    pulizia_da_api = not _fase_valida(pulito_file, rifai)   # True = la pulizia chiamera' l'API (ha speso TPM)
    reporter.fase(2, "attiva")
    if _fase_valida(pulito_file, rifai):
        reporter.log("Pulizia gia fatta, la riuso")
        pulito = pulito_file.read_text(encoding="utf-8")
        err_pulizia = 0                 # da cache = senza marcatori (lo garantisce _fase_valida)
    else:
        pulito, err_pulizia = textproc.pulisci(
            client, raw, lingua_sorgente, dominio, reporter,
            avanzamento=lambda fr: reporter.avanzamento(_pct(2, fr)),
        )
        util.scrivi_testo(pulito_file, pulito)
    reporter.fase(2, "fatta"); reporter.avanzamento(_pct(2))
    stop_se_annullato()

    # ---- FASE 3: un testo per ogni lingua richiesta ----
    reporter.fase(3, "attiva")
    testi: dict[str, str] = {}
    falliti = err_pulizia               # i blocchi falliti in pulizia contano nel totale
    # La lingua sorgente, se richiesta, usa direttamente il testo pulito (niente traduzione).
    if lingua_sorgente in job.lingue_output:
        testi[lingua_sorgente] = pulito
    # Le altre lingue richieste vanno tradotte.
    da_tradurre = [l for l in job.lingue_output if l != lingua_sorgente]
    # Pacing proattivo: pulizia e traduzione usano lo STESSO modello (TEXT_MODEL);
    # la pulizia satura il TPM del modello, quindi aspetto una finestra PRIMA di
    # tradurre per non prendere 429/503 a raffica. Solo se la pulizia ha DAVVERO
    # chiamato l'API e c'e' almeno una traduzione non in cache (in ripresa da
    # cache non ho speso TPM, inutile aspettare).
    traduzioni_da_api = [l for l in da_tradurre
                         if not _fase_valida(work_dir / f"testo_{l}.txt", rifai)]
    if pulizia_da_api and traduzioni_da_api and config.PAUSA_TESTO_S > 0:
        reporter.log(f"⏳ Pausa {config.PAUSA_TESTO_S}s prima di tradurre "
                     "(stesso modello della pulizia: evito di saturare il TPM)")
        _attendi_annullabile(config.PAUSA_TESTO_S, reporter.interrotto)
    for j, lang in enumerate(da_tradurre):
        stop_se_annullato()
        testo_file = work_dir / f"testo_{lang}.txt"
        if _fase_valida(testo_file, rifai):
            reporter.log(f"Traduzione {languages.nome_italiano(lang)} gia fatta, la riuso")
            testi[lang] = testo_file.read_text(encoding="utf-8")
        else:
            reporter.log(f"Traduco in {languages.nome_italiano(lang)}")
            tradotto, err = textproc.traduci(
                client, pulito, lingua_sorgente, lang, dominio, reporter,
                avanzamento=lambda fr, j=j: reporter.avanzamento(
                    _pct(3, (j + fr) / max(1, len(da_tradurre)))),
            )
            util.scrivi_testo(testo_file, tradotto)
            testi[lang] = tradotto
            falliti += err
    reporter.fase(3, "fatta"); reporter.avanzamento(_pct(3))
    stop_se_annullato()

    # ---- FASE 4: documenti Word ----
    reporter.fase(4, "attiva")
    fonte = "trascrizione fornita" if job.testo else config.ASR_MODEL
    nota = f"Trascrizione: {fonte} | Pulizia e traduzione: Gemini ({config.TEXT_MODEL})"
    if job.corso:
        nota = f"Corso: {job.corso} | " + nota
    documenti: list[Path] = []
    for k, lang in enumerate(job.lingue_output):
        nome_lingua = languages.nome_italiano(lang)
        titolo = f"Lezione — {job.nome} ({nome_lingua})"
        path = work_dir / f"{nome}_{lang.upper()}.docx"
        documents.genera_docx(testi.get(lang, ""), path, titolo, nota)
        reporter.log(f"💾 {path.name}")
        documenti.append(path)
        reporter.avanzamento(_pct(4, (k + 1) / max(1, len(job.lingue_output))))
    reporter.fase(4, "fatta"); reporter.avanzamento(100.0)

    # Completo = nessun blocco fallito (pulizia + traduzione). Usiamo il CONTEGGIO
    # (`falliti`) invece di cercare il marcatore nel testo: ora un blocco di pulizia
    # fallito contiene la trascrizione grezza (col marcatore come nota), e in traduzione
    # il marcatore verrebbe tradotto e non piu' riconosciuto -> il conteggio e' affidabile.
    completo = (falliti == 0)
    return Risultato(
        nome=job.nome, work_dir=work_dir, lingua_sorgente=lingua_sorgente,
        testi=testi, documenti=documenti, blocchi_falliti=falliti, completo=completo,
    )


def esegui(job: Job, chiave: str, reporter: Reporter, work_base: Path, rifai: bool = False) -> Risultato:
    """Esegue l'intera pipeline per un Job e ritorna il Risultato.

    Concatena i due stadi (trascrizione poi testo) in sequenza: e' il percorso
    usato dalla CLI e da ogni singola lezione. La coda parallela (coda.py) invece
    chiama i due stadi su worker separati per sovrapporli tra lezioni.
    Solleva: ChiaveMancante, FfmpegMancante, Interrotto, o altri errori Gemini.
    """
    client = crea_client(chiave, config.TIMEOUT_TRASCRIZIONE_S)
    work_dir = cartella_lavoro(work_base, job.nome, identita_job(job))
    work_dir.mkdir(parents=True, exist_ok=True)
    raw = fase_trascrizione(job, client, reporter, work_dir, rifai)
    return fase_testo(job, client, reporter, work_dir, raw, rifai)
