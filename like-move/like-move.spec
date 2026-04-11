# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for like-move.

Usage: pyinstaller like-move.spec
Output: dist/like-move.exe
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# pystray backends — only win32 needed on Windows
pystray_hiddenimports = [
    'pystray._win32',
]

# Pillow image plugins used at runtime
pil_hiddenimports = [
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.BmpImagePlugin',
    'PIL.PngImagePlugin',
    'PIL.IcoImagePlugin',
]

# App modules imported dynamically at runtime
app_hiddenimports = [
    'like_move.about',
    'like_move.splash',
    'like_move.startup',
]

a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/like-move.ico', 'assets'),
        ('VERSION', '.'),
    ],
    hiddenimports=pystray_hiddenimports + pil_hiddenimports + app_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Unused stdlib/third-party modules — reduces .exe size
        'tkinter',
        '_tkinter',
        'unittest',
        'email',
        'html',
        'http',
        'xml',
        'pydoc',
        'doctest',
        'argparse',
        'difflib',
        'multiprocessing',
        'socketserver',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name='like-move',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # --noconsole / --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/like-move.ico',
)
