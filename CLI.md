# Command-line version (`transcribe`)

A no-GUI version of the lecture transcriber, for people comfortable with a
terminal (and the natural way to run it on Linux/servers). Same engine as the
desktop app: audio/video files or links (YouTube/Webex) → cleaned, translated
documents (Word, plain text and/or Markdown), via Google Gemini.

## Requirements

- **Python 3.11+**
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

You give `transcribe` **one or more lectures**. Each lecture is either:
- a **file path** on your computer (mp4, m4a, mp3, wav, mkv, …), or
- a **link** to download (YouTube / Webex).

You can mix files and links freely; they are processed one after another and all
the documents go into the same `--out` folder. Put each path/link in
**double quotes** if it contains spaces.

```bash
# one local file
transcribe "C:\Users\me\Downloads\Lecture 1.mp4" --out "C:\Users\me\Desktop\Transcriptions"

# one YouTube link
transcribe "https://www.youtube.com/watch?v=XXXX" --out "C:\Users\me\Desktop\Transcriptions"

# SEVERAL lectures at once (files and links mixed)
transcribe "https://polimi.webex.com/..." "C:\Lectures\Zanero 1.mp4" "C:\Lectures\Zanero 2.mp4" --cookies "C:\Users\me\Downloads\cookies.txt" --out "C:\Users\me\Desktop\Transcriptions"

# choose output languages (default is Italian + English)
transcribe lecture.mp4 --languages it en fr --out ./transcriptions

# choose output formats (default is Word only)
transcribe lecture.mp4 --formats docx txt md --out ./transcriptions

# quick test: only 5 minutes starting at minute 10
transcribe lecture.mp4 --start 10 --minutes 5

# use an existing transcript, just clean + translate (one lecture only)
transcribe --text transcript.txt --name Zanero --languages it
```

On macOS/Linux a path looks like `/home/me/Lectures/lecture.mp4` or
`~/Lectures/lecture.mp4`, and an output folder like `--out ~/Transcriptions`.
The output folder is **created automatically** if it doesn't exist.

### Options

| Option | Meaning |
|--------|---------|
| `SOURCE …` | one or more lectures; each is a **file path** or a **link** (YouTube/Webex) |
| `--text FILE` | use an existing `.txt` transcript (skip transcription; one lecture only) |
| `--name NAME` | lecture name (single lecture only; default: file name) |
| `--languages L …` | output languages, e.g. `it en` (default: `it en`) |
| `--formats F …` | output formats: `docx` (Word), `txt` (plain text), `md` (Markdown) (default: `docx`) |
| `--course "…"` | course name (helps cleanup/translation) |
| `--cookies FILE` | `cookies.txt` for authenticated links (Webex); applies to all links |
| `--password PW` | video password (some Webex recordings); applies to all links |
| `--out DIR` | folder where the documents are saved (created if missing) |
| `--start MIN` / `--minutes MIN` | transcribe only a clip (applies to all) |
| `--redo` | redo all phases even if already cached |

If one lecture in a batch fails, `transcribe` reports it and **keeps going** with
the next ones; at the end it prints how many completed.

## Cookies (Webex)

Public YouTube videos don't need cookies. Webex "personal room" recordings do,
because they require being logged in. Export a `cookies.txt` from your browser
(e.g. a "Get cookies.txt" browser extension) while logged into Webex, then pass
it with `--cookies cookies.txt`.

**Without cookies: the direct link.** Open the recording in the browser (logged in),
press F12 → **Network** tab, start the video and type `m3u8` in the filter. Right-click
the `hls.m3u8` request → Copy → Copy URL, and pass that URL to `transcribe` (no
`--cookies` needed). The link carries its own access, so it **expires** (use it right
away) and **must not be shared**. The documents are named `Webex <recording number>`,
since the link has no title.

## Notes

- Your audio/transcripts are sent to Google Gemini for processing (see the
  Privacy section in the README). Only transcribe recordings you are allowed to
  use.
- Intermediate files are cached, so re-running a lecture resumes where it left
  off; use `--redo` to force a full re-run.
