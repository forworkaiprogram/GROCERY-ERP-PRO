# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the GROCERY ERP PRO Windows desktop EXE.
#
# Build on Windows (PyInstaller produces platform-specific bundles only):
#   pip install -r requirements-desktop.txt
#   pyinstaller desktop\packaging\grocery_erp_pro.spec --noconfirm
#
# The data directory policy is honored automatically: the app persists its
# SQLite DB under %LOCALAPPDATA%\GroceryERPPro (see desktop/database/db.py),
# never next to the EXE, so replacing the EXE atomically cannot touch data.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

block_cipher = None

hiddenimports = collect_submodules("desktop") + [
    "PySide6.QtSvg",
]

a = Analysis(
    [os.path.join(ROOT, "desktop", "app", "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (
            os.path.join(ROOT, "desktop", "database", "sql"),
            os.path.join("desktop", "database", "sql"),
        ),
        (
            os.path.join(ROOT, "desktop", "security", "public_keys"),
            os.path.join("desktop", "security", "public_keys"),
        ),
        (
            os.path.join(ROOT, "scripts", "build", "icon.ico"),
            "desktop",
        ),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "jupyter", "pytest", "django"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GroceryERPPro",
    icon=os.path.join(ROOT, "scripts", "build", "icon.ico"),
    debug=False,
    strip=False,
    upx=False,
    console=False,
    version=os.path.join(ROOT, "desktop", "packaging", "version_info.txt"),
)
