"""Parallelizzazione della coda — PASSO 1: prefetch dello Stadio 0.

Mentre il processo principale elabora una lezione (trascrizione + pulizia +
traduzione, tutte legate alle API, una lezione alla volta = collo di bottiglia),
un thread a parte prepara in ANTICIPO lo Stadio 0 (download del link + estrazione
e segmentazione dell'audio, nessuna API) delle lezioni SUCCESSIVE in coda.

Cosi, quando il principale passa alla prossima lezione, i blocchi audio sono gia'
in cache: `transcribe.prepara_audio` li trova e salta direttamente alla
trascrizione, senza far aspettare il download/estrazione.

Il prefetch resta al massimo `buffer` lezioni avanti (semaforo): durante una
trascrizione lunga si porta avanti fino a riempire il buffer, poi si ferma da
solo; riparte quando il principale libera uno slot. Oltre il buffer non si
guadagna (la trascrizione e' comunque una alla volta), si occuperebbe solo disco.

Progettato come fondamento per il PASSO 2 (separare lo stadio trascrizione dallo
stadio testo cosi si sovrappongono anche loro).
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config, pipeline, transcribe
from .errors import Interrotto, LimiteGiornaliero
from .gemini import crea_client
from .pipeline import cartella_lavoro, identita_job
from .progress import Reporter


class _ReporterSilente(Reporter):
    """Reporter muto per il prefetch (niente log/avanzamento sulle card), ma che
    onora l'annullo: se `ferma()` torna True, `prepara_audio` si interrompe."""

    def __init__(self, ferma):
        self._ferma = ferma

    def interrotto(self) -> bool:
        return bool(self._ferma())


class Prefetcher:
    """Prepara in anticipo lo Stadio 0 delle lezioni in coda, al massimo `buffer`
    avanti rispetto a quelle gia' consumate dal processo principale.

    Uso:
        pf = Prefetcher(jobs, work_base, ferma=lambda: annullato).start()
        for k, job in enumerate(jobs):
            pf.attendi_pronta(k)      # blocca finche' lo Stadio 0 di k e' pronto
            ... elabora la lezione k ...
            pf.completata(k)          # libera uno slot: il prefetch va 1 avanti
        pf.stop()                     # a fine/annullo: chiude il thread
    """

    def __init__(self, jobs, work_base, ferma=lambda: False,
                 buffer: int = config.PREFETCH_LEZIONI, prepara=None, rifai: bool = False):
        self._jobs = list(jobs)
        self._work_base = Path(work_base)
        self._ferma_ext = ferma
        self._rifai = rifai
        self._buffer = max(1, int(buffer))
        self._sem = threading.Semaphore(self._buffer)
        self._pronte = [threading.Event() for _ in self._jobs]
        self._prepara = prepara or self._prepara_default
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- interno ------------------------------------------------------------
    def _ferma(self) -> bool:
        return self._stop.is_set() or bool(self._ferma_ext())

    def _prepara_default(self, job) -> None:
        """Stadio 0 reale: scarica (se link) + estrai + segmenta in cache."""
        wd = cartella_lavoro(self._work_base, job.nome, identita_job(job))
        # Se la lezione e' GIA' trascritta (grezza valida in cache), lo Stadio 1
        # la riusera' senza audio: inutile ri-scaricare/ri-estrarre (importante
        # per i link Webex, che altrimenti si ri-scaricherebbero per intero).
        grezza = wd / "grezza.txt"
        if not self._rifai and grezza.exists():
            try:
                if config.MARCATORE_ERRORE not in grezza.read_text(encoding="utf-8"):
                    return
            except Exception:
                pass
        wd.mkdir(parents=True, exist_ok=True)
        transcribe.prepara_audio(
            job.sorgente, wd, job.inizio, job.minuti, _ReporterSilente(self._ferma),
            url=job.url, cookies=job.cookies, password=job.password,
        )

    def _run(self) -> None:
        for j, job in enumerate(self._jobs):
            self._sem.acquire()
            try:
                if self._ferma():
                    continue
                # La PRIMA lezione NON la pre-estraggo: non c'e' nulla dietro cui
                # nascondere la sua FASE 0 (le successive si sovrappongono alla
                # trascrizione della precedente), e farla QUI col reporter muto
                # lascia la scheda ferma e silenziosa per tutta l'estrazione
                # (~decine di secondi). La prepara invece lo Stadio 1 col reporter
                # vero, cosi' la scheda mostra subito "Scarico l'audio" + barra.
                if j == 0:
                    continue
                # una trascrizione gia' fornita (job.testo) non ha Stadio 0 da fare
                if job is not None and getattr(job, "testo", None) is None:
                    try:
                        self._prepara(job)
                    except Exception:
                        # l'errore verra' ri-sollevato quando il principale
                        # elabora la lezione (prepara_audio riprova lì)
                        pass
            finally:
                self._pronte[j].set()

    # -- API pubblica -------------------------------------------------------
    def start(self) -> "Prefetcher":
        self._thread = threading.Thread(target=self._run, name="prefetch", daemon=True)
        self._thread.start()
        return self

    def attendi_pronta(self, k: int) -> None:
        """Blocca finche' lo Stadio 0 della lezione k e' pronto (o si annulla)."""
        if k < 0 or k >= len(self._pronte):
            return
        while not self._pronte[k].wait(timeout=0.3):
            if self._ferma():
                return

    def completata(self, k: int) -> None:
        """Il principale ha finito la lezione k: libera uno slot del buffer."""
        self._sem.release()

    def stop(self) -> None:
        """Ferma il thread di prefetch (a fine batch o su annullo)."""
        self._stop.set()
        # sblocca un eventuale acquire in attesa
        for _ in range(len(self._jobs) + self._buffer):
            self._sem.release()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# =====================================================================
