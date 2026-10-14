# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

root = Path(SPECPATH)
# Qt uses Windows ICU; unrelated tools on PATH can supply an incompatible ICU DLL.
os.environ['PATH'] = os.pathsep.join((sys.base_prefix, str(Path(sys.base_prefix) / 'DLLs'),
                                     str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']))
a = Analysis(
    [str(root / 'app.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='AudioCut',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root / 'assets' / 'app.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AudioCut')
