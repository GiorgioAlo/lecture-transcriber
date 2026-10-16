"""
Trascrivi Lezioni — app desktop (finestra pywebview + pipeline reale).

Questo file e il "guscio": apre la finestra con la UI (ui/index.html) e fa da
ponte tra i click nella pagina e la pipeline vera (package `trascrittore`).

- La UI chiama i metodi di `Api` (es. pywebview.api.avvia(...), scegli_file()...).
- La pipeline, mentre lavora in un thread, aggiorna la finestra tramite
  `ReporterWeb`, che esegue piccole funzioni JavaScript nella pagina.

Per ora la chiave API si legge da GOOGLE_API_KEY (ambiente). La gestione della
chiave con keyring + primo avvio arriva al passo successivo.
"""

import json
import multiprocessing
import os
import queue
import shutil
import sys
import threading
import traceback
import webbrowser
from datetime import date, datetime
from pathlib import Path

import webview

from trascrittore import Job, aggiornamenti, config, percorsi, worker
from trascrittore import chiave as apikey
from trascrittore import download as dl
from trascrittore.audio import durata
from trascrittore.errors import DownloadFallito
from trascrittore.pipeline import Risultato
from trascrittore.progress import Reporter

BASE_DIR = Path(__file__).resolve().parent
UI_FILE = percorsi.risorsa("ui/index.html")   # da .exe: dentro il bundle (_MEIPASS); da sorgente: ui/ del repo
OUT_BASE = percorsi.dir_cache()               # cache interna (intermedi, chunk, docx di lavoro); i doc "veri" li salva l'utente.
                                              # Da .exe va in %LOCALAPPDATA%\Trascrittore (vedi percorsi.py), non accanto al programma.
QUOTA_FILE = OUT_BASE / ".quota.json"         # conteggio richieste di trascrizione fatte OGGI (stima quota giornaliera)
DEBUG_LOG = percorsi.file_log_debug()         # log di debug della coda: scritto SOLO se percorsi.DEBUG e' attivo (TRASCRITTORE_DEBUG=1)

ESTENSIONI_OK = (".mp4", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".mkv", ".mov", ".webm")

# Tipi di finestra file: nomi nuovi (pywebview 5+) con ripiego sui vecchi.
try:
    _DIALOG_OPEN = webview.FileDialog.OPEN       # type: ignore[attr-defined]
    _DIALOG_SAVE = webview.FileDialog.SAVE       # type: ignore[attr-defined]
    _DIALOG_FOLDER = webview.FileDialog.FOLDER   # type: ignore[attr-defined]
except AttributeError:
    _DIALOG_OPEN = webview.OPEN_DIALOG
    _DIALOG_SAVE = webview.SAVE_DIALOG
    _DIALOG_FOLDER = webview.FOLDER_DIALOG


class ReporterWeb(Reporter):
    """Reporter che riporta l'avanzamento nella finestra (via JavaScript)."""

    def __init__(self, esegui_js, è_annullato, su_richiesta=None, key=""):
        self._js = esegui_js
        self._annullato = è_annullato
        self._su_richiesta = su_richiesta
        self._key = key          # scheda a cui instradare (più lezioni attive insieme)

    def fase(self, indice, stato):
        self._js(f"appFase({json.dumps(self._key)}, {indice}, {json.dumps(stato)})")

    def avanzamento(self, percent):
        self._js(f"appAvanzamento({json.dumps(self._key)}, {percent:.1f})")

    def log(self, messaggio):
        self._js(f"appLog({json.dumps(self._key)}, {json.dumps(messaggio)})")

    def interrotto(self):
        return self._annullato()

    def richiesta_trascrizione(self):
        if self._su_richiesta is not None:
            self._su_richiesta()