# PASSO 2 — pipeline LINEARE: una lezione alla volta (niente sovrapposizione API)
# =====================================================================

def esegui_coda(jobs, keys, chiave, reporter_per_lezione, work_base,
                rifai: bool = False, prefetch_buffer: int = config.PREFETCH_LEZIONI,
                ferma=lambda: False, annullata=lambda key: False, al_inizio=lambda key: None,
                al_termine=lambda key, ris, err: None, al_annullata=lambda key: None) -> bool:
    """Elabora una coda di lezioni UNA ALLA VOLTA (pipeline lineare per lezione).

    Il parallelismo resta DENTRO la singola lezione (i blocchi audio insieme, in
    transcribe.trascrivi_chunks). Tra lezioni NON c'e' piu' sovrapposizione delle
    fasi API: sovrapporre trascrizione (ASR_MODEL) e testo (TEXT_MODEL) di lezioni
    diverse contendeva i limiti del progetto e scatenava i 429, senza guadagno
    reale quando si e' TPM-bound. Resta solo lo Stadio 0 (Prefetcher, SENZA API)
    che scarica/estrae in ANTICIPO l'audio delle lezioni successive, in background
    e muto, cosi' quando tocca a loro i blocchi sono gia' pronti (la PRIMA lezione
    non si prefetcha: la prepara qui col reporter vero, vedi Prefetcher._run).

    `jobs`/`keys` sono liste parallele (solo lezioni VALIDE; gli errori di
    costruzione del Job li gestisce il chiamante prima). `reporter_per_lezione(key)`
    da' il Reporter della scheda; `al_termine(key, risultato|None, errore|None)`
    viene chiamato a lezione finita o fallita, in ORDINE. `ferma()` True = annullo
    GLOBALE. Non solleva: gli errori arrivano via `al_termine`.
    """
    pf = Prefetcher(jobs, work_base, ferma=ferma, buffer=prefetch_buffer, rifai=rifai).start()
    try:
        client1 = crea_client(chiave, config.TIMEOUT_TRASCRIZIONE_S)
    except Exception as e:                          # chiave mancante/non valida
        for k in range(len(jobs)):                  # fallisce ogni lezione, con grazia
            al_termine(keys[k], None, e)
        pf.stop()
        return False
    try:
        client2 = crea_client(chiave, config.TIMEOUT_TESTO_S)
    except Exception:
        client2 = None

    interrotto = False
    for k, job in enumerate(jobs):
        if ferma():
            interrotto = True
            break
        if annullata(keys[k]):          # annullata MIRATO prima di partire: salto
            al_annullata(keys[k]); pf.completata(k); continue
        rep = reporter_per_lezione(keys[k])
        pf.attendi_pronta(k)            # aspetta che lo Stadio 0 (audio) sia pronto
        if ferma():
            interrotto = True
            break
        if annullata(keys[k]):          # annullata mentre aspettava il prefetch
            al_annullata(keys[k]); pf.completata(k); continue
        al_inizio(keys[k])              # la scheda passa in "in corso"
        wd = cartella_lavoro(work_base, job.nome, identita_job(job))
        wd.mkdir(parents=True, exist_ok=True)
        try:
            # Le due fasi, in sequenza sulla STESSA lezione (nessuna pausa tra
            # pulizia e traduzione: gli errori 429/503 li gestisce con_retry).
            raw = pipeline.fase_trascrizione(job, client1, rep, wd, rifai)
            ris = pipeline.fase_testo(job, client2, rep, wd, raw, rifai)
            al_termine(keys[k], ris, None)
        except LimiteGiornaliero as e:
            al_termine(keys[k], None, e)
            break                       # tetto giornaliero: inutile proseguire
        except Interrotto:
            if ferma():
                interrotto = True
                break                   # annullo GLOBALE: fermo tutto
            al_annullata(keys[k])       # annullo di QUESTA: le altre proseguono
        except Exception as e:
            al_termine(keys[k], None, e)
        finally:
            pf.completata(k)            # libera uno slot: il prefetch va avanti

    pf.stop()
    return interrotto
