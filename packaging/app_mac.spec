# -*- mode: python ; coding: utf-8 -*-
"""Build del pacchetto macOS 'Trascrivi Lezioni.app' (PyInstaller).

Gemello di app.spec (Windows), adattato al Mac:
  - produce un .app (BUNDLE) invece di un singolo .exe;
  - icona .icns (generata in CI da packaging/icon.png);
  - i binari ffmpeg/ffprobe/yt-dlp (build macOS) stanno in packaging/bin-macos/,
    scaricati dal workflow GitHub Actions (NON versionati nel repo);
  - keyring usa il Portachiavi di macOS (hiddenimport diverso da Windows).

Architettura: x86_64 (host del runner Intel macos-13). Gira anche su Apple
Silicon tramite Rosetta. In futuro si puo' passare a universal2 (serve Python
universal2 + binari fusi con lipo).

Risorse impacchettate (coerenti con come il codice le cerca via sys._MEIPASS):
  - ui/                    -> _MEIPASS/ui/   (percorsi.risorsa)
  - ffmpeg / ffprobe       -> _MEIPASS/      (audio._trova guarda in _MEIPASS)
  - yt-dlp                 -> _MEIPASS/      (download._ytdlp_binario lo copia in ~/Library/...)
I binari sono messi tra i 'datas' (blob opachi, cosi' PyInstaller non prova ad
analizzare il mach-o statico/standalone); il codice garantisce il bit +x a
runtime (percorsi.assicura_eseguibile).
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent            # C:\whisper_test / radice repo
BINM = Path(SPECPATH) / "bin-macos"     # ffmpeg/ffprobe/yt-dlp (macOS), scaricati in CI
ICNS = str(Path(SPECPATH) / "icon.icns")

# Versione dall'unica fonte di verita' (config.py), per l'Info.plist.
sys.path.insert(0, str(ROOT))
from trascrittore import config  # noqa: E402

datas = [
    (str(ROOT / "ui"), "ui"),
    (str(BINM / "ffmpeg"), "."),
    (str(BINM / "ffprobe"), "."),
    (str(BINM / "yt-dlp"), "."),
]

hiddenimports = [
    "keyring.backends.macOS",   # chiave API nel Portachiavi di macOS
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
