"""Operazioni audio con ffmpeg: estrazione, segmentazione, durata.

Isolato qui perché e l'unico punto che tocca ffmpeg. Include la LOCALIZZAZIONE
robusta dei binari: ffmpeg/ffprobe vengono cercati, nell'ordine, in
  1. la cartella indicata da TRASCRITTORE_FFMPEG_DIR (usata nel .exe impacchettato);
  2. il PATH di sistema;
  3. la cartella dell'ambiente conda corrente (<sys.prefix>\\Library\\bin su Windows);
  4. come ultimo tentativo, il nome nudo ("ffmpeg").
Cosi l'app funziona anche se lanciata senza "conda activate".
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from . import percorsi
from .errors import FfmpegMancante

# App "windowed" (senza console, come nel .exe): su Windows ogni subprocess verso
# ffmpeg/ffprobe aprirebbe una finestra di terminale lampeggiante. CREATE_NO_WINDOW
# la sopprime. 0 fuori da Windows (il flag non esiste).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@lru_cache(maxsize=None)
def _trova(nome: str) -> str:
    """Percorso completo di 'ffmpeg'/'ffprobe', o il nome nudo se non trovato."""
    exe = nome + (".exe" if os.name == "nt" else "")

    # 1) override esplicito (bundle .exe)
    override = os.environ.get("TRASCRITTORE_FFMPEG_DIR")
    if override and (Path(override) / exe).exists():
        return str(Path(override) / exe)

    # 2) PATH di sistema
    trovato = shutil.which(nome)
    if trovato:
        return trovato

    # 3) ambiente conda corrente (dove conda-forge mette i binari su Windows)
    candidati = [
        Path(sys.prefix) / "Library" / "bin" / exe,   # Windows (conda)
        Path(sys.prefix) / "bin" / exe,                # Linux/Mac (conda)
    ]
    # 4) bundle PyInstaller (se presente)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidati.insert(0, Path(meipass) / exe)

    for c in candidati:
        if c.exists():
            if meipass and c == Path(meipass) / exe:
                percorsi.assicura_eseguibile(c)   # su Mac/Linux il binario incluso potrebbe non avere +x
            return str(c)

    return nome  # tentiamo comunque: forse e nel PATH del processo figlio


def _bin(nome: str) -> str:
    return _trova(nome)


def _verifica_ffmpeg() -> None:
    for nome in ("ffmpeg", "ffprobe"):
        p = _trova(nome)
        # se _trova ha restituito il nome nudo e non e nel PATH, e assente
        if p == nome and shutil.which(nome) is None:
            raise FfmpegMancante(
                f"{nome} non trovato. Installa ffmpeg o imposta TRASCRITTORE_FFMPEG_DIR."
            )


def estrai_audio(sorgente: Path, dest: Path, inizio_min: float = 0, minuti: float | None = None) -> None:
    """Estrae (ed eventualmente ritaglia) l'audio in AAC mono 16 kHz, compatto per l'upload.

    Scrittura ATOMICA: ffmpeg scrive su un file `.part` e solo a estrazione
    COMPLETATA lo rinominiamo in `dest`. Cosi' se il processo viene ucciso a meta'
    (es. "Annulla tutto" = terminate() mentre ffmpeg scrive), resta al massimo un
    `.part` ignorato, MAI un `dest` troncato che a una ripresa verrebbe scambiato
    per audio valido e manderebbe in errore la segmentazione."""
    _verifica_ffmpeg()
    # Il temporaneo DEVE conservare l'estensione (.m4a): ffmpeg sceglie il muxer
    # dall'estensione del file di uscita, un ".part" lo manderebbe in errore.
    # Il PID nel nome lo rende UNICO per processo: se un "annulla tutto" (terminate)
    # lascia un ffmpeg ORFANO che continua a scrivere il suo .part, la ripresa usa un
    # altro .part e non ci finiscono due scrittori sullo stesso file (niente corruzione).
    tmp = dest.with_name(f"{dest.stem}.part{os.getpid()}{dest.suffix}")   # es. audio.part12345.m4a
    cmd = [_bin("ffmpeg"), "-y", "-loglevel", "error"]
    if inizio_min:
        cmd += ["-ss", str(int(inizio_min * 60))]
    cmd += ["-i", str(sorgente)]
    if minuti:
        cmd += ["-t", str(int(minuti * 60))]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k", str(tmp)]
    try:
        subprocess.run(cmd, check=True, creationflags=_NO_WINDOW)
        os.replace(tmp, dest)       # comparsa atomica di `dest`: o c'e' tutto, o niente
    finally:
        try:
            tmp.unlink()            # su errore/eccezione non lasciare il .part parziale
        except OSError:
            pass                    # gia' rinominato (successo) o mai creato


def segmenta(audio: Path, chunk_dir: Path, secondi: int) -> None:
    """Divide l'audio in blocchi da `secondi` (stream copy: veloce, niente ri-encoding).

    ATOMICA: ffmpeg scrive i blocchi in una cartella temporanea (unica per PID) e solo
    a comando COMPLETATO la si sostituisce a `chunk_dir`. Cosi' un kill a meta' non lascia
    un set di blocchi PARZIALE che una ripresa scambierebbe per completo (saltando la
    ri-segmentazione e trascrivendo una lezione troncata)."""
    _verifica_ffmpeg()
    tmp_dir = chunk_dir.with_name(f"{chunk_dir.name}.part{os.getpid()}")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([_bin("ffmpeg"), "-y", "-loglevel", "error", "-i", str(audio),
                        "-c", "copy", "-f", "segment", "-segment_time", str(secondi),
                        str(tmp_dir / "part_%03d.m4a")], check=True, creationflags=_NO_WINDOW)
        shutil.rmtree(chunk_dir, ignore_errors=True)   # via il vecchio set (vuoto o parziale)
        os.replace(tmp_dir, chunk_dir)                 # comparsa ATOMICA del set completo
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)     # su errore: niente temporaneo orfano


def durata(path: Path) -> float:
    """Durata in secondi di un file audio/video (0 se non leggibile)."""
    out = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                         creationflags=_NO_WINDOW)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0
