"""Segni del tempo nei documenti: "⏱ ~10 min", "⏱ ~20 min", ..., "⏱ ~1 h 10 min".

Servono solo a ORIENTARSI (ritrovare piu' o meno un punto nel video): sono
approssimati, e va bene cosi'. Le chiamate a Gemini e i blocchi di testo NON
cambiano: il segno si aggiunge solo quando si scrive il documento.

Come si calcola dove cade "~10 min":
  1. durante la trascrizione salviamo, per ogni pezzo audio (~10 min), la sua
     DURATA e QUANTO TESTO ne e' uscito (`tempi.json` nella cartella della lezione);
  2. dentro un pezzo il testo e' in proporzione al tempo -> sappiamo a che punto
     del grezzo siamo al minuto 10 (es. "al 12% del testo");
  3. il testo pulito/tradotto ha piu' o meno le stesse proporzioni del grezzo ->
     andiamo al 12% del testo finale e mettiamo il segno all'inizio della frase
     piu' vicina (mai a meta' frase, mai dentro una nota).
Ragionare pezzo per pezzo (e non sull'intera lezione) tiene conto delle parti
in cui si parla poco (pause, esercizi): l'errore resta piccolo.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config, util

FILE = "tempi.json"
PASSO_S = 600          # un segno ogni 10 minuti
MARGINE_S = 60         # niente segni nel primo e nell'ultimo minuto (inutili)

_FINE_FRASE = re.compile(r"[.!?…]+[\"'”’»)\]]*\s+")


# --- Salvataggio e lettura della mappa dei tempi ------------------------------

def salva(work_dir: Path, durate: list[float], testi: list[str]) -> None:
    """Scrive `tempi.json`: [durata in secondi, caratteri di testo] per ogni pezzo
    audio, in ordine. Se una durata non e' leggibile, niente mappa (niente segni)."""
    path = Path(work_dir) / FILE
    if not durate or any(d <= 0 for d in durate):
        path.unlink(missing_ok=True)
        return
    pezzi = [[round(float(d), 2), len(t or "")] for d, t in zip(durate, testi)]
    util.scrivi_testo(path, json.dumps({"pezzi": pezzi}))


def cancella(work_dir: Path) -> None:
    (Path(work_dir) / FILE).unlink(missing_ok=True)


def carica(work_dir: Path, grezza: str) -> list[tuple[float, int]] | None:
    """La mappa dei tempi, se c'e' ed e' coerente con la trascrizione grezza.
    Se la grezza non corrisponde (es. mappa di una trascrizione vecchia) -> None."""
    try:
        dati = json.loads((Path(work_dir) / FILE).read_text(encoding="utf-8"))
        pezzi = [(float(d), int(c)) for d, c in dati["pezzi"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not pezzi or any(d <= 0 or c < 0 for d, c in pezzi):
        return None
    # la grezza = i testi dei pezzi non vuoti uniti da "\n"
    attesi = sum(c for _, c in pezzi) + max(0, sum(1 for _, c in pezzi if c) - 1)
    if abs(attesi - len(grezza or "")) > max(50, 0.02 * attesi):
        return None
    return pezzi


# --- Dove cadono i segni ------------------------------------------------------

def etichetta(secondi: float) -> str:
    """600 -> "~10 min", 3600 -> "~1 h", 4200 -> "~1 h 10 min"."""
    minuti = int(round(secondi / 60))
    ore, resto = divmod(minuti, 60)
    if not ore:
        return f"~{minuti} min"
    return f"~{ore} h" if not resto else f"~{ore} h {resto} min"


def _carattere(pezzi: list[tuple[float, int]], t: float) -> float:
    """Posizione (in caratteri del grezzo) corrispondente al secondo `t` dell'audio."""
    t_acc, c_acc = 0.0, 0
    for d, c in pezzi:
        if t <= t_acc + d:
            return c_acc + (t - t_acc) / d * c
        t_acc += d
        c_acc += c
    return float(c_acc)


def posizioni(pezzi: list[tuple[float, int]] | None, inizio_s: float = 0.0) -> list[tuple[float, str]]:
    """[(frazione del testo, etichetta), ...] per ogni multiplo di 10 minuti.
    `inizio_s` = da che secondo del video parte l'audio trascritto (spezzoni):
    le etichette sono sempre tempi del VIDEO."""
    if not pezzi:
        return []
    durata = sum(d for d, _ in pezzi)
    caratteri = sum(c for _, c in pezzi)
    if caratteri <= 0:
        return []
    segni = []
    t_video = (int(inizio_s // PASSO_S) + 1) * PASSO_S
    while True:
        t = t_video - inizio_s                    # secondo dentro l'audio trascritto
        if t > durata - MARGINE_S:
            break
        if t >= MARGINE_S:
            segni.append((_carattere(pezzi, t) / caratteri, etichetta(t_video)))
        t_video += PASSO_S
    return segni


# --- Inserimento nel testo del documento --------------------------------------

def _riga_speciale(riga: str) -> bool:
    """Note sulle parti non riuscite e segni gia' presenti: mai un segno li dentro."""
    s = riga.strip()
    return s.startswith("[⚠") or s.startswith(config.MARCATORE_TEMPO)


def riga_segno(etichetta_: str) -> str:
    return f"{config.MARCATORE_TEMPO} {etichetta_}]"


def inserisci(testo: str, segni: list[tuple[float, str]]) -> str:
    """Mette una riga "[⏱ ~10 min]" per ogni segno, all'inizio della frase piu'
    vicina al punto calcolato. Le righe-nota non contano nelle proporzioni (una
    parte non tradotta e' solo una nota: il testo che c'e' resta allineato)."""
    if not segni or not testo:
        return testo
    testo = testo.replace("\r\n", "\n").replace("\r", "\n")
    # candidati: (posizione nel "contenuto", posizione nel testo, a inizio riga?)
    candidati: list[tuple[int, int, bool]] = []
    contenuto = assoluta = 0
    for riga in testo.split("\n"):
        if riga.strip() and not _riga_speciale(riga):
            candidati.append((contenuto, assoluta, True))
            for m in _FINE_FRASE.finditer(riga):
                if m.end() < len(riga):
                    candidati.append((contenuto + m.end(), assoluta + m.end(), False))
            contenuto += len(riga) + 1
        assoluta += len(riga) + 1
    if not candidati or contenuto <= 0:
        return testo

    scelti: dict[int, tuple[bool, str]] = {}
    for frazione, etich in segni:
        obiettivo = frazione * contenuto
        _, pos, a_capo = min(candidati, key=lambda k: abs(k[0] - obiettivo))
        scelti.setdefault(pos, (a_capo, etich))       # due segni sulla stessa frase: tengo il primo

    for pos in sorted(scelti, reverse=True):          # dal fondo: le posizioni prima restano valide
        a_capo, etich = scelti[pos]
        if a_capo:
            testo = testo[:pos] + riga_segno(etich) + "\n" + testo[pos:]
        else:
            testo = testo[:pos].rstrip() + "\n" + riga_segno(etich) + "\n" + testo[pos:]
    return testo
