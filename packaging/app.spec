# -*- mode: python ; coding: utf-8 -*-
"""Build del pacchetto 'Trascrivi Lezioni' (PyInstaller).

Parte in ONEDIR (cartella, facile da ispezionare/debuggare). Quando il build e'
pulito si passa a ONEFILE (vedi in fondo).

Risorse impacchettate (coerenti con come il codice le cerca):
  - ui/                  -> _MEIPASS/ui/      (percorsi.risorsa)
  - ffmpeg.exe/ffprobe   -> _MEIPASS/         (audio._trova guarda in _MEIPASS)
  - yt-dlp.exe (seme)    -> _MEIPASS/         (download._ytdlp_binario lo copia in %LOCALAPPDATA%)
"""
import os
import sys
from pathlib import Path

# conda mette le DLL native (OpenSSL libssl/libcrypto, ffi, expat, lzma, bz2...) in
# <env>\Library\bin, che PyInstaller NON scandaglia di default → _ssl/_ctypes ecc.
# non si caricherebbero (DLL load failed). Mettendo quella cartella nel PATH durante
# il build, lo scanner delle dipendenze le trova e le impacchetta.
_conda_bin = Path(sys.prefix) / "Library" / "bin"
if _conda_bin.is_dir():
    os.environ["PATH"] = str(_conda_bin) + os.pathsep + os.environ.get("PATH", "")

ROOT = Path(SPECPATH).parent          # C:\whisper_test
BIN = Path(SPECPATH) / "bin"          # ffmpeg/ffprobe/yt-dlp statici per il bundle

datas = [
    (str(ROOT / "ui"), "ui"),
    (str(BIN / "ffmpeg.exe"), "."),
    (str(BIN / "ffprobe.exe"), "."),
    (str(BIN / "yt-dlp.exe"), "."),
]

# Moduli caricati "dinamicamente" che PyInstaller non trova da solo.
hiddenimports = [
    "keyring.backends.Windows",         # chiave API nel Credential Manager
    "win32ctypes.core",
    "win32ctypes.pywin32.win32cred",
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,                  # ONEFILE: tutto dentro il singolo .exe
    a.datas,
    [],
    name="Trascrivi Lezioni",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,               # app con finestra, niente console nera
    icon=str(Path(SPECPATH) / "icon.ico"),
)
