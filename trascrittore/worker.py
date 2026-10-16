"""Esecuzione della coda in un PROCESSO SEPARATO (per l'Annulla immediato).

Un thread non si puo' uccidere in Python: se la trascrizione gira nel processo
dell'app, l'Annulla puo' solo CHIEDERE di fermarsi ai checkpoint e deve
aspettare che finisca la chiamata di rete in volo (fino a parecchi secondi).

Facendola girare in un processo figlio, l'app puo' chiamare `process.terminate()`
e ucciderla ALL'ISTANTE, qualunque cosa sia in volo. La cache rende il kill
sicuro (i blocchi gia' fatti restano su disco, con scrittura ATOMICA: vedi
util.scrivi_testo), quindi riaggiungendo la lezione si riprende da dove era.

Questo modulo e' il codice che gira NEL FIGLIO: esegue `coda.esegui_coda` e
manda ogni evento (fase, barra, log, inizio, fine, quota, errore) su una
`multiprocessing.Queue`. Nel figlio non c'e' annullo cooperativo: si muore via
terminate(), quindi i Reporter qui riportano `interrotto() == False`.

L'app (processo padre) svuota la coda e richiama le solite funzioni JS/callback.
"""
from __future__ import annotations

from pathlib import Path

from . import coda
from .progress import Reporter


class _ReporterCoda(Reporter):
    """Reporter del figlio: invece di toccare la finestra (che non puo'
    raggiungere), mette gli eventi sulla coda verso il processo padre."""

    def __init__(self, q, key, ev=None):
        self._q = q
        self._key = key
        self._ev = ev     # Event di questa lezione (annullo MIRATO); None = nessun annullo cooperativo

    def fase(self, indice, stato):
        self._q.put(("fase", self._key, indice, stato))

    def avanzamento(self, percent):
        self._q.put(("avanz", self._key, round(float(percent), 1)))

    def log(self, messaggio):
        self._q.put(("log", self._key, messaggio))

    def interrotto(self):
        # L'annullo MIRATO (cooperativo) di QUESTA lezione: il padre fa .set()
        # dell'Event. ("Annulla tutto" resta il terminate() del processo.)
        return bool(self._ev is not None and self._ev.is_set())

    def richiesta_trascrizione(self):
        self._q.put(("quota",))


def esegui_in_processo(q, jobs, keys, chiave, work_base, rifai=False, cancel_events=None):
    """Entrypoint del processo figlio: esegue la coda e riporta tutto su `q`.

    Gli oggetti arrivano gia' pronti e picklabili dal padre (Job con percorsi,
    chiavi, lingue). `cancel_events` = dict key→Event condiviso col padre per
    l'annullo MIRATO di singole lezioni. Alla fine mette ('__fine__', interrotto)."""
    cancel_events = cancel_events or {}

    def reporter_per_lezione(key):
        return _ReporterCoda(q, key, cancel_events.get(key))

    def annullata(key):
        ev = cancel_events.get(key)
        return bool(ev is not None and ev.is_set())

    def al_inizio(key):
        q.put(("inizio", key))

    def al_annullata(key):
        q.put(("annullata", key))

    def al_termine(key, ris, err):
        if err is None and ris is not None:
            q.put(("fatta", key, {
                "nome": ris.nome,
                "work_dir": str(ris.work_dir),
                "documenti": [str(d) for d in ris.documenti],
                "lingua_sorgente": ris.lingua_sorgente,
                "completo": bool(ris.completo),
                "blocchi_falliti": int(ris.blocchi_falliti),
            }))
        else:
            # Mando il TIPO dell'errore (nome classe) cosi il padre sceglie il
            # messaggio giusto senza dover spedire l'oggetto eccezione.
            q.put(("errore", key, type(err).__name__ if err else "Exception", str(err)[:200]))

    interrotto = False
    try:
        interrotto = coda.esegui_coda(
            jobs, keys, chiave, reporter_per_lezione, Path(work_base),
            rifai=rifai, ferma=lambda: False, annullata=annullata,
            al_inizio=al_inizio, al_termine=al_termine, al_annullata=al_annullata,
        )
    except Exception as e:                     # imprevisto catastrofico nel figlio
        q.put(("fatale", str(e)[:200]))
    finally:
        q.put(("__fine__", bool(interrotto)))
