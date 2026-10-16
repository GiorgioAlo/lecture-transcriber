# Trascrivi Lezioni (lecture-transcriber)

Turn your **lectures** — audio/video files, or **links** (YouTube / Webex) — into clean,
nicely formatted, translated **Word documents**, automatically. Powered by Google Gemini.

Made to be simple enough for non-technical people. Pick one of the three ways below.

---

## ⬇️ Get the app (easiest for most people)

**[➡️ Go to the Downloads page (Releases)](https://github.com/GiorgioAlo/lecture-transcriber/releases/latest)**

On that page scroll down to **“Assets”** and download the file for your computer:

### 🪟 Windows
1. Download **`Trascrivi.Lezioni.exe`** from the Assets list.
2. Double-click it to open. (It's a single file — no installation.)
3. The first time, Windows may show a blue box *“Windows protected your PC”*. This happens
   because the app isn't signed (it's a free hobby app, not a security problem). Click
   **More info → Run anyway**.

### 🍎 Mac (Apple Silicon — M1/M2/M3…)
1. Download **`Trascrivi-Lezioni-macOS.dmg`** from the Assets list.
2. Open it and **drag the app into the Applications folder**.
3. Open it from Applications. If macOS says it's from an *unidentified developer*, go to
   **System Settings → Privacy & Security**, scroll down and click **Open Anyway**, then
   reopen the app. (Same reason as Windows: the app isn't signed.)

> After opening it the first time, paste your free Google Gemini key (see **First run** below)
> and you're ready.

---

## ☁️ Or run it in Google Colab (nothing to install, any computer)

The simplest option if you don't want to download anything — it runs in your browser.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/GiorgioAlo/lecture-transcriber/blob/main/notebooks/Trascrivi_Lezioni_Colab.ipynb)

Click the badge, then just follow the instructions written at the top of the notebook
(get a key, upload your lectures or paste links, press play). No coding needed.

---

## 💻 Or use the command line (for techies / Linux / servers)

A no-GUI `transcribe` command, installable with `pipx`/`pip` — see **[CLI.md](CLI.md)**.

---

## 🔑 First run — get your free Google Gemini key
The app (and Colab) need a free personal key from Google:
1. Open **https://aistudio.google.com/apikey** and sign in with your Google account.
2. Click **Create API key**, give it a name, pick/create a project.
3. **Copy** the key and paste it into the app when it asks (you do this only once).

## ✍️ How to use it
1. Add your lectures: choose a **file** on your computer, or paste a **link** (YouTube/Webex).
2. Choose the output **languages** (Italian and English by default).
3. Start — the app transcribes, cleans up the text and writes a **Word document** per language.
   (Webex "personal room" recordings also need a `cookies.txt` exported from your browser.)

## ⏳ If it's slow, or a lecture stops with a "server busy" message
The app uses Google Gemini on the **free tier**, so it shares capacity with everyone else.
When Google's servers are under heavy load they temporarily refuse requests ("high demand"),
and transcription can get **slow** or a lecture may **stop with a message saying Google is busy**.
This is a temporary problem **on Google's side, not a bug in the app** — and it comes and goes
within minutes. Just **wait a few minutes and press "Retry"** on the lecture: it resumes from
where it left off (already-done parts are kept), so you don't lose any work. If a whole stretch
of the day is bad, try again later.

**Tip on timing:** these services tend to be busiest in the **European afternoon** (which overlaps
with the US morning). If you keep hitting slowdowns, **early morning or late evening** usually works
better. (There's no official schedule — it just reflects when the most people worldwide are using it.)

---

## 🔒 Privacy & responsible use
- **Your audio and the resulting transcripts are sent to Google Gemini** for processing —
  the content leaves your computer and is handled by Google under their API terms. The app
  uses **your own** key, stored locally (never in the code or in a file).
- **Only transcribe recordings you are allowed to use.** Lectures and downloaded videos may be
  copyrighted and may contain other people's personal data (e.g. a professor's voice/name).
  Make sure you have the right to record, download and transcribe them. Downloading from some
  sites (e.g. YouTube) may be restricted by their Terms of Service — respect them.
- Provided for personal study, free of charge, with no warranty.

## 📄 License
- This project's own source code: **MIT** — see [`LICENSE`](LICENSE).
- The downloadable app bundles third-party programs (notably **FFmpeg**, under the **GPL**)
  and libraries, each under its own license — see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
