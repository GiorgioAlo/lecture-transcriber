"""Gestione della chiave API di Google Gemini.

La chiave NON sta nel codice ne' in un file: vive nel Gestore Credenziali di
Windows (tramite `keyring`). Qui ci sono leggi/salva/elimina + una verifica
leggera che la chiave sia valida (chiamata ai metadati, non consuma quota di
trascrizione).
"""
from __future__ import annotations

import keyring

SERVICE = "TrascriviLezioni"   # voce nel Gestore Credenziali di Windows
USER = "gemini"                # app a utente singolo: un nome fisso basta


def leggi() -> str:
    """La chiave salvata, o stringa vuota se non c'e'."""
    try:
        return (keyring.get_password(SERVICE, USER) or "").strip()
    except Exception:
        return ""


def salva(chiave: str) -> None:
    keyring.set_password(SERVICE, USER, (chiave or "").strip())


def elimina() -> None:
    try:
        keyring.delete_password(SERVICE, USER)
    except Exception:
        pass  # gia' assente: va bene lo stesso


def valida(chiave: str) -> tuple[bool, str]:
    """Verifica che la chiave funzioni davvero. Ritorna (ok, messaggio_errore).

    Usa `models.list()`: e' una chiamata leggera ai metadati (~0,3s) che NON
    intacca la quota di trascrizione. Distingue "chiave sbagliata" da "non
    riesco a verificare" (es. senza internet)."""
    chiave = (chiave or "").strip()
    if not chiave:
        return False, "Incolla una chiave."
    try:
        from google import genai
        client = genai.Client(api_key=chiave)
        next(iter(client.models.list()), None)   # forza la chiamata
        return True, ""
    except Exception as e:
        code = getattr(e, "code", None)
        msg = str(e).lower()
        if code in (400, 401, 403) or "api key not valid" in msg or "api_key_invalid" in msg:
            return False, "La chiave non è valida. Controlla di averla copiata per intero."
        return False, "Non riesco a verificare la chiave adesso (controlla la connessione a internet)."


def anteprima(chiave: str) -> str:
    """Versione mascherata per mostrarla senza rivelarla tutta (es. 'AIza…wXyZ')."""
    chiave = (chiave or "").strip()
    if not chiave:
        return ""
    if len(chiave) <= 8:
        return "•" * len(chiave)
    return chiave[:4] + "…" + chiave[-4:]
