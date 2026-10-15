# -*- mode: python ; coding: utf-8 -*-
"""Build del pacchetto macOS 'Trascrivi Lezioni.app' (PyInstaller).

Gemello di app.spec (Windows), adattato al Mac:
  - produce un .app (BUNDLE) invece di un singolo .exe;
  - icona .icns (generata in CI da packaging/icon.png);
  - i binari ffmpeg/ffprobe/yt-dlp (build macOS) stanno in packaging/bin-macos/,
    scaricati dal workflow GitHub Actions (NON versionati nel repo);
  - keyring usa il Portachiavi di macOS (hiddenimport diverso da Windows).

Architettura: arm64 (Apple Silicon), host del runner macos-14. Scelta "Strada 1":
copre tutti i Mac recenti (dal 2020). I Mac Intel vecchi NON sono coperti (si
potra' aggiungere in futuro un build universal2). macos-13 (Intel) e' stato
scartato: a meta' 2025 i suoi runner spesso non prendono i job (restano in coda).

Risorse impacchettate (coerenti con come il codice le cerca via sys._MEIPASS):
  - ui/                    -> _MEIPASS/ui/   (percorsi.risorsa)
  - ffmpeg / ffprobe       -> _MEIPASS/      (audio._trova guarda in _MEIPASS)
  - yt-dlp                 -> _MEIPASS/      (download._ytdlp_binario lo copia in ~/Library/...)
ffmpeg/ffprobe vengono da Homebrew (dinamici): stanno tra i 'binaries' cosi'
PyInstaller analizza il mach-o e impacchetta anche le librerie (.dylib) che
servono. yt-dlp e' uno standalone opaco -> 'datas', col bit +x garantito a
runtime (percorsi.assicura_eseguibile).
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent            # C:\whisper_test / radice repo
BINM = Path(SPECPATH) / "bin-macos"     # ffmpeg/ffprobe/yt-dlp (macOS), preparati in CI
ICNS = str(Path(SPECPATH) / "icon.icns")

# Versione dall'unica fonte di verita' (config.py), per l'Info.plist.
sys.path.insert(0, str(ROOT))
from trascrittore import config  # noqa: E402

binaries = [
    (str(BINM / "ffmpeg"), "."),    # PyInstaller ci tira dietro le .dylib di Homebrew
    (str(BINM / "ffprobe"), "."),
]

datas = [
    (str(ROOT / "ui"), "ui"),
    (str(BINM / "yt-dlp"), "."),    # standalone opaco (universal2); +x a runtime
]

hiddenimports = [
    "keyring.backends.macOS",   # chiave API nel Portachiavi di macOS
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
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
    [],
    exclude_binaries=True,       # i binari vanno nel COLLECT (.app onedir)
    name="Trascrivi Lezioni",
    debug=False,
    strip=False,
    upx=False,
    console=False,               # app con finestra, niente terminale
    icon=ICNS,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Trascrivi Lezioni",
)

app = BUNDLE(
    coll,
    name="Trascrivi Lezioni.app",
    icon=ICNS,
    bundle_identifier="com.giorgioalo.trascrivilezioni",
    info_plist={
        "CFBundleName": "Trascrivi Lezioni",
        "CFBundleDisplayName": "Trascrivi Lezioni",
        "CFBundleShortVersionString": config.VERSION,
        "CFBundleVersion": config.VERSION,
        "LSMinimumSystemVersion": "11.0",        # Big Sur+
        "NSHighResolutionCapable": True,         # schermi Retina
        "NSRequiresAquaSystemAppearance": False, # rispetta tema chiaro/scuro
        "LSApplicationCategoryType": "public.app-category.education",
    },
)
