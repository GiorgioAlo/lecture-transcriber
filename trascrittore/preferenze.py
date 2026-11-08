"""Preferenze dell'utente che devono restare tra un avvio e l'altro dell'app.

Un piccolo `preferenze.json` nella cartella dati (vedi percorsi.dir_dati): da
eseguibile sta in %LOCALAPPDATA%\\Trascrittore (o l'equivalente Mac/Linux), da
sorgente nella radice del repo (ignorato da git).

Per ora contiene solo i formati dei documenti finali. Non usiamo il localStorage
della pagina: e' legato al motore web della finestra e non e' garantito che
sopravviva alla chiusura dell'app. Qualunque errore (file mancante, rovinato,
cartella non scrivibile) NON deve mai bloccare l'app: si torna ai valori di default.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from . import documents, percorsi, util


def _file() -> Path:
    return percorsi.dir_dati() / "preferenze.json"


def _leggi_tutto() -> dict:
    try:
        f = _file()
        if f.exists():
            dati = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(dati, dict):
                return dati
    except Exception:
        traceback.print_exc()
    return {}


def _scrivi(chiave: str, valore) -> None:
    try:
        dati = _leggi_tutto()
        dati[chiave] = valore
        util.scrivi_testo(_file(), json.dumps(dati, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()


def formati() -> list[str]:
    """Formati dei documenti scelti dall'utente (default: solo Word)."""
    return documents.normalizza_formati(_leggi_tutto().get("formati"))


def salva_formati(scelti) -> list[str]:
    """Salva la scelta (ripulita: mai vuota) e la ritorna."""
    puliti = documents.normalizza_formati(scelti)
    _scrivi("formati", puliti)
    return puliti
