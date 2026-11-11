# -*- mode: python -*-
# Especificación de PyInstaller para MDEmeeh (Linux y Windows).
# No se usa directamente: ejecutar build.sh (Linux) o build.ps1 (Windows).
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
IS_WIN = sys.platform == "win32"

binaries = []
if sys.platform.startswith("linux"):
    # Qt >= 6.5 necesita libxcb-cursor en X11; se incluye para no depender del sistema.
    # build.sh la descarga en packaging/libs si no está.
    lib = os.path.join(SPECPATH, "libs", "libxcb-cursor.so.0")
    if os.path.exists(lib):
        binaries.append((lib, "."))

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=[(os.path.join(ROOT, "emeeh_markdown", "static"), "emeeh_markdown/static")],
    hiddenimports=["PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    excludes=["tkinter", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtMultimedia", "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtSql"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MDEmeeh",
    console=False,
    strip=False,
    upx=False,
    icon=os.path.join(SPECPATH, "icon.ico") if IS_WIN else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MDEmeeh")
