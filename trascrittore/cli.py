"""Command-line interface for the transcription pipeline (no GUI).

The engine already supports local files, links (YouTube/Webex) and cookies; this
CLI just exposes them. You can pass several lectures at once: each one is either
a file path or a link, and they are processed one after another.

The API key is read from the GOOGLE_API_KEY environment variable (recommended for
terminal/headless use); if missing, it is asked at the prompt (not echoed).

Examples:
    transcribe lecture.mp4 --languages it en --out ./transcriptions
    transcribe "https://www.youtube.com/watch?v=XXXX" --out ./transcriptions
    transcribe lec1.mp4 "https://youtu.be/XXXX" lec2.mp4 --out ./transcriptions
    transcribe "https://org.webex.com/..." --cookies cookies.txt --out ./transcriptions
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


def _esegui_lezione(job: Job, key: str, out_dir: Path | None, redo: bool) -> tuple[bool, list[Path]]:
    """Runs one lecture. Returns (fully_completed, saved_document_paths)."""
    ris = esegui(job, key, ReporterConsole(config.FASI), OUT_BASE, rifai=redo)
    documenti = [Path(d) for d in ris.documenti]
    if out_dir and documenti:
        out_dir.mkdir(parents=True, exist_ok=True)
        copiati = []
        for d in documenti:
            dest = out_dir / d.name
            shutil.copy2(d, dest)
            copiati.append(dest)
        documenti = copiati
    return ris.completo, documenti


def main(argv: list[str] | None = None) -> int:
    # The Windows console may be cp1252 and crash on emojis: force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        prog="transcribe",
        description="Turn one or more lectures (files or links) into cleaned, translated Word documents.",
    )
    ap.add_argument("sources", nargs="*", metavar="SOURCE",
                    help="one or more lectures; each is a FILE PATH (mp4, m4a, ...) OR a LINK (YouTube/Webex)")
    ap.add_argument("--text", help="use an existing .txt transcript (skips transcription; one lecture only)")
    ap.add_argument("--name", help="lecture name (single lecture only; default: file name)")
    ap.add_argument("--languages", nargs="+", default=["it", "en"],
                    choices=list(languages.LINGUE.keys()), metavar="LANG",
                    help="output document languages (default: it en)")
    ap.add_argument("--course", default="", help='course name, e.g. "Computer Security"')
    ap.add_argument("--cookies", help="cookies.txt file (needed for Webex links); applies to all links")
    ap.add_argument("--password", help="video password (some Webex recordings); applies to all links")
    ap.add_argument("--out", help="folder where the Word documents are saved (created if missing)")
    ap.add_argument("--start", type=float, default=0, metavar="MIN", help="start minute (applies to all)")
    ap.add_argument("--minutes", type=float, default=None, metavar="MIN", help="how many minutes to use (applies to all)")
    ap.add_argument("--redo", action="store_true", help="redo all phases even if already cached")
    args = ap.parse_args(argv)

    if args.text and args.sources:
        ap.error("pass either files/links OR --text, not both")
    if not args.sources and not args.text:
        ap.error("pass at least one file or link (or --text)")
    if args.name and len(args.sources) > 1:
        ap.error("--name can be used with a single lecture only")

    # Local inputs that must exist up front (the transcript and the cookies file).
    for path, label in ((args.text, "--text file"), (args.cookies, "--cookies file")):
        if path and not Path(path).exists():
            print(f"[x] Cannot find {label}: {path}", file=sys.stderr)
            return 1

    key = os.environ.get("GOOGLE_API_KEY", "").strip() or \
        getpass.getpass("Paste your Gemini API key (hidden): ").strip()
    if not key:
        print("[x] No API key provided (set GOOGLE_API_KEY or paste it).", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else None
    shared = dict(
        lingue_output=args.languages,
        corso=args.course,
        cookies=args.cookies,
        password=args.password,
        inizio=args.start,
        minuti=args.minutes,
    )

    # Build the list of lectures to run: either the --text one, or one per source.
    lavori: list[tuple[str, Job | None]] = []
    if args.text:
        name = args.name or Path(args.text).stem
        lavori.append((name, Job(nome=name, testo=Path(args.text), **shared)))
    else:
        for src in args.sources:
            is_link = _is_url(src)
            if not is_link and not Path(src).exists():
                lavori.append((src, None))   # missing file: reported and skipped in the loop
                continue
            if args.name and len(args.sources) == 1:
                name = args.name
            else:
                name = "Lecture" if is_link else Path(src).stem
            job = Job(
                sorgente=None if is_link else Path(src),
                url=src if is_link else None,
                nome=name,
                **shared,
            )
            lavori.append((name, job))

    totale = len(lavori)
    completate = 0
    falliti = 0
    tutti_doc: list[Path] = []
    t0 = time.time()

    for i, (name, job) in enumerate(lavori, 1):
        etichetta = f"[{i}/{totale}] {name}"
        print(f"\n{'=' * 60}\n{etichetta}\n{'=' * 60}")
        if job is None:
            print(f"[x] skipped: file not found ({name})", file=sys.stderr)
            falliti += 1
            continue
        try:
            completo, documenti = _esegui_lezione(job, key, out_dir, args.redo)
        except ErrorePipeline as e:
            print(f"[x] {e}", file=sys.stderr)
            falliti += 1
            continue
        tutti_doc.extend(documenti)
        if completo:
            completate += 1
        else:
            print("[!] done WITH MISSING BLOCKS (run again to retry them)")
        for d in documenti:
            print(f"[doc] {d}")

    print("\n" + "=" * 60)
    riepilogo = f"[done] {completate}/{totale} fully completed"
    if falliti:
        riepilogo += f", {falliti} failed/skipped"
    print(riepilogo)
    print(f"[time] total: {(time.time() - t0) / 60:.1f} min")
    if out_dir and tutti_doc:
        print(f"[out] documents saved in: {out_dir}")
    print("=" * 60)
    return 0 if falliti == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
