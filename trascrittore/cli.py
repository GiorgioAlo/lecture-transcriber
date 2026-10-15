"""Riga di comando per la pipeline (utile per test senza l'interfaccia grafica).

Esempi (Anaconda Prompt, env "trascrittore"):
    python -m trascrittore.cli lezione.mp4 --lingue it en --corso "Computer Security"
    python -m trascrittore.cli lezione.mp4 --inizio 10 --minuti 5        # solo uno spezzone
    python -m trascrittore.cli --testo trascrizione.txt --nome Zanero --lingue it
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

from . import config, languages, percorsi
from .errors import ErrorePipeline
from .pipeline import Job, esegui
from .progress import ReporterConsole

OUT_BASE = percorsi.dir_cache()   # in sviluppo = cache/ del repo; da .exe = %LOCALAPPDATA% (vedi percorsi.py)


def main(argv: list[str] | None = None) -> int:
    # La console Windows puo essere in cp1252 e andare in crash sulle emoji: forziamo UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Lezione → trascrizione + pulizia/traduzione → Word")
    ap.add_argument("input", nargs="?", help="video o audio della lezione (mp4, m4a, ...)")
    ap.add_argument("--testo", help="usa una trascrizione .txt gia pronta (salta la trascrizione)")
    ap.add_argument("--nome", help="nome della lezione (default: nome del file)")
    ap.add_argument("--lingue", nargs="+", default=["it", "en"],
                    choices=list(languages.LINGUE.keys()),
                    help="lingue dei documenti (default: it en)")
    ap.add_argument("--corso", default="", help='nome del corso, es. "Computer Security"')
    ap.add_argument("--inizio", type=float, default=0, help="da che minuto partire")
    ap.add_argument("--minuti", type=float, default=None, help="quanti minuti usare")
    ap.add_argument("--rifai", action="store_true", help="rifa tutte le fasi anche se gia presenti")
    args = ap.parse_args(argv)

    if not args.input and not args.testo:
        ap.error("serve un file audio/video oppure --testo")
    sorgente = Path(args.testo or args.input)
    if not sorgente.exists():
        print(f"❌ Non trovo {sorgente}", file=sys.stderr)
        return 1

    chiave = os.environ.get("GOOGLE_API_KEY", "").strip() or \
        getpass.getpass("🔑 Incolla la chiave API di Gemini (non verra mostrata): ").strip()

    nome = args.nome or sorgente.stem
    job = Job(
        sorgente=Path(args.input) if args.input else sorgente,
        nome=nome,
        lingue_output=args.lingue,
        corso=args.corso,
        inizio=args.inizio,
        minuti=args.minuti,
        testo=Path(args.testo) if args.testo else None,
    )

    print(f"📚 {nome}  →  lingue: {', '.join(args.lingue)}")
    t0 = time.time()
    try:
        ris = esegui(job, chiave, ReporterConsole(config.FASI), OUT_BASE, rifai=args.rifai)
    except ErrorePipeline as e:
        print(f"\n❌ {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("✅ Completata" if ris.completo else "⚠️  Completata CON BLOCCHI MANCANTI (rilancia per riprovarli)")
    print(f"⏱️  totale: {(time.time() - t0) / 60:.1f} min")
    for d in ris.documenti:
        print(f"📄 {d}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
