# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec dla TimeRecord.

Build: pyinstaller timerecord.spec --noconfirm
Lub przez: python scripts/build.py
"""
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

# Szablony HTML jako dane
datas = [
    (str(ROOT / 'templates' / 'dashboard.html'), 'templates'),
]

# Hidden imports — uvicorn/fastapi często nie wykrywalne przez PyInstaller
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'anyio._backends._asyncio',
    'email.mime.multipart',
    'email.mime.text',
]

# pywin32 — upewnij się że DLL-e są dołączone
binaries = []
try:
    import win32sysloader
    binaries += [(win32sysloader.__file__, '.')]
except (ImportError, AttributeError):
    pass

a = Analysis(
    [str(ROOT / 'run.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'pytest'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TimeRecord',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # bez okna konsoli (jak pythonw.exe)
    icon=str(ROOT / 'assets' / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TimeRecord',
)
