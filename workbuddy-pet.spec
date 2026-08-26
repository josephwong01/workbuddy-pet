# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['pystray', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'tkinter', 'tkinter.ttk', 'http.server', 'urllib.request']
hiddenimports += collect_submodules('pystray')
hiddenimports += collect_submodules('PIL')


a = Analysis(
    ['C:/Users/win/WorkBuddy/2026-08-25-11-10-41/WorkBuddy-pet/scripts/app.py'],
    pathex=['C:/Users/win/WorkBuddy/2026-08-25-11-10-41/WorkBuddy-pet/scripts'],
    binaries=[],
    datas=[('C:/Users/win/WorkBuddy/2026-08-25-11-10-41/WorkBuddy-pet/assets', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='workbuddy-pet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/win/WorkBuddy/2026-08-25-11-10-41/WorkBuddy-pet/assets/icon/app_icon.ico'],
)
