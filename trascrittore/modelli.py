"""Quali modelli Gemini usare: `modelli.json` letto da GitHub (punto 8, parte B).

Se Google ritira un modello, basta cambiare `modelli.json` nel repo (ramo main) e
tutti gli utenti passano al modello nuovo senza aspettare una release.

Ordine delle fonti: file su GitHub → ultima copia buona salvata in dir_dati
(`modelli_cache.json`: da sorgente dir_dati e' la cartella del repo, e il nome
diverso evita di sovrascrivere il `modelli.json` ufficiale) → valori di `config.py`.

Protezioni:
- ogni ruolo (asr / fallback / text) si valida da solo: un ruolo rotto tiene i
  valori di config.py, gli altri si applicano lo stesso;
- solo nomi `gemini-…` (minuscole, cifre, punti, trattini);
- un nome DIVERSO da quello di config.py si usa solo se Google conferma che esiste
  (`models.get`, gratis): un errore di battitura nel file non blocca nessuno.
  Attenzione: `models.get` non vede la quota (un modello a 0 RPD sul free tier
  "esiste" lo stesso) → prima di cambiare il file si guarda la pagina dei limiti.

I limiti (rpm/rpd) arrivano col modello: rpd del ruolo asr = contatore "ore
rimaste"; rpm decide quanti blocchi mandare in parallelo (con i valori di oggi
si ottengono esattamente i numeri di config.py: 12 blocchi audio, 4 di testo).

Non solleva mai: ogni intoppo lascia i valori di config.py.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable

from . import config, percorsi

NOME_FILE = "modelli.json"
_FILE_CACHE = "modelli_cache.json"
_NOME_VALIDO = re.compile(r"^gemini-[a-z0-9][a-z0-9.-]*$")

# ruolo nel file -> costante di config.py col nome del modello
RUOLI = {
    "asr": "ASR_MODEL",
    "fallback": "TRANSCRIBE_MODEL",
    "text": "TEXT_MODEL",
}

# Valori di config.py all'import: base da cui si riparte a ogni applicazione
# (cosi' applicare due volte, o un file diverso, non accumula modifiche).
_DEFAULT = {
    "ASR_MODEL": config.ASR_MODEL,
    "TRANSCRIBE_MODEL": config.TRANSCRIBE_MODEL,
    "TEXT_MODEL": config.TEXT_MODEL,
    "RPD_TRASCRIZIONE": config.RPD_TRASCRIZIONE,
    "ASR_WORKER": config.ASR_WORKER,
    "WORKER_PARALLELI": config.WORKER_PARALLELI,
}

_preparato = False


# --- regole pure -----------------------------------------------------------
def worker_asr(rpm: int) -> int:
    """Blocchi audio in parallelo dato l'RPM del modello ASR: un po' sotto l'RPM
    (margine per upload e ritentativi), mai oltre il massimo di config.py.
    RPM 15 → 12 (come oggi), RPM 5 → 2."""
    return max(1, min(_DEFAULT["ASR_WORKER"], rpm - 3))


def worker_testo(rpm: int) -> int:
    """Blocchi di testo in parallelo dato l'RPM del modello di testo (chiamate
    piu' lunghe e pesanti in token → un terzo dell'RPM). RPM 15 → 4 (come oggi), RPM 5 → 1."""
    return max(1, min(_DEFAULT["WORKER_PARALLELI"], rpm // 3))


def _intero_positivo(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        return None
    return v


def valida(dati) -> dict[str, dict]:
    """Tiene solo i ruoli ben fatti: {ruolo: {"model", "rpm"?, "rpd"?}}.
    rpm/rpd sono facoltativi (se mancano o sono strani valgono quelli di config.py)."""
    out: dict[str, dict] = {}
    if not isinstance(dati, dict):
        return out
    for ruolo in RUOLI:
        voce = dati.get(ruolo)
        if not isinstance(voce, dict):
            continue
        nome = voce.get("model")
        if not isinstance(nome, str) or not _NOME_VALIDO.match(nome):
            continue
        pulita: dict = {"model": nome}
        for lim in ("rpm", "rpd"):
            v = _intero_positivo(voce.get(lim))
            if v is not None:
                pulita[lim] = v
        out[ruolo] = pulita
    return out


def ripristina() -> None:
    """Rimette in config i valori originali di config.py."""
    for k, v in _DEFAULT.items():
        setattr(config, k, v)


def _esiste(client, nome: str) -> bool:
    try:
        client.models.get(model=nome)
        return True
    except Exception:
        return False


def applica(ruoli: dict[str, dict], client=None,
            log: Callable[[str], None] = lambda _m: None) -> None:
    """Applica i ruoli validati a `config`, partendo sempre dai valori originali.

    Un nome diverso da config.py si accetta solo se `client` conferma che esiste;
    se viene scartato, quel ruolo tiene nome E limiti di config.py. Senza client
    (app grafica senza chiave: le servono solo i limiti per il contatore) il nome
    si accetta cosi' com'e': chi trascrive davvero ha sempre il client."""
    ripristina()
    for ruolo, voce in ruoli.items():
        attr = RUOLI[ruolo]
        nome = voce["model"]
        if nome != _DEFAULT[attr]:
            if client is not None and not _esiste(client, nome):
                log(f"⚠️  modelli.json indica {nome} per '{ruolo}', ma Google non lo conosce: "
                    f"resto su {_DEFAULT[attr]}")
                continue
            log(f"🔁 uso {nome} al posto di {_DEFAULT[attr]} (indicato in modelli.json)")
        setattr(config, attr, nome)
        if ruolo == "asr":
            if "rpd" in voce:
                config.RPD_TRASCRIZIONE = voce["rpd"]
            if "rpm" in voce:
                config.ASR_WORKER = worker_asr(voce["rpm"])
        elif ruolo == "text" and "rpm" in voce:
            config.WORKER_PARALLELI = worker_testo(voce["rpm"])


