"""Come la pipeline comunica col mondo esterno (UI o terminale).

La pipeline non sa NIENTE di pywebview o di print: parla solo con un `Reporter`.
Chi la usa passa il Reporter giusto:
  - l'app desktop passa un reporter che aggiorna la finestra (vedi app.py);
  - la riga di comando usa `ReporterConsole` che stampa a schermo.

Il Reporter serve anche per l'ANNULLO: la pipeline chiama `interrotto()` nei
punti sicuri; se torna True, si ferma sollevando `Interrotto`.
"""
from __future__ import annotations


class Reporter:
    """Reporter di base: non fa niente. Serve come interfaccia da estendere."""

    def fase(self, indice: int, stato: str) -> None:
        """Una fase cambia stato. `stato`: 'attiva' | 'fatta'."""

    def avanzamento(self, percent: float) -> None:
        """Percentuale complessiva 0..100."""

    def log(self, messaggio: str) -> None:
        """Messaggio di dettaglio (facoltativo da mostrare)."""

    def interrotto(self) -> bool:
        """True se l'utente ha chiesto di annullare."""
        return False

    def richiesta_trascrizione(self) -> None:
        """Un blocco audio e' appena stato trascritto via API (1 richiesta).

        Serve a contare il consumo della quota giornaliera (RPD) per stimare
        quante lezioni restano oggi. Di base: non fa niente (la CLI non conta)."""


class ReporterConsole(Reporter):
    """Reporter per la riga di comando: stampa fasi, avanzamento e log."""

    def __init__(self, fasi: list[str]):
        self._fasi = fasi

    def fase(self, indice: int, stato: str) -> None:
        nome = self._fasi[indice] if 0 <= indice < len(self._fasi) else f"fase {indice}"
        icona = "✅" if stato == "fatta" else "▶️"
        print(f"{icona}  {nome}")

    def avanzamento(self, percent: float) -> None:
        print(f"\r   {percent:5.1f}%", end="", flush=True)

    def log(self, messaggio: str) -> None:
        print(f"   {messaggio}")
