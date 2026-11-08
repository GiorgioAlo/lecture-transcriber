"""FASE 4 — Generazione dei documenti finali (Word, testo semplice, Markdown).

Prende il testo finale di una lingua e produce un documento impaginato:
copertina + paragrafi, con le domande in corsivo e i timestamp in grassetto.

Il testo viene letto UNA volta in "blocchi" (titolo / punto elenco / paragrafo,
vedi `_blocchi`); i tre formati sono solo modi diversi di scrivere quei blocchi,
cosi Word, .txt e .md hanno sempre gli stessi paragrafi e gli stessi titoli.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from . import util

TIMESTAMP_RE = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
ALLCAPS_RE = re.compile(r"^[A-ZÀ-Ü0-9\s\-–—:]{3,}$")


def _sembra_titolo(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 70:
        return False
    # Una frase vera (finisce con . ? !) non e' un titolo, anche se urlata in
    # maiuscolo: evita che "OK." o "NON CAPISCO." diventino intestazioni.
    if s.endswith((".", "?", "!")):
        return False
    return s.endswith(":") or ALLCAPS_RE.match(s) is not None


def _aggiungi_copertina(doc, titolo, sottotitolo="", note=""):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(titolo); r.bold = True; r.font.size = Pt(28)
    if sottotitolo:
        p2 = doc.add_paragraph(); p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.add_run(sottotitolo).font.size = Pt(14)
    if note:
        p3 = doc.add_paragraph(); p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r3 = p3.add_run(note); r3.italic = True; r3.font.size = Pt(11)
    doc.add_page_break()


def _aggiungi_paragrafo(doc, testo):
    para = doc.add_paragraph()
    # Corsivo SOLO sulla frase che e' una domanda (finisce con "?"), non sul testo
    # che la segue: dopo il reflow un paragrafo contiene piu' frasi, quindi
    # isoliamo le domande frase per frase (_dividi_frasi gestisce le abbreviazioni).
    frasi = _dividi_frasi(testo) or [testo]
    for k, frase in enumerate(frasi):
        if k:
            para.add_run(" ")                                   # spazio tra le frasi
        is_q = _e_domanda(frase)
        for i, part in enumerate(TIMESTAMP_RE.split(frase)):
            if not part:
                continue
            run = para.add_run(f"[{part}]" if i % 2 else part)
            if i % 2:
                run.bold = True
            if is_q:
                run.italic = True


# --- Reflow: ricuce i frammenti dell'ASR in paragrafi leggibili ------------
# La trascrizione (ASR) va a capo a OGNI pausa del parlato e il modello di testo
# trasforma quelle righe in paragrafi separati: cosi nel Word finiva un inciso
# per paragrafo (tipico nelle parti di dialogo/chiusura). Qui riuniamo i frammenti
# in prosa e li ri-raggruppiamo in paragrafi di lunghezza leggibile. Il TESTO non
# cambia (stesse parole): cambia solo come e' spezzato in righe.
REFLOW_TARGET_CHARS = 360          # lunghezza-bersaglio di un paragrafo

# Abbreviazioni dopo cui un punto NON chiude la frase: evita i falsi tagli tipo
# "Dr." o "e.g.". Confronto in minuscolo, con gli eventuali punti interni tolti.
_ABBR = {
    # inglese
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie",
    "cf", "al", "fig", "figs", "no", "nos", "inc", "ltd", "co", "corp", "eq",
    "eqs", "approx", "dept", "univ", "vol", "ch", "sec", "pp", "pg", "ca", "et",
    "viz", "esp", "us", "uk",
    # italiano
    "dott", "sig", "ing", "ecc", "es", "pag", "cfr", "art", "cap", "par", "n",
}


def _fine_frase(frase: str, prossimo: str) -> bool:
    """True se il punto in fondo a `frase` chiude DAVVERO una frase (non e'
    un'abbreviazione ne' un'iniziale puntata). `prossimo` = testo che segue."""
    m = re.search(r"([A-Za-zÀ-ü.'’‘]+)[.!?]+$", frase)
    ultima = re.sub(r"[.'’‘]", "", m.group(1) if m else "").lower()
    if ultima in _ABBR:                 # Dr., Prof., e.g., ecc.
        return False
    if len(ultima) == 1:                # iniziale puntata ("A.", o la "g" di "e.g.")
        return False
    p = prossimo.lstrip()
    if p and not (p[0].isupper() or p[0].isdigit() or p[0] in "\"'“‘([«"):
        return False                    # cio' che segue non inizia "da frase": punto interno
    return True


def _dividi_frasi(testo: str) -> list[str]:
    """Spezza il testo in frasi su . ! ? , ricucendo i tagli falsi (_fine_frase)."""
    parti = re.split(r"([.!?]+)(\s+)", testo)   # [corpo, punt, spazio, corpo, ...]
    frasi, cur = [], ""
    for i in range(0, len(parti), 3):
        cur += parti[i] + (parti[i + 1] if i + 1 < len(parti) else "")
        punt = parti[i + 1] if i + 1 < len(parti) else ""
        prossimo = parti[i + 3] if i + 3 < len(parti) else ""
        if punt and _fine_frase(cur, prossimo):
            frasi.append(cur.strip()); cur = ""
        elif i + 2 < len(parti):
            cur += parti[i + 2]                 # spazio: la frase continua
    if cur.strip():
        frasi.append(cur.strip())
    return frasi


def _reflow(righe: list[str]) -> list[str]:
    """Unisce righe-frammento in un flusso e lo raggruppa in paragrafi di ~TARGET
    caratteri (almeno 2 frasi l'uno), tagliando solo a fine frase."""
    flusso = re.sub(r"\s+", " ", " ".join(righe)).strip()
    if not flusso:
        return []
    paras, cur, n = [], "", 0
    for f in _dividi_frasi(flusso):
        cur = (cur + " " + f).strip() if cur else f
        n += 1
        if len(cur) >= REFLOW_TARGET_CHARS and n >= 2:
            paras.append(cur); cur, n = "", 0
    if cur:
        paras.append(cur)
    return paras


# --- Lettura del testo in blocchi (comune a tutti i formati) --------------
def _blocchi(testo: str) -> list[tuple[str, str]]:
    """Divide il testo finale in blocchi ("titolo" | "punto" | "para", testo).

    La prosa viene accumulata e passata al reflow; un titolo o un elenco puntato
    interrompe il flusso (viene emesso cosi com'e'), poi la prosa riprende."""
    testo = (testo or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    blocchi: list[tuple[str, str]] = []
    prosa: list[str] = []

    def _svuota_prosa():
        blocchi.extend(("para", p) for p in _reflow(prosa))
        prosa.clear()

    for riga in (testo.split("\n") if testo else []):
        s = riga.strip()
        if not s:
            continue
        if _sembra_titolo(s):
            _svuota_prosa()
            blocchi.append(("titolo", s.rstrip(":")))
        elif s.startswith(("• ", "- ", "* ")):
            _svuota_prosa()
            blocchi.append(("punto", s.lstrip("•-* ").strip()))
        else:
            prosa.append(s)
    _svuota_prosa()
    return blocchi


def _sottotitolo() -> str:
    return f"Generato il {datetime.now():%d/%m/%Y %H:%M}"


def _e_domanda(frase: str) -> bool:
    """Domanda = la frase finisce con "?" (anche prima di virgolette/parentesi)."""
    return frase.rstrip().rstrip(")]\"'”’»").endswith("?")


# --- Word (.docx) ----------------------------------------------------------
def genera_docx(testo: str, path: Path, titolo: str, note: str) -> Path:
    """Scrive il documento Word e ritorna il percorso creato."""
    doc = Document()
    _aggiungi_copertina(doc, titolo, _sottotitolo(), note)
    for tipo, contenuto in _blocchi(testo):
        if tipo == "titolo":
            doc.add_paragraph(contenuto, style="Heading 2")
        elif tipo == "punto":
            doc.add_paragraph(contenuto, style="List Bullet")
        else:
            _aggiungi_paragrafo(doc, contenuto)
    # Salvataggio atomico: scrive un .docx temporaneo e poi lo rinomina, cosi un
    # kill a meta' (Annulla immediato) non lascia un documento corrotto.
    tmp, finale = util.percorso_atomico(path)
    doc.save(tmp)
    util.concludi_atomico(tmp, finale)
    return path


def _unisci(pezzi: list[tuple[str, str]]) -> str:
    """Unisce i blocchi gia' scritti: riga vuota tra un blocco e l'altro, ma i
    punti elenco consecutivi restano attaccati (un elenco unico, non spezzato)."""
    righe: list[str] = []
    prec = ""
    for tipo, riga in pezzi:
        if righe and not (tipo == "punto" and prec == "punto"):
            righe.append("")
        righe.append(riga)
        prec = tipo
    return "\n".join(righe) + "\n"


# --- Testo semplice (.txt) -------------------------------------------------
def genera_txt(testo: str, path: Path, titolo: str, note: str) -> Path:
    """Scrive il documento come testo semplice (UTF-8). Stessi paragrafi del
    Word, ma senza formattazione: i titoli stanno su una riga da soli e gli
    elenchi iniziano con "•"."""
    testa = [titolo, _sottotitolo()] + ([note] if note else [])
    sep = "=" * min(70, max(len(r) for r in testa))
    pezzi: list[tuple[str, str]] = [("testa", "\n".join(testa + [sep]))]
    for tipo, contenuto in _blocchi(testo):
        pezzi.append((tipo, "• " + contenuto if tipo == "punto" else contenuto))
    util.scrivi_testo(path, _unisci(pezzi))
    return path


# --- Markdown (.md) --------------------------------------------------------
# Caratteri che in Markdown cambiano la formattazione ovunque nella riga...
_MD_SPECIALI = re.compile(r"([\\`*_<])")
# ...e quelli che la cambiano solo A INIZIO riga (titolo, citazione, elenco).
_MD_INIZIO_RIGA = re.compile(r"^(?:[#>+=-]|\d+(?=[.)](?:\s|$)))")


def _md_testo(s: str) -> str:
    """Neutralizza i caratteri speciali dentro la riga (asterischi, trattini
    bassi, ...), cosi il testo della lezione resta testo e non diventa formattazione."""
    return _MD_SPECIALI.sub(r"\\\1", s)


def _md_riga(s: str) -> str:
    """Come `_md_testo`, ma per un testo che sta A INIZIO riga: anche "# ...",
    "> ...", "- ...", "2024. ..." non devono diventare titolo/citazione/elenco."""
    s = _md_testo(s)
    m = _MD_INIZIO_RIGA.match(s)
    if not m:
        return s
    if m.group(0)[0].isdigit():      # "2024. Quell'anno" -> "2024\. Quell'anno"
        return s[:m.end()] + "\\" + s[m.end():]
    return "\\" + s


def _md_paragrafo(testo: str) -> str:
    """Un paragrafo in Markdown: timestamp in **grassetto**, domande in *corsivo*
    (come nel Word, frase per frase)."""
    frasi_md: list[str] = []
    for frase in (_dividi_frasi(testo) or [testo]):
        is_q = _e_domanda(frase)
        pezzi: list[str] = []
        for i, part in enumerate(TIMESTAMP_RE.split(frase)):
            if not part:
                continue
            if i % 2:                                   # un timestamp
                pezzi.append(f"**[{part}]**")
                continue
            primo = not pezzi and not frasi_md          # il paragrafo inizia qui
            esc = _md_riga(part) if primo else _md_testo(part)
            nucleo = esc.strip()
            if is_q and nucleo:                         # corsivo senza inglobare gli spazi
                sx = esc[:len(esc) - len(esc.lstrip())]
                dx = esc[len(esc.rstrip()):]
                esc = f"{sx}*{nucleo}*{dx}"
            pezzi.append(esc)
        frasi_md.append("".join(pezzi))
    return " ".join(frasi_md)


def genera_md(testo: str, path: Path, titolo: str, note: str) -> Path:
    """Scrive il documento in Markdown (UTF-8): # titolo, ## titoli interni,
    - elenchi, timestamp in grassetto e domande in corsivo. Aperto in Obsidian,
    Notion, VS Code, GitHub... appare impaginato quasi come il Word."""
    testa = ["# " + _md_testo(titolo), "", f"*{_sottotitolo()}*"]
    if note:
        testa[-1] += "  "                       # due spazi in fondo = a capo in Markdown
        testa.append(f"*{_md_testo(note)}*")
    testa += ["", "---"]
    pezzi: list[tuple[str, str]] = [("testa", "\n".join(testa))]
    for tipo, contenuto in _blocchi(testo):
        if tipo == "titolo":
            pezzi.append((tipo, "## " + _md_testo(contenuto)))
        elif tipo == "punto":
            pezzi.append((tipo, "- " + _md_testo(contenuto)))
        else:
            pezzi.append((tipo, _md_paragrafo(contenuto)))
    util.scrivi_testo(path, _unisci(pezzi))
    return path


# --- Scelta dei formati ----------------------------------------------------
# Ordine fisso (anche dei file prodotti): Word, poi testo, poi Markdown.
GENERATORI = {"docx": genera_docx, "txt": genera_txt, "md": genera_md}
FORMATI = tuple(GENERATORI)
FORMATI_DEFAULT = ("docx",)
_SINONIMI = {"word": "docx", "doc": "docx", "markdown": "md", "text": "txt", "testo": "txt"}


def normalizza_formati(formati) -> list[str]:
    """Pulisce una scelta di formati (dalla UI, dalla CLI, da un file): tiene solo
    quelli conosciuti, senza doppioni, nell'ordine fisso. Vuota -> Word."""
    if isinstance(formati, str):
        formati = formati.replace(",", " ").split()
    scelti = set()
    for f in (formati or []):
        f = str(f).strip().lower().lstrip(".")
        scelti.add(_SINONIMI.get(f, f))
    return [f for f in FORMATI if f in scelti] or list(FORMATI_DEFAULT)


def percorso_documento(base: Path, formato: str) -> Path:
    """`base` + estensione. NON usa with_suffix: un nome con un punto
    ("Lez. 3_IT") perderebbe il pezzo dopo il punto."""
    base = Path(base)
    return base.parent / f"{base.name}.{formato}"


def genera(testo: str, base: Path, titolo: str, note: str, formati) -> list[Path]:
    """Scrive un documento per ogni formato scelto. `base` = percorso SENZA
    estensione (es. .../Lezione_IT). Ritorna i percorsi creati, in ordine."""
    return [GENERATORI[f](testo, percorso_documento(base, f), titolo, note)
            for f in normalizza_formati(formati)]
