# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for like-move.

Usage: pyinstaller like-move.spec
Output: dist/like-move/ (like-move.exe + _internal/), distribuído como like-move-win64.zip

Pasta (onedir), sem UPX e com metadados de versão no exe: o modo onefile extrai
tudo para %TEMP% e executa de lá, e o UPX comprime os binários — os dois são
heurísticas clássicas de antivírus.
"""

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

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
    'like_move.settings',
    'like_move.wifi',
    'like_move.updater',
    'like_move.awake',
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
        'pydoc',
        'doctest',
        'argparse',
        'difflib',
        'multiprocessing',
        'socketserver',
        # NOTE: não excluir 'http'/'email'/'xml' — urllib.request (auto-update)
        # depende de http.client e email; removê-los quebra o updater no .exe.
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

with open('VERSION', encoding='utf-8') as f:
    _ver = f.read().strip()
_nums = tuple(int(x) for x in (_ver.split('.') + ['0', '0', '0'])[:4])
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[
        StringFileInfo([StringTable('041604B0', [
            StringStruct('CompanyName', 'Allan Santos'),
            StringStruct('FileDescription', 'like-move - mantém o Windows sem bloquear'),
            StringStruct('FileVersion', _ver),
            StringStruct('InternalName', 'like-move'),
            StringStruct('LegalCopyright', 'MIT License - github.com/AllanSantos-DV/like-move'),
            StringStruct('OriginalFilename', 'like-move.exe'),
            StringStruct('ProductName', 'like-move'),
            StringStruct('ProductVersion', _ver),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0416, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='like-move',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # --noconsole / --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/like-move.ico',
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='like-move',
)
