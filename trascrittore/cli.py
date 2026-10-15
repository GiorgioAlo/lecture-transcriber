"""Command-line interface for the transcription pipeline (no GUI).

The engine already supports local files, links (YouTube/Webex) and cookies; this
CLI just exposes them. The API key is read from the GOOGLE_API_KEY environment
variable (recommended for terminal/headless use); if missing, it is asked at the
prompt (not echoed).

Examples:
    transcribe lecture.mp4 --languages it en --out ./Documents
    transcribe "https://www.youtube.com/watch?v=XXXX" --out ./Documents
    transcribe "https://org.webex.com/..." --cookies cookies.txt --out ./Documents
    transcribe lecture.mp4 --start 10 --minutes 5          # quick test on a clip
    transcribe --text transcript.txt --name Zanero --languages it
"""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
import time
from pathlib import Path

from . import config, languages, percorsi
from .errors import ErrorePipeline
from .pipeline import Job, esegui
from .progress import ReporterConsole

OUT_BASE = percorsi.dir_cache()   # internal work/cache dir (intermediate files)


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def main(argv: list[str] | None = None) -> int:
    # The Windows console may be cp1252 and crash on emojis: force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        prog="transcribe",
        description="Lecture (file or link) -> transcription + cleanup/translation -> Word documents.",
    )
    ap.add_argument("source", nargs="?",
                    help="lecture audio/video file (mp4, m4a, ...) OR a link (YouTube/Webex)")
    ap.add_argument("--text", help="use an existing .txt transcript (skips transcription)")
    ap.add_argument("--name", help="lecture name (default: file name / link title)")
    ap.add_argument("--languages", nargs="+", default=["it", "en"],
                    choices=list(languages.LINGUE.keys()), metavar="LANG",
                    help="output document languages (default: it en)")
    ap.add_argument("--course", default="", help='course name, e.g. "Computer Security"')
    ap.add_argument("--cookies", help="cookies.txt file (needed for Webex links)")
    ap.add_argument("--password", help="video password (some Webex recordings)")
    ap.add_argument("--out", help="folder where the Word documents are saved")
    ap.add_argument("--start", type=float, default=0, metavar="MIN", help="start minute")
    ap.add_argument("--minutes", type=float, default=None, metavar="MIN", help="how many minutes to use")
    ap.add_argument("--redo", action="store_true", help="redo all phases even if already cached")
    args = ap.parse_args(argv)

    if not args.source and not args.text:
        ap.error("a source file/link or --text is required")

    is_link = bool(args.source) and _is_url(args.source)

    # Resolve the local inputs that must exist on disk (file source, text, cookies).
    for path, label in ((None if is_link else args.source, "source"),
                         (args.text, "--text file"),
                         (args.cookies, "--cookies file")):
        if path and not Path(path).exists():
            print(f"[x] Cannot find {label}: {path}", file=sys.stderr)
            return 1

    key = os.environ.get("GOOGLE_API_KEY", "").strip() or \
        getpass.getpass("Paste your Gemini API key (hidden): ").strip()
    if not key:
        print("[x] No API key provided (set GOOGLE_API_KEY or paste it).", file=sys.stderr)
        return 1

    if args.name:
        name = args.name
    elif is_link:
        name = "Lecture"
    else:
        name = Path(args.text or args.source).stem

    job = Job(
        sorgente=None if is_link else (Path(args.source) if args.source else None),
        url=args.source if is_link else None,
        nome=name,
        lingue_output=args.languages,
        corso=args.course,
        cookies=args.cookies,
        password=args.password,
        inizio=args.start,
        minuti=args.minutes,
        testo=Path(args.text) if args.text else None,
    )

    print(f"[lecture] {name}  ->  languages: {', '.join(args.languages)}")
    t0 = time.time()
    try:
        ris = esegui(job, key, ReporterConsole(config.FASI), OUT_BASE, rifai=args.redo)
    except ErrorePipeline as e:
        print(f"\n[x] {e}", file=sys.stderr)
        return 1

    # Copy the produced documents into the chosen output folder.
    documenti = list(ris.documenti)
    if args.out and documenti:
        out_dir = Path(args.out)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            copiati = []
            for d in documenti:
                dest = out_dir / Path(d).name
                shutil.copy2(d, dest)
                copiati.append(dest)
            documenti = copiati
        except OSError as e:
            print(f"\n[!] Could not save into {out_dir}: {e}", file=sys.stderr)

    print("\n" + "=" * 60)
    print("[ok] Done" if ris.completo else "[!] Done WITH MISSING BLOCKS (run again to retry them)")
    print(f"[time] total: {(time.time() - t0) / 60:.1f} min")
    for d in documenti:
        print(f"[doc] {d}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
