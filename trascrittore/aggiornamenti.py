"""Controllo aggiornamenti dell'app (Step 3 — "controlla e avvisa").

Strategia scelta per un onefile .exe NON firmato dato ad amici non tecnici:
NON si auto-installa (un exe in esecuzione e' bloccato da Windows, e SmartScreen
avvisa comunque su ogni .exe scaricato). Si CONTROLLA se su GitHub Releases c'e'
una versione piu' nuova e, se si', si avvisa dentro l'app con un pulsante che
apre la pagina della Release (changelog + download). L'utente scarica e rimpiazza
il file a mano.

Regole d'oro:
- MAI bloccare l'avvio: il controllo gira in un thread di sfondo, con timeout
  corto, e QUALSIASI errore (niente rete, GitHub giu', repo non configurato) e'
  un no-op silenzioso. Non deve mai disturbare l'amico ne' rallentare l'apertura.
- Al massimo un controllo al giorno (throttle su un piccolo json in dir_dati()),
  cosi' non si martella GitHub e non si ri-assilla con lo stesso avviso.

La RETE e' isolata in `_ultima_release_github()`; tutto il resto (confronto
semver, throttle, costruzione URL) e' puro e testato offline.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from urllib.parse import quote

from . import config, percorsi

_FILE_STATO = "aggiornamenti.json"   # in dir_dati(): {"ultimo_controllo": "YYYY-MM-DD"}


# --- confronto versioni (puro) --------------------------------------------
def versione_tupla(s: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3). Parti non numeriche o il suffisso
    di pre-release vengono ignorati; parti mancanti valgono 0. Stringa illeggibile
    -> (0,) (cosi' non viene mai scambiata per piu' recente di una versione vera)."""
    s = (s or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parti: list[int] = []
    for pezzo in s.split("."):
        m = re.match(r"\d+", pezzo)
        if not m:
            break
        parti.append(int(m.group()))
    return tuple(parti) if parti else (0,)


def e_piu_recente(candidata: str, corrente: str) -> bool:
    """True se `candidata` (tag remoto) e' una versione STRETTAMENTE piu' nuova
    di `corrente` (quella installata)."""
    return versione_tupla(candidata) > versione_tupla(corrente)


# --- throttle (puro) -------------------------------------------------------
def _deve_controllare(stato: dict, oggi: str) -> bool:
    """True se oggi non e' ancora stato fatto un controllo."""
    return stato.get("ultimo_controllo") != oggi


def _leggi_stato() -> dict:
    try:
        return json.loads((percorsi.dir_dati() / _FILE_STATO).read_text("utf-8"))
    except Exception:
        return {}


def _scrivi_stato(stato: dict) -> None:
    try:
        base = percorsi.dir_dati()
        base.mkdir(parents=True, exist_ok=True)
        (base / _FILE_STATO).write_text(json.dumps(stato), "utf-8")
    except Exception:
        pass


# --- URL del form di segnalazione (puro) -----------------------------------
def url_segnalazione(versione: str | None = None) -> str | None:
    """URL del Google Form per 'Segnala un problema', con la versione dell'app
    pre-compilata se e' stato configurato il campo. None se il form non e'
    configurato (il pulsante allora non va mostrato)."""
    base = (config.URL_FORM_SEGNALAZIONE or "").strip()
    if not base:
        return None
    campo = (config.FORM_CAMPO_VERSIONE or "").strip()
    if campo:
        sep = "&" if "?" in base else "?"
        ver = versione if versione is not None else config.VERSION
        base += f"{sep}usp=pp_url&{campo}={quote(ver)}"
    return base


# --- rete (isolata) --------------------------------------------------------
def _ultima_release_github(owner: str, repo: str, timeout: float) -> dict | None:
    """Interroga l'API GitHub Releases. Ritorna {'tag_name','html_url'} o None.
    `/releases/latest` salta gia' draft e pre-release: torna l'ultima stabile."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Trascrivi-Lezioni",   # GitHub richiede uno User-Agent
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (host fisso GitHub)
        dati = json.loads(resp.read().decode("utf-8"))
    tag = dati.get("tag_name")
    if not tag:
        return None
    return {"tag_name": tag, "html_url": dati.get("html_url") or ""}


# --- orchestratore ---------------------------------------------------------
def controlla(force: bool = False) -> dict | None:
    """Da chiamare in un THREAD di sfondo. Ritorna {'versione','url'} se c'e' un
    aggiornamento da proporre, altrimenti None. Non solleva mai: ogni intoppo
    (rete, parsing, repo non configurato) e' None.

    - Repo non configurato (costanti vuote) -> None (feature dormiente).
    - Throttle: salvo force, al massimo un controllo di rete al giorno.
    """
    owner = (config.GITHUB_OWNER or "").strip()
    repo = (config.GITHUB_REPO or "").strip()
    if not owner or not repo:
        return None

    oggi = date.today().isoformat()
    stato = _leggi_stato()
    if not force and not _deve_controllare(stato, oggi):
        return None

    try:
        rel = _ultima_release_github(owner, repo, config.TIMEOUT_CHECK_UPDATE_S)
    except Exception:
        return None   # niente rete / GitHub giu' / 404: silenzio
    # Segno il controllo come fatto SOLO se e' andato a buon fine, cosi' un errore
    # di rete oggi non blocca il nuovo tentativo di domani (ne' lo ripete ogni avvio).
    stato["ultimo_controllo"] = oggi
    _scrivi_stato(stato)

    if rel and e_piu_recente(rel["tag_name"], config.VERSION):
        return {"versione": rel["tag_name"].lstrip("vV"), "url": rel["html_url"]}
    return None


def controlla_manuale() -> dict:
    """Check su richiesta (pulsante 'Cerca aggiornamenti'): come controlla(force=True)
    ma DISTINGUE gli esiti, cosi' la UI puo' dire qualcosa in ogni caso:
      {'stato': 'nuovo', 'versione', 'url'}  -> c'e' una versione piu' nuova
      {'stato': 'aggiornato'}                -> gia' all'ultima versione
      {'stato': 'errore'}                    -> rete giu' / repo non configurato / GitHub ko
    Non solleva mai."""
    owner = (config.GITHUB_OWNER or "").strip()
    repo = (config.GITHUB_REPO or "").strip()
    if not owner or not repo:
        return {"stato": "errore"}
    try:
        rel = _ultima_release_github(owner, repo, config.TIMEOUT_CHECK_UPDATE_S)
    except Exception:
        return {"stato": "errore"}
    if not rel:
        return {"stato": "errore"}
    stato = _leggi_stato()                      # un check riuscito aggiorna il throttle
    stato["ultimo_controllo"] = date.today().isoformat()
    _scrivi_stato(stato)
    if e_piu_recente(rel["tag_name"], config.VERSION):
        return {"stato": "nuovo", "versione": rel["tag_name"].lstrip("vV"), "url": rel["html_url"]}
    return {"stato": "aggiornato"}
