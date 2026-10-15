# Command-line version (`transcribe`)

A no-GUI version of the lecture transcriber, for people comfortable with a
terminal (and the natural way to run it on Linux/servers). Same engine as the
desktop app: audio/video files or links (YouTube/Webex) → cleaned, translated
Word documents, via Google Gemini.

## Requirements

- **Python 3.12+**
- **ffmpeg** (and ffprobe) on your `PATH`:
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`
  - Windows: `choco install ffmpeg` (or download it and add it to `PATH`)
- A **Google Gemini API key** (free): https://aistudio.google.com/apikey

`yt-dlp` is installed automatically as a dependency (used for links).

## Install

```bash
pipx install git+https://github.com/GiorgioAlo/lecture-transcriber
```

(`pip install git+https://github.com/GiorgioAlo/lecture-transcriber` also works;
`pipx` just keeps it isolated.) This creates the `transcribe` command.

## Set your API key

```bash
export GOOGLE_API_KEY="your-key-here"        # Windows (cmd):  set GOOGLE_API_KEY=your-key-here
```

If you don't set it, `transcribe` asks for it at the prompt (input is hidden).

## Usage

```bash
# local file
transcribe lecture.mp4 --languages it en --out ./Documents

# YouTube link
transcribe "https://www.youtube.com/watch?v=XXXX" --out ./Documents

# Webex link (needs a cookies file, see below)
transcribe "https://org.webex.com/recordingservice/..." --cookies cookies.txt --out ./Documents

# quick test: only 5 minutes starting at minute 10
transcribe lecture.mp4 --start 10 --minutes 5

# use an existing transcript, just clean + translate
transcribe --text transcript.txt --name Zanero --languages it
```

The first positional argument can be **either a file or a link** (auto-detected).

### Options

| Option | Meaning |
|--------|---------|
| `source` | lecture file (mp4, m4a, …) **or** a link (YouTube/Webex) |
| `--text FILE` | use an existing `.txt` transcript (skip transcription) |
| `--name NAME` | lecture name (default: file name) |
| `--languages L …` | output languages, e.g. `it en` (default: `it en`) |
| `--course "…"` | course name (helps cleanup/translation) |
| `--cookies FILE` | `cookies.txt` for authenticated links (Webex) |
| `--password PW` | video password (some Webex recordings) |
| `--out DIR` | folder where the Word files are saved |
| `--start MIN` / `--minutes MIN` | transcribe only a clip |
| `--redo` | redo all phases even if already cached |

## Cookies (Webex)

Public YouTube videos don't need cookies. Webex "personal room" recordings do,
because they require being logged in. Export a `cookies.txt` from your browser
(e.g. a "Get cookies.txt" browser extension) while logged into Webex, then pass
it with `--cookies cookies.txt`.

## Notes

- Your audio/transcripts are sent to Google Gemini for processing (see the
  Privacy section in the README). Only transcribe recordings you are allowed to
  use.
- Intermediate files are cached, so re-running a lecture resumes where it left
  off; use `--redo` to force a full re-run.