class Api:
    """Tutto cio che la UI puo chiedere a Python."""

    def __init__(self):
        self._window = None
        self._annulla = False
        self._dialogo_in_corso = False
        self._dlg_lock = threading.Lock()   # rende atomico il "controlla e prenota" dei dialoghi
        self._fatte = {}              # path sorgente (str) -> Risultato dell'ultima trascrizione
        self._cartella_salvata = {}   # path sorgente (str) -> cartella scelta dall'utente al salvataggio
        self._lock = threading.Lock() # protegge l'avvio di un batch (anti-concorrenza)
        self._in_corso = False        # True mentre un batch e in esecuzione
        self._worker = None           # il thread che sta lavorando
        self._cartella_batch = None   # cartella scelta a inizio batch: ci salvo da solo le lezioni finite
        self._cookies_webex = None    # file cookies.txt per Webex, tenuto SOLO in RAM (sessione sensibile)
        self._proc = None             # processo figlio che trascrive (lo si puo' uccidere per annullare)
        self._cancel_events = {}      # key lezione -> Event condiviso col figlio (annullo MIRATO cooperativo)

    def _collega_finestra(self, window):
        self._window = window

    def _prendi_dialogo(self) -> bool:
        """Prenota l'apertura di UN dialogo file. Ritorna False se ce n'e' gia
        uno aperto (cosi due clic rapidi non aprono due finestre). Il thread che
        prenota deve rimettere `_dialogo_in_corso = False` nel suo finally."""
        with self._dlg_lock:
            if self._dialogo_in_corso:
                return False
            self._dialogo_in_corso = True
            return True

    def _js(self, codice):
        if self._window is not None:
            try:
                self._window.evaluate_js(codice)
            except Exception:
                pass

    # --- chiamate dalla UI -------------------------------------------------
    def ping(self):
        return "pong"

    def scegli_file(self):
        """Apre la finestra nativa per scegliere file audio/video.

        IMPORTANTE: il dialogo viene aperto in un THREAD separato e questa
        chiamata ritorna subito. Aprirlo dentro la chiamata JS→Python bloccava
        il thread grafico (il dialogo non si chiudeva). I file scelti vengono
        rimandati alla pagina con la funzione JS `appFileScelti`.
        """
        if not self._prendi_dialogo():      # evita aperture doppie
            return {"ok": True}
        threading.Thread(target=self._apri_dialogo_file, daemon=True).start()
        return {"ok": True}

    def _apri_dialogo_file(self):
        try:
            if self._window is None:
                return
            tipi = (
                "Audio e video (*.mp4;*.m4a;*.mp3;*.wav;*.aac;*.ogg;*.flac;*.mkv;*.mov;*.webm)",
                "Tutti i file (*.*)",
            )
            try:
                scelti = self._su_thread_gui(lambda: self._window.create_file_dialog(
                    _DIALOG_OPEN, allow_multiple=True, file_types=tipi))
            except Exception:
                traceback.print_exc()
                scelti = None
            risultato, scartati = self._descrivi_file(scelti or [])
            self._js("appFileScelti(" + json.dumps(risultato, ensure_ascii=False) + ")")
            if scartati:
                nomi = ", ".join(scartati)
                titolo = "File non valido" if len(scartati) == 1 else "File non validi"
                msg = f"Questo non è un file audio o video, l'ho saltato: {nomi}" if len(scartati) == 1 \
                    else f"Questi non sono file audio o video, li ho saltati: {nomi}"
                self._js("toast('warn', " + json.dumps(titolo, ensure_ascii=False)
                         + ", " + json.dumps(msg, ensure_ascii=False) + ")")
        finally:
            self._dialogo_in_corso = False

    def _descrivi_file(self, percorsi):
        """Da una lista di percorsi a (voci_valide, nomi_scartati).

        Scarta chi non ha un'estensione audio/video riconosciuta e ne tiene i
        nomi per avvisare l'utente (messaggio gentile, non silenzio).
        """
        risultato = []
        scartati = []
        for p in percorsi:
            if not p:
                continue
            path = Path(p)
            if path.suffix.lower() not in ESTENSIONI_OK:
                scartati.append(path.name)
                continue
            try:
                minuti = durata(path) / 60
                sub = f"File · {minuti:.0f} min" if minuti >= 1 else "File"
            except Exception:
                sub = "File"
            risultato.append({"nome": path.name, "path": str(path), "sub": sub})
        return risultato, scartati

    def scegli_cartella(self):
        """Apre il selettore CARTELLA nativo (su richiesta della nostra finestra
        di dialogo). Ritorna subito; la cartella torna via JS `appCartellaScelta`."""
        if not self._prendi_dialogo():
            return {"ok": True}
        threading.Thread(target=self._apri_dialogo_cartella, daemon=True).start()
        return {"ok": True}

    def _apri_dialogo_cartella(self):
        try:
            if self._window is None:
                return
            try:
                scelto = self._su_thread_gui(
                    lambda: self._window.create_file_dialog(_DIALOG_FOLDER))
            except Exception:
                traceback.print_exc()
                scelto = None
            cartella = scelto[0] if isinstance(scelto, (list, tuple)) else scelto
            self._js("appCartellaScelta(" + json.dumps(str(cartella) if cartella else "") + ")")
        finally:
            self._dialogo_in_corso = False

    def carica_cookies(self):
        """Apre il selettore per il file cookies.txt di Webex (lo tiene in RAM)."""
        if not self._prendi_dialogo():
            return {"ok": True}
        threading.Thread(target=self._apri_dialogo_cookies, daemon=True).start()
        return {"ok": True}

    def _apri_dialogo_cookies(self):
        try:
            if self._window is None:
                return
            tipi = ("File di cookie (*.txt)", "Tutti i file (*.*)")
            try:
                scelti = self._su_thread_gui(lambda: self._window.create_file_dialog(
                    _DIALOG_OPEN, allow_multiple=False, file_types=tipi))
            except Exception:
                traceback.print_exc()
                scelti = None
            path = (scelti[0] if isinstance(scelti, (list, tuple)) else scelti) if scelti else None
            if not path:
                return  # annullato
            ok, errore = dl.valida_cookies(str(path))
            if ok:
                self._cookies_webex = str(path)   # solo in RAM, non lo copiamo/salviamo
                self._js("appCookies(" + json.dumps({"ok": True, "nome": Path(path).name}) + ")")
            else:
                self._js("appCookies(" + json.dumps({"ok": False, "errore": errore}) + ")")
        finally:
            self._dialogo_in_corso = False

    def info_link(self, url):
        """Titolo + durata (min) di un link, per dare un nome bello alla scheda.

        Per Webex serve prima il file cookie: senza, torna solo {webex:true}."""
        url = (url or "").strip()
        webex = dl.e_webex(url)
        cookies = self._cookies_webex if webex else None
        if webex and not cookies:
            return {"webex": True, "titolo": "", "durata_min": None}
        try:
            info = dl.info(url, cookies)
        except Exception:
            info = {"titolo": "", "durata": None}
        dmin = round(info["durata"] / 60) if info.get("durata") else None
        return {"webex": webex, "titolo": info.get("titolo", ""), "durata_min": dmin}

    def _su_thread_gui(self, chiama):
        """Esegue `chiama()` sul thread della finestra (STA) e ne ritorna il valore.

        Su WinForms i dialoghi fanno ShowDialog sul thread chiamante e pretendono
        un thread STA che possieda la finestra: l'unico e il thread grafico. Qui
        usiamo form.Invoke per farlo girare la. Se qualcosa non torna (altro
        backend), ripieghiamo sulla chiamata diretta.
        """
        try:
            form = self._window.gui.BrowserView.instances[self._window.uid]
            from System import Action  # delegato .NET (disponibile col backend WinForms)
            box = {}

            def run():
                box["r"] = chiama()

            form.Invoke(Action(run))
            return box.get("r")
        except Exception:
            # backend diverso o internals cambiati: tentiamo diretto
            return chiama()

    def apri_cartella(self, path):
        """Apre in Esplora File la cartella dei documenti di QUELLA lezione.

        Apre la cartella dove l'utente ha salvato; ma se quella cartella non
        esiste piu' o NON contiene piu' i documenti (li ha cancellati/spostati),
        ripiega sulla copia interna nella cache (che tiene comunque i .docx).
        """
        key = str(path)
        ris = self._fatte.get(key)
        salvata = self._cartella_salvata.get(key)

        dove = None
        if salvata and Path(salvata).exists():
            if ris and ris.documenti:
                presenti = any((Path(salvata) / Path(d).name).exists() for d in ris.documenti)
            else:
                presenti = True  # non conosco i nomi: mi fido della cartella
            if presenti:
                dove = salvata
        ripiego = dove is None and salvata is not None  # volevo la cartella utente, non c'e' piu'

        if dove is None and ris is not None and Path(ris.work_dir).exists():
            dove = str(ris.work_dir)

        if dove:
            if ripiego:
                self._js("toast('warn'," + json.dumps("Documenti spostati o cancellati") + "," +
                         json.dumps("Nella cartella salvata non ci sono più: apro la copia interna dell'app.") + ")")
            try:
                percorsi.apri_cartella(dove)   # Esplora / Finder / file manager Linux
            except Exception:
                traceback.print_exc()
        else:
            self._js("toast('err'," + json.dumps("Non trovo i documenti") + "," +
                     json.dumps("I documenti di questa lezione non ci sono più nemmeno nella cache. Rifai la trascrizione.") + ")")
        return {"ok": True}

    def salva(self, path):
        """Salva i .docx di QUELLA lezione dove sceglie l'utente (ibrido).

        1 documento  -> finestra "Salva con nome" (col nome gia proposto).
        2+ documenti -> finestra "Scegli cartella", poi li copio tutti dentro.
        Ritorna subito; il dialogo gira in un thread e l'esito torna via JS.
        """
        ris = self._fatte.get(str(path))
        if not ris or not ris.documenti:
            return {"ok": False}
        if not self._prendi_dialogo():
            return {"ok": True}
        threading.Thread(target=self._salva_dialogo, args=(str(path), list(ris.documenti)), daemon=True).start()
        return {"ok": True}

    def _salva_dialogo(self, path, documenti):
        try:
            docs = [Path(d) for d in documenti if Path(d).exists()]
            if not docs:
                return
            if len(docs) == 1:
                scelto = self._su_thread_gui(lambda: self._window.create_file_dialog(
                    _DIALOG_SAVE, save_filename=docs[0].name,
                    file_types=("Documento Word (*.docx)", "Tutti i file (*.*)")))
                destino = scelto[0] if isinstance(scelto, (list, tuple)) else scelto
                if not destino:
                    return
                shutil.copyfile(docs[0], destino)
                salvati = [Path(destino)]
            else:
                # Il selettore cartella di Windows non ha un messaggio proprio:
                # lo spieghiamo con un avviso PRIMA di aprirlo.
                nomi = ", ".join(d.name for d in docs)
                self._js("toast('info'," + json.dumps("Scegli la cartella") + "," +
                         json.dumps(f"Ci salvo i {len(docs)} documenti: {nomi}") + ")")
                scelto = self._su_thread_gui(
                    lambda: self._window.create_file_dialog(_DIALOG_FOLDER))
                cartella = scelto[0] if isinstance(scelto, (list, tuple)) else scelto
                if not cartella:
                    return
                salvati = []
                for d in docs:
                    out = Path(cartella) / d.name
                    shutil.copyfile(d, out)
                    salvati.append(out)
            dove = str(salvati[0].parent)
            self._ricorda_cartella_salvata(path, dove)
            self._js("appSalvato(" + json.dumps(path) + "," +
                     json.dumps({"n": len(salvati), "cartella": dove}) + ")")
        except Exception:
            traceback.print_exc()
            # il salvataggio e fallito ma la lezione resta "fatta": solo un avviso
            self._js("toast('err'," + json.dumps("Salvataggio non riuscito") + "," +
                     json.dumps("Non sono riuscito a copiare i documenti nella posizione scelta.") + ")")
        finally:
            self._dialogo_in_corso = False

    def elimina(self, path):
        """Cestino per-lezione: svuota la cache di QUELLA lezione.

        La scheda viene tolta dalla vista lato UI; qui cancelliamo i dati su
        disco (chunk, intermedi, docx di lavoro) e dimentichiamo il risultato.
        Per rifare la lezione basta ri-trascinare il file: ripartira' pulita.
        """
        # Uso la cartella di lavoro VERA registrata nel Risultato: funziona sia
        # per i file sia per i link (prima ricostruivo il nome dal path e sui
        # link cancellavo la cartella sbagliata, lasciando la cache orfana).
        key = str(path)
        ris = self._fatte.get(key)
        try:
            if ris is not None and Path(ris.work_dir).exists():
                shutil.rmtree(Path(ris.work_dir), ignore_errors=True)
        except Exception:
            traceback.print_exc()
        self._fatte.pop(key, None)
        self._cartella_salvata.pop(key, None)
        return {"ok": True}

    # --- quota giornaliera (stima "lezioni rimaste oggi") -------------------
    def _leggi_quota(self):
        """Ritorna (oggi_iso, richieste_fatte_oggi). Azzera se e' un nuovo giorno."""
        oggi = date.today().isoformat()
        usate = 0
        try:
            if QUOTA_FILE.exists():
                d = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
                if d.get("data") == oggi:
                    usate = int(d.get("richieste", 0))
        except Exception:
            pass
        return oggi, usate

    def _scrivi_quota(self, oggi, usate):
        try:
            OUT_BASE.mkdir(parents=True, exist_ok=True)
            QUOTA_FILE.write_text(json.dumps({"data": oggi, "richieste": usate}), encoding="utf-8")
        except Exception:
            traceback.print_exc()

    def _quota_info(self, usate=None):
        if usate is None:
            _, usate = self._leggi_quota()
        cap = config.RPD_TRASCRIZIONE
        rimaste = max(0, cap - usate)
        # Ogni richiesta copre ~MAX_BLOCCO_MIN minuti di audio (un blocco):
        # richieste rimaste x MAX_BLOCCO_MIN = minuti di lezione trascrivibili oggi.
        minuti = rimaste * config.MAX_BLOCCO_MIN
        return {"usate": usate, "cap": cap, "richieste_rimaste": rimaste,
                "minuti": minuti, "min_per_richiesta": config.MAX_BLOCCO_MIN}

    def _conta_richiesta(self):
        """Chiamata dal Reporter a ogni blocco trascritto: +1 e aggiorna il badge."""
        oggi, usate = self._leggi_quota()
        usate += 1
        self._scrivi_quota(oggi, usate)
        self._js("appQuota(" + json.dumps(self._quota_info(usate)) + ")")

    def quota_oggi(self):
        """La UI la chiama all'avvio per mostrare la stima iniziale."""
        return self._quota_info()

    # --- chiave API (keyring + primo avvio) --------------------------------
    def stato_chiave(self):
        """Stato della chiave per decidere se mostrare il primo avvio.

        `presente`: c'e' una chiave salvata. `preview`: versione mascherata (per
        le Impostazioni). `prefill`: se NON c'e' una chiave salvata ma ne esiste
        una in GOOGLE_API_KEY, la passo per precompilare il campo (migrazione)."""
        salvata = apikey.leggi()
        prefill = "" if salvata else os.environ.get("GOOGLE_API_KEY", "").strip()
        return {"presente": bool(salvata), "preview": apikey.anteprima(salvata), "prefill": prefill}

    def salva_chiave(self, valore):
        """Verifica la chiave online e, se valida, la salva nel Gestore
        Credenziali. Ritorna {ok, errore, preview}."""
        valore = (valore or "").strip()
        ok, errore = apikey.valida(valore)
        if not ok:
            return {"ok": False, "errore": errore}
        try:
            apikey.salva(valore)
        except Exception:
            traceback.print_exc()
            return {"ok": False,
                    "errore": "Non riesco a salvare la chiave nel Gestore Credenziali di Windows."}
        return {"ok": True, "preview": apikey.anteprima(valore)}

    def elimina_chiave(self):
        apikey.elimina()
        return {"ok": True}

    def apri_link(self, url):
        """Apre un link nel browser di sistema (non dentro la finestra dell'app)."""
        try:
            if str(url).startswith(("http://", "https://")):
                webbrowser.open(str(url))
        except Exception:
            traceback.print_exc()
        return {"ok": True}

    # --- aggiornamenti / segnalazioni (Step 3) -----------------------------
    def info_app(self):
        """Dati per il pannello Impostazioni: versione e se il form di
        segnalazione e' configurato (per mostrarne o no il pulsante)."""
        return {
            "versione": config.VERSION,
            "segnalazione": bool(aggiornamenti.url_segnalazione()),
        }

    def apri_segnalazione(self):
        """Apre il Google Form 'Segnala un problema' col numero di versione gia'
        pre-compilato. {'ok': False} se il form non e' configurato (la UI allora
        non mostra il pulsante)."""
        url = aggiornamenti.url_segnalazione(config.VERSION)
        if not url:
            return {"ok": False}
        self.apri_link(url)
        return {"ok": True}

    def aggiorna_ytdlp(self):
        """Forza l'aggiornamento di yt-dlp (`-U`) su richiesta dell'utente, in un
        thread (puo' impiegare qualche secondo). L'esito torna via toast in UI.
        {'ok': True} = richiesta avviata (non ancora l'esito)."""
        def _lavora():
            esito = False
            try:
                esito = dl.aggiorna_ytdlp()
            except Exception:
                traceback.print_exc()
            if esito:
                self._js("toast('ok','yt-dlp aggiornato',"
                         "'Il motore di download è alla versione più recente.')")
            else:
                self._js("toast('warn','yt-dlp non aggiornato',"
                         "'Non è stato possibile aggiornare ora. Riprova più tardi.')")
        threading.Thread(target=_lavora, daemon=True).start()
        return {"ok": True}

    def cerca_aggiornamenti(self):
        """Controllo aggiornamenti MANUALE ('Cerca aggiornamenti'): forza il check su
        GitHub (salta il throttle giornaliero), in un thread. Esito via UI:
          nuovo      -> banner appAggiornamento (con 'Scarica')
          aggiornato -> toast 'sei aggiornato'
          errore     -> toast 'controllo non riuscito'.
        {'ok': True} = richiesta avviata. NON auto-installa: apre la pagina di download."""
        def _lavora():
            try:
                r = aggiornamenti.controlla_manuale()
            except Exception:
                traceback.print_exc()
                r = {"stato": "errore"}
            if r.get("stato") == "nuovo":
                self._js(f"appAggiornamento({json.dumps(r['versione'])}, {json.dumps(r['url'])}, true)")
            elif r.get("stato") == "aggiornato":
                self._js("appAggiornato()")
            else:
                self._js("appControlloFallito()")
        threading.Thread(target=_lavora, daemon=True).start()
        return {"ok": True}

    # --- lezioni gia' in cache (ripristino all'avvio) -----------------------
    def lezioni_in_cache(self):
        """Elenca le lezioni gia' completate trovate in cache/ (per ripopolare
        la sezione 'Completate' alla riapertura dell'app). Ricostruisce anche
        un `Risultato` minimo in `self._fatte` cosi Salva/Apri funzionano."""
        voci = []
        if not OUT_BASE.exists():
            return voci
        for d in sorted(OUT_BASE.iterdir()):
            if not d.is_dir():
                continue
            docx = sorted(d.glob("*.docx"))
            if not docx:
                continue
            self._snellisci(d)   # pulizia una-tantum: libera i blocchi audio di run vecchie
            nome = d.name
            lingue = []
            cartella_salvata = ""
            src = ""                      # path/url sorgente originale (per evitare doppioni al re-add)
            meta_f = d / "meta.json"
            if meta_f.exists():
                try:
                    m = json.loads(meta_f.read_text(encoding="utf-8"))
                    nome = m.get("nome", nome)
                    lingue = [str(x).lower() for x in m.get("lingue", [])]
                    cartella_salvata = str(m.get("cartella_salvata", "") or "")
                    src = str(m.get("path", "") or "")
                except Exception:
                    pass
            if not lingue:  # deduci dai nomi file <nome>_<LANG>.docx
                lingue = [p.stem.rsplit("_", 1)[-1].lower() for p in docx]
            chiave = str(d)  # identita' stabile della scheda ripristinata
            self._fatte[chiave] = Risultato(
                nome=nome, work_dir=d, lingua_sorgente="", documenti=list(docx))
            if cartella_salvata:
                self._cartella_salvata[chiave] = cartella_salvata  # 'Apri cartella' -> cartella vera
            n_doc = len(docx)
            voci.append({
                "nome": nome, "path": chiave, "documenti": n_doc,
                "lingue": ", ".join(x.upper() for x in lingue),
                "sub": "Completata · " + (f"{n_doc} documento" if n_doc == 1 else f"{n_doc} documenti"),
                "cartella": cartella_salvata, "src": src,
            })
        return voci

    def _scrivi_meta(self, path, ris, lingue):
        """Salva un meta.json nella cartella di lavoro: serve a ripristinare la
        scheda 'completata' (nome vero + lingue) alla prossima apertura."""
        try:
            meta = {"nome": ris.nome, "path": str(path), "lingue": list(lingue)}
            (ris.work_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception:
            traceback.print_exc()

    def _snellisci(self, work_dir):
        """Variante A: a lezione COMPLETATA cancella i blocchi audio
        (`chunks_audio/`), che sono il ~99% del peso in cache e non servono piu'
        (grezza/pulito/testo restano, quindi ripresa e ri-traduzione funzionano
        senza ri-trascrivere). Ritorna True se ha liberato spazio."""
        try:
            chunk_dir = Path(work_dir) / "chunks_audio"
            if chunk_dir.exists():
                shutil.rmtree(chunk_dir, ignore_errors=True)
                return True
        except Exception:
            traceback.print_exc()
        return False

    def _ricorda_cartella_salvata(self, path, cartella):
        """Memorizza dove l'utente ha salvato i Word di questa lezione, sia in
        RAM sia su `meta.json`, cosi 'Apri cartella' funziona anche dopo aver
        chiuso e riaperto l'app (prima era solo in memoria -> ripiegava sulla cache)."""
        cartella = str(cartella)
        self._cartella_salvata[path] = cartella
        ris = self._fatte.get(path)
        if not ris:
            return
        try:
            meta_f = Path(ris.work_dir) / "meta.json"
            meta = {}
            if meta_f.exists():
                meta = json.loads(meta_f.read_text(encoding="utf-8"))
            meta["cartella_salvata"] = cartella
            meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception:
            traceback.print_exc()

    def _autosave(self, path, ris, cartella):
        """Copia i .docx della lezione nella cartella scelta a inizio batch e
        aggiorna la scheda (come un salvataggio manuale, ma automatico)."""
        try:
            salvati = []
            for d in ris.documenti:
                d = Path(d)
                if not d.exists():
                    continue
                out = Path(cartella) / d.name
                shutil.copyfile(d, out)
                salvati.append(out)
            if salvati:
                self._ricorda_cartella_salvata(path, cartella)
                self._js("appSalvato(" + json.dumps(path) + "," +
                         json.dumps({"n": len(salvati), "cartella": str(cartella)}) + ")")
        except Exception:
            traceback.print_exc()
            self._js("toast('err'," + json.dumps("Salvataggio non riuscito") + "," +
                     json.dumps("Non sono riuscito a copiare i documenti nella cartella scelta; usa Salva...") + ")")

    def svuota_cache(self):
        """Svuota la cache di TUTTE le lezioni (cancella il contenuto di cache/)."""
        # Mai durante un batch: cancellerebbe le cartelle delle lezioni in corso.
        if self._in_corso:
            self._js("toast(" + json.dumps("warn") + "," + json.dumps("Sto lavorando") + "," +
                     json.dumps("Aspetta che finiscano le trascrizioni prima di svuotare la cache.") + ")")
            return {"ok": False, "motivo": "in_corso"}
        try:
            if OUT_BASE.exists():
                for child in OUT_BASE.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
        except Exception:
            traceback.print_exc()
        self._fatte.clear()
        self._cartella_salvata.clear()
        return {"ok": True}

    def avvia(self, lavoro):
        """Avvia la trascrizione reale. Il lavoro vero gira in un thread.

        Lucchetto anti-concorrenza: se un batch e gia in corso, un secondo
        avvio (doppio click, oppure annulla->riavvia troppo veloce) viene
        IGNORATO. Cosi due pipeline non lavorano MAI sulla stessa cache
        contemporaneamente (era la causa sospetta della trascrizione duplicata).
        """
        with self._lock:
            if self._in_corso:
                print("[Python] avvia() ignorato: un batch e gia in corso")
                self._js("appGiaInCorso()")
                return {"ok": False, "motivo": "in_corso"}
            self._in_corso = True
            self._annulla = False
            print("[Python] avvia():", json.dumps(lavoro, ensure_ascii=False)[:300])
            self._worker = threading.Thread(target=self._lavora_protetto, args=(lavoro,), daemon=True)
            self._worker.start()
        return {"ok": True}

    def annulla(self, path=None):
        """Annulla UNA sola lezione (MIRATO, cooperativo): fa .set() dell'Event
        della sua scheda → quella lezione si ferma al prossimo checkpoint (finito
        il blocco audio in corso, ~decine di secondi), le altre proseguono.
        Senza `path` ripiega su annulla_tutto (compatibilita')."""
        if not path:
            return self.annulla_tutto()
        ev = self._cancel_events.get(path)
        if ev is not None:
            # timestamp della RICHIESTA: la differenza con la riga "ANNULLATA" nel
            # log misura la latenza reale dell'annullo mirato (cooperativo).
            self._log_debug(f"RICHIESTA annullo mirato {self._short_key(path)}")
            try:
                ev.set()
            except Exception:
                traceback.print_exc()
        return {"ok": True}

    def annulla_tutto(self):
        """Annulla TUTTO il batch, ALL'ISTANTE: uccide il processo di trascrizione
        (qualunque cosa sia in volo muore subito). La cache con scrittura atomica
        rende il kill sicuro: riaggiungendo una lezione riprende da dove era."""
        self._log_debug("RICHIESTA annulla tutto (terminate)")
        self._annulla = True
        for ev in self._cancel_events.values():
            try:
                ev.set()
            except Exception:
                pass
        proc = self._proc
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                traceback.print_exc()
        return {"ok": True}

    # --- il lavoro vero, in background -------------------------------------
    def _lavora_protetto(self, lavoro):
        """Esegue il batch e rilascia SEMPRE il lucchetto a fine corsa.

        Qualunque cosa succeda dentro `_lavora` (fine normale, annullo, o un
        errore imprevisto), il flag `_in_corso` torna a False e la UI viene
        sbloccata con `appLavoroFinito` una sola volta, da qui.
        """
        try:
            self._lavora(lavoro)
        except Exception:
            traceback.print_exc()
        finally:
            with self._lock:
                self._in_corso = False
                self._worker = None
            # I cookie Webex restano in RAM per tutta la SESSIONE dell'app: cosi'
            # non vanno ricaricati a ogni batch (prima li azzeravo qui). Se sono
            # scaduti, il download fallira' con un errore gentile e si ricaricano
            # solo in quel caso — non ha senso richiederli se funzionano ancora.
            self._js("appLavoroFinito()")

    def _costruisci_job(self, l, lingue, corso):
        """Crea il Job per una voce della coda. Puo' sollevare DownloadFallito
        (link Webex senza cookie): l'errore verra' mostrato sulla sua scheda."""
        key = l["path"]
        tipo = l.get("tipo", "file")
        if tipo == "file":
            return Job(sorgente=Path(key), nome=Path(key).stem, lingue_output=lingue, corso=corso)
        webex = (tipo == "webex") or dl.e_webex(key)
        cookies = self._cookies_webex if webex else None
        if webex and not cookies:
            raise DownloadFallito("Carica prima il file dei cookie di Webex (riga 'Accesso Webex').")
        nome = (l.get("nome") or key).strip()
        # NIENTE chiamate di rete qui: una `dl.info()` sincrona (fino a decine di secondi su
        # un link lento) bloccherebbe l'avvio del batch PRIMA che parta il processo figlio →
        # la UI resta "in corso", la barra sembra ferma e l'annullo non funziona (gli Event e
        # il figlio non esistono ancora). Se il titolo non si e' ancora risolto (nome = URL
        # grezzo) — raro: Avvia premuto prima che `info_link` rispondesse — usiamo un nome di
        # ripiego dall'host; il titolo "bello" di solito e' gia' arrivato async in aggiunta.
        if not nome or "://" in nome or nome.startswith(("http", "www.")):
            host = key.split("://", 1)[-1].split("/", 1)[0].replace("www.", "") or "link"
            nome = f"Lezione ({host})"
        return Job(url=key, nome=nome, lingue_output=lingue,
                   corso=corso, cookies=cookies, password=(l.get("password") or None))

    # --- log di debug della coda -------------------------------------------
    def _log_debug(self, msg):
        """Appende una riga al file di debug (timestamp al ms). SPENTO di default:
        scrive solo se percorsi.DEBUG e' attivo (TRASCRITTORE_DEBUG=1). Non deve
        MAI far cadere il batch: ogni errore di scrittura viene ignorato."""
        if not percorsi.DEBUG:
            return
        try:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    @staticmethod
    def _short_key(key):
        """Nome breve e leggibile di una lezione (basename del path o coda dell'url)."""
        s = str(key)
        base = s.replace("\\", "/").rstrip("/").split("/")[-1]
        return base[:50] if base else s[-50:]

    def _fmt_ev(self, ev):
        """Rende un evento della coda in una riga leggibile per il log."""
        tipo = ev[0]
        if tipo == "fase":
            _, key, i, stato = ev
            nome = config.FASI[i] if 0 <= i < len(config.FASI) else "?"
            return f"fase   {self._short_key(key)}  [{i}:{nome}] -> {stato}"
        if tipo == "avanz":
            _, key, pct = ev
            return f"avanz  {self._short_key(key)}  {pct:.1f}%"
        if tipo == "log":
            _, key, m = ev
            return f"log    {self._short_key(key)}  {m}"
        if tipo == "quota":
            return "quota  +1 richiesta trascrizione"
        if tipo == "inizio":
            return f"INIZIO {self._short_key(ev[1])}"
        if tipo == "annullata":
            return f"ANNULLATA {self._short_key(ev[1])}"
        if tipo == "fatta":
            light = ev[2]
            return (f"FATTA  {self._short_key(ev[1])}  "
                    f"doc={len(light.get('documenti', []))} completo={light.get('completo')}")
        if tipo == "errore":
            return f"ERRORE {self._short_key(ev[1])}  {ev[2]}: {ev[3]}"
        if tipo == "fatale":
            return f"FATALE {ev[1]}"
        return f"? {ev!r}"

    def _lavora(self, lavoro):
        lezioni = [l for l in lavoro.get("lezioni", []) if l.get("path")]
        lingue = lavoro.get("lingue", ["it", "en"])
        corso = lavoro.get("corso", "")

        chiave = apikey.leggi()
        if lezioni and not chiave:
            for l in lezioni:
                self._js("appErrore(" + json.dumps(l["path"]) + "," +
                         json.dumps("Manca la chiave") + "," +
                         json.dumps("Apri le Impostazioni (icona ingranaggio) e inserisci la tua chiave API.") + ")")
            return

        # Cartella di destinazione scelta UNA volta (dalla nostra finestra di
        # dialogo, PRIMA di arrivare qui): ogni lezione finita ci viene salvata
        # in automatico. Vuota = l'utente salvera' a mano con [Salva...].
        self._cartella_batch = (lavoro.get("cartella") or "").strip() or None

        # Costruisco i job; gli errori di costruzione (es. Webex senza cookie)
        # li segnalo subito sulla scheda e NON entrano nella coda parallela.
        keys, jobs = [], []
        for l in lezioni:
            key = l["path"]
            try:
                job = self._costruisci_job(l, lingue, corso)
            except DownloadFallito as e:
                self._js("appLavoroPartito(" + json.dumps(key) + ")")
                self._js("appErrore(" + json.dumps(key) + "," +
                         json.dumps("Download non riuscito") + "," + json.dumps(str(e)) + ")")
                continue
            except Exception as e:
                self._js("appLavoroPartito(" + json.dumps(key) + ")")
                self._js("appErrore(" + json.dumps(key) + "," +
                         json.dumps("Impossibile aggiungere") + "," + json.dumps(str(e)[:200]) + ")")
                continue
            keys.append(key); jobs.append(job)

        if not jobs:     # tutte scartate in costruzione: niente da far girare
            return

        self._log_debug("=" * 60)
        self._log_debug(f"NUOVO BATCH: {len(jobs)} lezioni  lingue={lingue}  "
                        f"cartella={self._cartella_batch!r}  "
                        f"ASR_WORKER={config.ASR_WORKER} PREFETCH={config.PREFETCH_LEZIONI}")
        for n, k in enumerate(keys):
            self._log_debug(f"  [{n}] {self._short_key(k)}")

        # La coda (Stadio 0 prefetch + Stadio 1 transcribe + Stadio 2 testo) gira
        # in un PROCESSO FIGLIO, cosi l'Annulla puo' ucciderlo all'istante
        # (vedi trascrittore/worker.py). Qui facciamo da "centralino": riceviamo
        # i suoi eventi da una coda e chiamiamo le solite funzioni JS/callback.
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        # Un Event per lezione, CONDIVISO col figlio: l'annullo mirato di una
        # scheda fa .set() del suo Event → quella lezione si ferma al prossimo
        # checkpoint, le altre proseguono. ("Annulla tutto" usa invece terminate.)
        self._cancel_events = {k: ctx.Event() for k in keys}
        proc = ctx.Process(target=worker.esegui_in_processo,
                           args=(q, jobs, keys, chiave, str(OUT_BASE), False, self._cancel_events),
                           daemon=True)
        self._proc = proc
        proc.start()
        self._log_debug(f"processo figlio avviato pid={proc.pid}")

        interrotto = False
        try:
            while True:
                try:
                    ev = q.get(timeout=0.3)
                except queue.Empty:
                    if not proc.is_alive():
                        # morto senza sentinella = ucciso dall'Annulla (o crash)
                        self._log_debug(f"FIGLIO MORTO senza __fine__ "
                                        f"(exitcode={proc.exitcode}, annulla={self._annulla})")
                        interrotto = bool(self._annulla)
                        break
                    continue
                if ev[0] == "__fine__":
                    self._log_debug(f"__fine__ interrotto={ev[1]}")
                    interrotto = bool(ev[1])
                    break
                self._log_debug(self._fmt_ev(ev))
                self._dispatch(ev, lingue)
        finally:
            try:
                proc.join(timeout=2)
            except Exception:
                pass
            self._log_debug(f"batch concluso (interrotto={interrotto}); loop centralino chiuso")
            self._proc = None

        if interrotto:   # si e' fermata davvero a meta' (non a batch gia' concluso)
            self._js("appAnnullato()")

    def _dispatch(self, ev, lingue):
        """Esegue nell'app l'evento arrivato dal processo di trascrizione."""
        tipo = ev[0]
        if tipo == "fase":
            _, key, indice, stato = ev
            self._js(f"appFase({json.dumps(key)}, {indice}, {json.dumps(stato)})")
        elif tipo == "avanz":
            _, key, percent = ev
            self._js(f"appAvanzamento({json.dumps(key)}, {percent:.1f})")
        elif tipo == "log":
            _, key, msg = ev
            self._js(f"appLog({json.dumps(key)}, {json.dumps(msg)})")
        elif tipo == "quota":
            self._conta_richiesta()
        elif tipo == "inizio":
            self._js("appLavoroPartito(" + json.dumps(ev[1]) + ")")
        elif tipo == "annullata":
            # una SINGOLA lezione e' stata annullata (le altre proseguono)
            self._js("appAnnullato(" + json.dumps(ev[1]) + ")")
        elif tipo == "fatta":
            self._lezione_fatta(ev[1], ev[2], lingue)
        elif tipo == "errore":
            self._lezione_errore(ev[1], ev[2], ev[3])
        elif tipo == "fatale":
            self._js("toast('err'," + json.dumps("Errore imprevisto") + "," +
                     json.dumps(ev[1]) + ")")

    def _lezione_fatta(self, key, light, lingue):
        """Lezione completata nel figlio: ricostruisco il Risultato (i documenti
        sono su disco), aggiorno la scheda, salvo e snellisco — come prima."""
        ris = Risultato(
            nome=light.get("nome", ""),
            work_dir=Path(light["work_dir"]),
            lingua_sorgente=light.get("lingua_sorgente", ""),
            documenti=[Path(d) for d in light.get("documenti", [])],
            completo=bool(light.get("completo", True)),
        )
        self._fatte[key] = ris
        self._scrivi_meta(key, ris, lingue)
        info = {"documenti": len(ris.documenti),
                "lingue": ", ".join(x.upper() for x in lingue),
                "completo": bool(light.get("completo", True)),
                "blocchi_falliti": int(light.get("blocchi_falliti", 0))}
        self._js("appLezioneFatta(" + json.dumps(key) + "," + json.dumps(info) + ")")
        if self._cartella_batch:
            self._autosave(key, ris, self._cartella_batch)
        self._snellisci(ris.work_dir)

    def _lezione_errore(self, key, kind, msg):
        """Errore su una lezione: titolo + messaggio GENTILI a seconda del tipo o del
        contenuto. Gli errori 'grezzi' dell'API Gemini (503/429/rete) vengono tradotti
        in qualcosa di comprensibile invece di mostrare il JSON dell'errore."""
        low = (msg or "").lower()
        titoli = {
            "LimiteGiornaliero": "Finite le lezioni di oggi",
            "DownloadFallito": "Download non riuscito",
            "ContenutoBloccato": "Contenuto non trascrivibile",
            "ChiaveMancante": "Impossibile procedere",
            "FfmpegMancante": "Impossibile procedere",
        }
        if kind in titoli:
            titolo, testo = titoli[kind], (msg or "")[:200]
        elif any(x in low for x in ("503", "unavailable", "high demand", "overloaded")):
            titolo = "Google è sovraccarico in questo momento"
            testo = ("I server di Gemini sono molto richiesti adesso: è un intoppo temporaneo, "
                     "non un problema della tua lezione. Aspetta qualche minuto e premi «Riprova» "
                     "sulla scheda: il lavoro già fatto è salvato e riparte da dove si era fermato.")
        elif "429" in low or "resource_exhausted" in low or "rate limit" in low:
            titolo = "Troppe richieste in questo momento"
            testo = ("Gemini sta limitando le richieste (troppe in poco tempo). Aspetta un minuto "
                     "e premi «Riprova» sulla scheda: riprende da dove era.")
        elif any(x in low for x in ("timed out", "timeout", "connection", "getaddrinfo",
                                     "temporary failure", "network", "ssl", "urlopen")):
            titolo = "Problema di connessione"
            testo = ("Sembra un problema di rete. Controlla la connessione e premi «Riprova» "
                     "sulla scheda per riprendere.")
        else:
            titolo, testo = "Errore durante l'elaborazione", (msg or "")[:200]
        self._js("appErrore(" + json.dumps(key) + "," +
                 json.dumps(titolo) + "," + json.dumps(testo) + ")")


# --- Controllo runtime WebView2 -------------------------------------------
# pywebview su Windows rende la finestra con WebView2 (componente Microsoft). Su
# Win10/11 aggiornati c'e' quasi sempre; se manca, l'app non si aprirebbe. Qui lo
# rileviamo dal registro e, se assente, mostriamo un messaggio chiaro col download
# invece di fallire in silenzio. (Link diretto all'installer "Evergreen Bootstrapper".)
_WV2_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_WV2_DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def _webview2_presente() -> bool:
    """True se il runtime WebView2 risulta installato (per-macchina o per-utente)."""
    import winreg
    rami = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\\" + _WV2_CLIENT),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + _WV2_CLIENT),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\\" + _WV2_CLIENT),
    ]
    for hive, path in rami:
        try:
            with winreg.OpenKey(hive, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv not in ("", "0.0.0.0"):
                    return True
        except OSError:
            continue
    return False


def _avvisa_webview2_mancante() -> None:
    """Messaggio nativo (senza finestra web) + apre il download di WebView2."""
    msg = ("Per funzionare, questa app usa il componente gratuito Microsoft \"WebView2\",\n"
           "che non risulta installato su questo PC.\n\n"
           "Premendo OK si apre il download: installa \"Evergreen Bootstrapper\",\n"
           "poi riapri l'app.")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Trascrivi Lezioni — componente mancante", 0x40)
    except Exception:
        pass
    try:
        webbrowser.open(_WV2_DOWNLOAD)
    except Exception:
        pass


def _dopo_avvio(api):
    """Girato in un thread da webview.start, a GUI gia' su. Controlla se c'e' una
    versione piu' nuova su GitHub e, se si', mostra il banner in UI. Silenzioso su
    ogni errore (niente rete, repo non configurato, GUI non ancora pronta)."""
    try:
        agg = aggiornamenti.controlla()
    except Exception:
        return
    if not agg:
        return
    # Aspetto che la PAGINA sia caricata, altrimenti evaluate_js andrebbe a vuoto e il
    # banner (throttle giornaliero) sparirebbe per tutta la sessione. Best-effort.
    try:
        api._window.events.loaded.wait(15)
    except Exception:
        pass
    api._js(f"appAggiornamento({json.dumps(agg['versione'])}, {json.dumps(agg['url'])})")


def main():
    # Necessario quando l'app sara' un .exe (PyInstaller): senza, il processo
    # figlio di trascrizione (spawn) ri-lancerebbe l'intera app. Innocuo da sorgente.
    multiprocessing.freeze_support()
    # La console puo essere in cp1252: evitiamo crash sulle emoji nei print di debug.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    # WebView2 assente → messaggio chiaro + download, invece di non aprirsi in silenzio.
    if os.name == "nt" and not _webview2_presente():
        _avvisa_webview2_mancante()
        return

    api = Api()
    window = webview.create_window(
        "Trascrivi Lezioni",
        url=str(UI_FILE),
        js_api=api,
        width=1040,
        height=760,
        min_size=(840, 620),
    )
    api._collega_finestra(window)
    # Controllo aggiornamenti: gira DOPO che la GUI e' partita (webview.start chiama
    # _dopo_avvio in un thread suo), mai in avvio sincrono (lezione imparata col freeze
    # di dl.info()). Tutto in try/except: qualunque intoppo e' un no-op silenzioso.
    webview.start(_dopo_avvio, api, debug=percorsi.DEBUG)   # devtools solo con TRASCRITTORE_DEBUG=1 (mai nel pacchetto)


if __name__ == "__main__":
    main()