# --- rete e cache (isolate) ------------------------------------------------
def _url() -> str | None:
    owner = (config.GITHUB_OWNER or "").strip()
    repo = (config.GITHUB_REPO or "").strip()
    if not owner or not repo:
        return None
    return f"https://raw.githubusercontent.com/{owner}/{repo}/main/{NOME_FILE}"


def _scarica() -> dict | None:
    url = _url()
    if not url:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Trascrivi-Lezioni"})
    with urllib.request.urlopen(req, timeout=config.TIMEOUT_CHECK_UPDATE_S) as resp:  # noqa: S310 (host fisso GitHub)
        return json.loads(resp.read().decode("utf-8"))


def _leggi_cache() -> dict | None:
    try:
        return json.loads((percorsi.dir_dati() / _FILE_CACHE).read_text("utf-8"))
    except Exception:
        return None


def _scrivi_cache(dati: dict) -> None:
    try:
        base = percorsi.dir_dati()
        base.mkdir(parents=True, exist_ok=True)
        (base / _FILE_CACHE).write_text(json.dumps(dati, indent=1), "utf-8")
    except Exception:
        pass


# --- orchestratore -----------------------------------------------------------
def prepara(client=None, log: Callable[[str], None] = lambda _m: None, forza: bool = False) -> None:
    """Legge i modelli (GitHub → cache → config.py) e li applica. Una volta per
    processo (l'app grafica lancia un processo nuovo a ogni coda, quindi la
    rilegge da sola a ogni «Riprova»); `invalida()` o `forza` la fanno rileggere.
    Non solleva mai."""
    global _preparato
    if _preparato and not forza:
        return
    try:
        ruoli: dict[str, dict] = {}
        try:
            remoto = _scarica()
        except Exception:
            remoto = None
        if remoto is not None:
            ruoli = valida(remoto)
            if ruoli:
                _scrivi_cache(remoto)
        if not ruoli:
            ruoli = valida(_leggi_cache())
        applica(ruoli, client, log)
    except Exception:
        ripristina()
    _preparato = True


def invalida() -> None:
    """La prossima `prepara()` rilegge il file (dopo un modello ritirato)."""
    global _preparato
    _preparato = False
