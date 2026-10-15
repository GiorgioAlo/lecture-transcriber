"""Utility condivise. Per ora: scrittura ATOMICA di file.

Serve perche' la trascrizione gira in un processo che l'utente puo' UCCIDERE
all'istante (Annulla immediato). Se un file di cache venisse ucciso a meta'
scrittura, resterebbe TRONCATO e alla ripresa verrebbe riusato come se fosse
completo (output rovinato in silenzio). Scrivendo prima un file temporaneo nella
stessa cartella e poi rinominandolo (os.replace, atomico su Windows e POSIX),
su disco c'e' sempre O la versione vecchia O quella nuova intera, mai una a meta'.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def scrivi_testo(path, testo: str, encoding: str = "utf-8") -> Path:
    """Scrive `testo` in `path` in modo atomico (tmp nella stessa cartella + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=path.suffix or ".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(testo)
        os.replace(tmp, path)       # atomico: sostituisce in un colpo solo
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def percorso_atomico(path):
    """Ritorna (tmp, path) per scrivere un file BINARIO in modo atomico.

    Chi chiama scrive su `tmp` (es. doc.save(tmp)) e poi chiama `concludi_atomico`.
    Utile per i .docx, che una libreria salva da sola su un percorso."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=path.suffix or ".tmp")
    os.close(fd)
    return tmp, path


def concludi_atomico(tmp, path) -> None:
    """Rinomina il temporaneo sul percorso finale (o pulisce in caso d'errore)."""
    try:
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
