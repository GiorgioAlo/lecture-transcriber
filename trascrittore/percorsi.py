"""Dove l'app scrive i suoi file di lavoro (cache interna + log di debug).

Regola d'oro: da ESEGUIBILE (.exe PyInstaller) non si scrive MAI accanto al
programma. La cartella del programma puo' essere di sola lettura (tipico se
l'utente lo mette in "Program Files") e mescolare i file di lavoro col
programma e' sporco (aggiornamenti/disinstallazione non puliti). Si usa invece
%LOCALAPPDATA%\\Trascrittore, la cartella standard di Windows per i dati-utente
di un'applicazione. (NB: i Word FINALI non passano di qui — quelli l'utente li
salva dove vuole; qui sta solo la cache interna, rigenerabile.)

Da SORGENTE (sviluppo) si resta nella cache/ del repo: comoda da ispezionare e
coerente con i test offline (che usano Path("cache")).

Override esplicito con la variabile d'ambiente TRASCRITTORE_DATA (qualunque
percorso): utile per i test o per spostare i dati altrove.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent   # la radice del repo in sviluppo

_NOME_APP = "Trascrittore"   # nome della cartella dati dell'app, uguale su ogni OS


def _da_eseguibile() -> bool:
    """True se stiamo girando da eseguibile PyInstaller (non da sorgente Python)."""
    return bool(getattr(sys, "frozen", False))


def _dir_dati_sistema() -> Path:
    """Cartella standard dei dati-utente dell'app, SECONDO l'OS (usata da eseguibile).
    Windows: %LOCALAPPDATA%\\Trascrittore; macOS: ~/Library/Application Support/
    Trascrittore; Linux: $XDG_DATA_HOME o ~/.local/share/Trascrittore."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _NOME_APP
    if os.name == "nt":
        radice = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(radice) / _NOME_APP
    # Linux / altri Unix: specifica XDG Base Directory
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / _NOME_APP


def dir_dati() -> Path:
    """Cartella base dei dati di lavoro (contiene cache/ e il log di debug)."""
    override = os.environ.get("TRASCRITTORE_DATA")
    if override:
        return Path(override)
    if _da_eseguibile():
        return _dir_dati_sistema()
    return _REPO


def assicura_eseguibile(percorso) -> None:
    """Su Unix (Mac/Linux) garantisce il bit di esecuzione su un binario incluso
    nel bundle: i file impacchettati da PyInstaller come 'datas' possono perderlo,
    e senza +x `ffmpeg`/`yt-dlp` darebbero 'Permission denied'. No-op su Windows
    (non ha il concetto di bit di esecuzione) e su errore (best-effort)."""
    if os.name == "nt":
        return
    try:
        p = Path(percorso)
        p.chmod(p.stat().st_mode | 0o111)   # +x per utente/gruppo/altri
    except OSError:
        pass


def apri_cartella(percorso) -> None:
    """Apre una cartella nel file manager del sistema (Esplora / Finder / file
    manager Linux). Astrae l'unica chiamata che differisce per OS; chi chiama
    gestisce eventuali eccezioni."""
    p = str(percorso)
    if sys.platform == "darwin":
        subprocess.run(["open", p], check=False)
    elif os.name == "nt":
        os.startfile(p)   # type: ignore[attr-defined]  # esiste solo su Windows
    else:
        subprocess.run(["xdg-open", p], check=False)


def dir_cache() -> Path:
    """Cartella della cache interna (intermedi, chunk, docx di lavoro, quota)."""
    return dir_dati() / "cache"


def risorsa(rel: str) -> Path:
    """Percorso di una risorsa IMPACCHETTATA e di sola lettura (la UI, un'icona, ecc.).

    Da eseguibile PyInstaller sta nella cartella temporanea del bundle (`sys._MEIPASS`);
    da sorgente, nella radice del repo. Diverso da `dir_dati()`, che è scrivibile."""
    base = getattr(sys, "_MEIPASS", None) or _REPO
    return Path(base) / rel


def file_log_debug() -> Path:
    """File del log di debug della coda (scritto solo se DEBUG e' attivo)."""
    return dir_dati() / "debug_coda.log"


# Log di debug SPENTO di default: e' uno strumento da sviluppatore e sull'.exe
# di un amico sarebbe solo rumore che cresce all'infinito (si appende e basta).
# Si accende con TRASCRITTORE_DEBUG=1 per diagnosticare un problema sul PC di un
# amico senza dover ricompilare.
DEBUG = os.environ.get("TRASCRITTORE_DEBUG") == "1"
