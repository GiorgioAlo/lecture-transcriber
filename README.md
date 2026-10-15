# lecture-transcriber
Automatic lecture transcription app turning audio/video and links (YouTube/Webex) into formatted documents using Google Gemini.

## Run in Google Colab (no install)
The easiest way to use it: run it in the cloud, nothing to install.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/GiorgioAlo/lecture-transcriber/blob/main/notebooks/Trascrivi_Lezioni_Colab.ipynb)

Open the notebook, add your Gemini key as a Colab *Secret*, upload your lectures
(or paste links), and run the cells. The first cell is a step-by-step tutorial.

## Command-line version
Prefer the terminal (or running on Linux/servers)? There's a no-GUI `transcribe`
command — see [`CLI.md`](CLI.md) for install and usage.

## Privacy & responsible use
- **Your audio and the resulting transcripts are sent to Google Gemini** for
  processing — the content leaves your computer and is handled by Google under
  their API terms. The app uses **your own** Google Gemini API key, stored
  locally in your operating system's keychain (never in the code or in a file).
- **Only transcribe recordings you are allowed to use.** Lectures and downloaded
  videos may be copyrighted and may contain other people's personal data
  (e.g. a professor's voice/name). Make sure you have the right to record,
  download and transcribe them. Downloading from some sites (e.g. YouTube) may be
  restricted by their Terms of Service — respect them.
- This tool is provided for personal study, free of charge, with no warranty.

## License
- This project's own source code: **MIT** — see [`LICENSE`](LICENSE).
- The downloadable app bundles third-party programs (notably **FFmpeg**, under
  the **GPL**) and libraries, each under its own license — see
  [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
