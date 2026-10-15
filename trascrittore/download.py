"""Download dell'audio di una lezione da un link (YouTube, Webex, ...) con yt-dlp.

Scarica SOLO l'audio (non il video) in `work_dir/scaricato.<ext>`; la pipeline
poi lo normalizza a mono 16k e lo spezza come un qualsiasi file locale.

Per Webex serve un file cookies.txt (sessione autenticata) e talvolta una
password del video. yt-dlp viene invocato come modulo dell'ambiente corrente
(`python -m yt_dlp`) così usa sempre la versione giusta.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from . import audio, percorsi
from .errors import DownloadFallito, Interrotto
from .progress import Reporter

# App "windowed" (senza console, come nel .exe): su Windows ogni subprocess verso
# yt-dlp aprirebbe una finestra di terminale. CREATE_NO_WINDOW la sopprime.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _ffmpeg_dir() -> str | None:
    """Cartella di ffmpeg (per passare --ffmpeg-location a yt-dlp)."""
    try:
        p = Path(audio._trova("ffmpeg"))
        if p.exists():
            return str(p.parent)
    except Exception:
        pass
    return None


_PARZIALI = (".part", ".ytdl", ".temp", ".tmp")


def _scaricati_completi(work_dir: Path) -> list[Path]:
    """File 'scaricato.*' COMPLETI (esclude i parziali di un download interrotto).

    yt-dlp scrive 'scaricato.webm.part' mentre scarica: riusarlo darebbe un
    audio troncato. Teniamo solo i file senza estensione di lavoro."""
    out = []
    for p in sorted(work_dir.glob("scaricato.*")):
        if p.suffix.lower() in _PARZIALI or any(s in p.suffixes for s in _PARZIALI):
            continue
        out.append(p)
    return out


def e_webex(url: str) -> bool:
    try:
        return "webex.com" in (urlparse(url).netloc or "").lower()
    except Exception:
        return "webex.com" in (url or "").lower()


def _url_valido(url: str) -> bool:
    """True solo per URL http/https. Blocca:
    - l'ARGUMENT INJECTION in yt-dlp (una stringa che inizia con '-' sarebbe letta
      come OPZIONE, es. --config-locations/--exec → esecuzione comandi);
    - schemi pericolosi come file:// (lettura di file locali).
    Difesa in profondita' insieme al separatore '--' messo prima dell'URL."""
    try:
        return (urlparse(url).scheme or "").lower() in ("http", "https")
    except Exception:
        return False


# --- localizzazione di yt-dlp (binario standalone, auto-aggiornabile) -------
# Preferiamo il BINARIO `yt-dlp.exe`, non `python -m yt_dlp`, perche':
#  - nel pacchetto .exe `python -m yt_dlp` NON esiste (sys.executable e' l'app, non
#    un interprete) → l'invocazione a modulo si lancerebbe l'app addosso;
#  - il binario sa AUTO-AGGIORNARSI (`yt-dlp.exe -U`) dal GitHub di yt-dlp, e yt-dlp
#    e' la cosa che si rompe piu' spesso (YouTube/Webex cambiano) → aggiornamenti
#    "gratis" senza che noi ridistribuiamo l'app.
# Deve stare in una cartella SCRIVIBILE (percorsi.dir_dati, = %LOCALAPPDATA% nel
# pacchetto) perche' `-U` possa sovrascriverlo. In SVILUPPO, se il binario non c'e',
# si ripiega su `python -m yt_dlp` (comodo, nessun setup, comportamento invariato).
_YTDLP_EXE = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"


def _ytdlp_binario() -> Path | None:
    """Percorso del binario standalone yt-dlp, o None se non disponibile."""
    # 1) override esplicito (test o posizione personalizzata)
    override = os.environ.get("TRASCRITTORE_YTDLP_DIR")
    if override and (Path(override) / _YTDLP_EXE).exists():
        return Path(override) / _YTDLP_EXE
    # 2) copia scrivibile per-utente: e' QUESTA che si auto-aggiorna con -U
    dati = percorsi.dir_dati() / _YTDLP_EXE
    if dati.exists():
        percorsi.assicura_eseguibile(dati)   # su Mac/Linux garantisce il +x
        return dati
    # 3) seme impacchettato (bundle PyInstaller): lo copiamo UNA volta nella cartella
    #    dati, cosi' da li' in poi puo' aggiornarsi da solo.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / _YTDLP_EXE).exists():
        try:
            dati.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(meipass) / _YTDLP_EXE, dati)
            percorsi.assicura_eseguibile(dati)   # il seme 'datas' puo' aver perso il +x
            return dati
        except OSError:
            ripiego = Path(meipass) / _YTDLP_EXE   # uso dal bundle (non si aggiorna)
            percorsi.assicura_eseguibile(ripiego)
            return ripiego
    return None


def _ytdlp_cmd() -> tuple[list[str], bool]:
    """Prefisso del comando yt-dlp e flag 'e' il binario standalone' (serve a sapere
    se `-U` ha senso). In sviluppo senza binario → (`python -m yt_dlp`, False)."""
    b = _ytdlp_binario()
    if b:
        return [str(b)], True
    return [sys.executable, "-m", "yt_dlp"], False


def aggiorna_ytdlp(reporter: Reporter | None = None, timeout: int = 120) -> bool:
    """Auto-aggiorna yt-dlp (`-U`). Ha senso SOLO col binario standalone (col modulo
    pip lo gestisce l'ambiente). Ritorna True se l'aggiornamento e' andato a buon fine."""
    cmd, binario = _ytdlp_cmd()
    if not binario:
        return False
    try:
        res = subprocess.run(cmd + ["-U"], capture_output=True, text=True, timeout=timeout,
                             creationflags=_NO_WINDOW)
        if reporter and (res.stdout or "").strip():
            reporter.log("yt-dlp: " + res.stdout.strip().splitlines()[-1])
        return res.returncode == 0
    except Exception:
        return False


def _base_cmd(url: str, cookies: str | None, password: str | None) -> list[str]:
    # `--no-playlist`: se l'URL contiene `&list=...` (tipico del link che Chrome copia
    # dalla barra, spesso un Mix/Radio `RD...` praticamente infinito), yt-dlp di default
    # scaricherebbe TUTTA la playlist → lentissimo e "sembra bloccato". Noi vogliamo
    # sempre e solo IL singolo video della lezione.
    cmd = _ytdlp_cmd()[0] + ["--no-warnings", "--restrict-filenames", "--no-playlist"]
    ff = _ffmpeg_dir()
    if ff:
        cmd += ["--ffmpeg-location", ff]
    if e_webex(url):
        host = urlparse(url).netloc
        cmd += ["--add-header", f"Referer: https://{host}"]
    if cookies:
        cmd += ["--cookies", str(cookies)]
    if password:
        cmd += ["--video-password", str(password)]
    return cmd


def info(url: str, cookies: str | None = None) -> dict:
    """Titolo + durata (secondi) SENZA scaricare. Campi vuoti se non recuperabili."""
    if not _url_valido(url):
        return {"titolo": "", "durata": None}
    cmd = _base_cmd(url, cookies, None) + ["--skip-download", "--print",
                                           "%(title)s\t%(duration)s", "--", url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             creationflags=_NO_WINDOW)
        if res.returncode == 0 and res.stdout.strip():
            titolo, _, dur = res.stdout.strip().partition("\t")
            dur = dur.strip()
            durata = float(dur) if re.fullmatch(r"[0-9]+(\.[0-9]+)?", dur) else None
            return {"titolo": titolo.strip(), "durata": durata}
    except Exception:
        pass
    return {"titolo": "", "durata": None}


def scarica(
    url: str,
    work_dir: Path,
    cookies: str | None,
    password: str | None,
    reporter: Reporter,
    avanzamento=lambda fr: None,
) -> Path:
    """Scarica il bestaudio in work_dir/scaricato.<ext> e ritorna il percorso.

    Se un file 'scaricato.*' esiste gia', lo riusa (ripresa). `avanzamento(fr)`
    riceve 0..1 man mano che il download procede."""
    if not _url_valido(url):
        raise DownloadFallito("Link non valido: inserisci un indirizzo che inizia con http:// o https://.")
    work_dir.mkdir(parents=True, exist_ok=True)
    esistenti = _scaricati_completi(work_dir)
    if esistenti:
        reporter.log("Audio del link gia' scaricato, lo riuso")
        return esistenti[0]

    try:
        return _esegui_download(url, work_dir, cookies, password, reporter, avanzamento)
    except DownloadFallito:
        # Un fallimento e' spesso yt-dlp vecchio (il sito e' cambiato): provo ad
        # AGGIORNARLO e riprovo UNA volta. Se non e' il binario (o l'update non va),
        # rilancio l'errore originale. L'annullo (Interrotto) NON entra qui.
        if aggiorna_ytdlp(reporter):
            reporter.log("Riprovo con yt-dlp aggiornato…")
            return _esegui_download(url, work_dir, cookies, password, reporter, avanzamento)
        raise


def _esegui_download(
    url: str,
    work_dir: Path,
    cookies: str | None,
    password: str | None,
    reporter: Reporter,
    avanzamento=lambda fr: None,
) -> Path:
    """Un singolo tentativo di download (usato da `scarica`, anche per la riprova)."""
    # Ripuliamo eventuali parziali di un tentativo interrotto, cosi yt-dlp
    # riparte pulito invece di accodarsi a un .part sbagliato.
    for p in work_dir.glob("scaricato.*"):
        p.unlink(missing_ok=True)

    cmd = _base_cmd(url, cookies, password) + [
        "-f", "bestaudio/best", "-o", str(work_dir / "scaricato.%(ext)s"),
        "--newline", "--", url,
    ]
    reporter.log("Scarico l'audio dal link...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, creationflags=_NO_WINDOW)
    # L'output di yt-dlp lo legge un THREAD a parte che lo mette in coda. Il ciclo
    # principale la controlla ogni ~0,5s e a ogni giro verifica l'annullo: cosi'
    # l'Annulla resta REATTIVO anche quando yt-dlp e' muto a lungo (YouTube lento/
    # throttling). Prima il ciclo si bloccava in `for line in proc.stdout` in attesa di
    # una riga, e l'annullo (e la barra) restavano fermi finche' non ne arrivava una.
    righe: "queue.Queue" = queue.Queue()

    def _leggi_output():
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                righe.put(line)
        finally:
            righe.put(None)   # sentinella: output finito

    threading.Thread(target=_leggi_output, daemon=True).start()
    coda_errori: list[str] = []
    ultimo_decile = -1    # progresso loggato solo ogni ~10% (la barra resta fluida)
    try:
        while True:
            if reporter.interrotto():
                proc.terminate()
                raise Interrotto()
            try:
                line = righe.get(timeout=0.5)
            except queue.Empty:
                continue      # yt-dlp muto: ricontrollo l'annullo e riaspetto
            if line is None:
                break         # output finito
            line = line.rstrip()
            if line:
                coda_errori.append(line)
                if len(coda_errori) > 15:
                    coda_errori.pop(0)
            m = re.search(r"\[download\]\s+([0-9.]+)%", line)
            if m:
                try:
                    pct = float(m.group(1))
                except ValueError:
                    continue
                avanzamento(min(1.0, pct / 100.0))     # barra: ogni aggiornamento
                decile = int(pct // 10) * 10            # log: solo al cambio di decina
                if decile > ultimo_decile:
                    ultimo_decile = decile
                    reporter.log(f"Scarico l'audio… {decile}%")
    finally:
        proc.wait()

    files = _scaricati_completi(work_dir)
    if proc.returncode != 0 or not files:
        testo = "\n".join(coda_errori).lower()
        if e_webex(url):
            msg = ("Non riesco a scaricare da Webex. I cookie potrebbero essere scaduti "
                   "(riesportali) o il video è protetto da password.")
        elif "sign in" in testo or "login" in testo or "private" in testo:
            msg = "Il video è privato o richiede l'accesso: non posso scaricarlo."
        elif "unsupported url" in testo or "no video" in testo:
            msg = "Questo link non è supportato per il download."
        else:
            msg = "Non sono riuscito a scaricare l'audio dal link (controlla il link e la connessione)."
        raise DownloadFallito(msg)

    avanzamento(1.0)
    return files[0]


def valida_cookies(path: str) -> tuple[bool, str]:
    """Controllo di forma del file cookies.txt (livelli 1-2; il 3 e' il download).

    1) e' un file di cookie in formato Netscape? 2) contiene voci di webex.com?
    Il "funziona davvero" si scopre solo al download (cookie scaduti ecc.)."""
    try:
        testo = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, "Non riesco a leggere il file."
    # Righe-cookie vere = quelle con >=7 campi separati da TAB (incluse le
    # '#HttpOnly_...', che hanno i tab; i commenti normali non hanno tab).
    righe_cookie = [r.split("\t") for r in testo.splitlines()
                    if "\t" in r and len(r.split("\t")) >= 7]
    formato_ok = ("# Netscape HTTP Cookie File" in testo) or bool(righe_cookie)
    if not formato_ok:
        return False, "Questo non è un file di cookie valido (serve il formato Netscape, non un .txt qualsiasi)."
    # 'webex.com' deve stare nel CAMPO DOMINIO (il primo) di una riga-cookie,
    # non comparire da qualche parte nel testo (cosi un file a caso non passa).
    ha_webex = any("webex.com" in cols[0].lower() for cols in righe_cookie)
    if not ha_webex:
        return False, "Nel file non ci sono cookie di Webex: esportali mentre sei dentro Webex (sulla pagina della registrazione)."
    return True, ""
