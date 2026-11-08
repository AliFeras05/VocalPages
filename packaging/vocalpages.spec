# PyInstaller spec for a double-clickable VocalPages app.
# Build from the repository root with:  pyinstaller packaging/vocalpages.spec
# (see README, "Build a double-click app").

import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# Packages that load data files, models or native libraries at runtime.
for package in ("vocalpages", "kokoro", "misaki", "espeakng_loader", "phonemizer", "spacy", "en_core_web_sm", "language_tags"):
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
    name="VocalPages",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VocalPages")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VocalPages.app",
        bundle_identifier="io.github.vocalpages",
        info_plist={
            "CFBundleDisplayName": "VocalPages",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
