# PyInstaller spec for a double-clickable Readaloud app.
# Build from the repository root with:  pyinstaller packaging/readaloud.spec
# (see README, "Build a double-click app").

import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# Packages that load data files, models or native libraries at runtime.
for package in ("kokoro", "misaki", "espeakng_loader", "phonemizer", "spacy", "en_core_web_sm", "language_tags"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Readaloud",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Readaloud")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Readaloud.app",
        bundle_identifier="io.github.readaloud",
        info_plist={
            "CFBundleDisplayName": "Readaloud",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
