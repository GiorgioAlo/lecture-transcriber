# Third-party notices

This application ("Trascrivi Lezioni" / lecture-transcriber) is distributed as a
single downloadable package that **bundles third-party programs and libraries**.
Each of them is covered by its own license, listed below. The project's own
source code is under the MIT license (see `LICENSE`).

The project's own code invokes FFmpeg and yt-dlp as **separate processes**
(subprocess), it does not link them into its own binary. This "mere aggregation"
means the project's own code is not a derivative work of those programs; even so,
their binaries are redistributed with the app, so their licenses apply to those
binaries and are reproduced/referenced here.

---

## FFmpeg (ffmpeg, ffprobe) — GPL

The app bundles **FFmpeg** (the `ffmpeg` and `ffprobe` executables) to extract and
segment audio.

- The bundled builds are configured with GPL components (e.g. x264/x265), so they
  are licensed under the **GNU General Public License, version 3 (GPLv3)**.
- Full license text: https://www.gnu.org/licenses/gpl-3.0.html
- FFmpeg project and licensing details: https://ffmpeg.org/legal.html
- **Corresponding source code** (GPL requirement) is available from the FFmpeg
  project and from the build providers used here:
  - FFmpeg source: https://ffmpeg.org/download.html  and  https://github.com/FFmpeg/FFmpeg
  - Windows builds: https://www.gyan.dev/ffmpeg/builds/
  - macOS builds: Homebrew — https://formulae.brew.sh/formula/ffmpeg
- **Written offer:** the maintainer of this project will, on request, provide the
  complete corresponding source code of the exact FFmpeg build distributed with a
  given release (open an issue on the project repository).

## yt-dlp — The Unlicense (public domain)

The app bundles **yt-dlp** to download audio from links (YouTube/Webex).

- License: **The Unlicense** (public domain dedication) — https://unlicense.org
- Project / source: https://github.com/yt-dlp/yt-dlp

## Python libraries bundled in the app

| Component | Purpose | License |
|-----------|---------|---------|
| pywebview | app window (local web UI) | BSD-3-Clause |
| google-genai (Google Gen AI SDK) | calls to Google Gemini | Apache-2.0 |
| python-docx | generates the Word documents | MIT |
| lxml | XML backend used by python-docx | BSD-3-Clause |
| keyring | stores the API key in the OS keychain | MIT |
| pyobjc (macOS only) | macOS WebView integration | MIT |

These libraries are permissively licensed (BSD/MIT/Apache); their copyright
notices are retained in their respective packages bundled inside the app.

## Build-only tools (not distributed in the app)

- **PyInstaller** (GPL with a bundling exception that does not affect the license
  of the produced app) and **Pillow** (HPND) are used only to build the package
  and are not shipped at runtime.

---

*If you redistribute this app, keep this file alongside it to satisfy the FFmpeg
GPL notice requirement.*
