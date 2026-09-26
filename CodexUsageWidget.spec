# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import shiboken6


shiboken6_dll = Path(shiboken6.__file__).with_name('shiboken6.abi3.dll')


def is_conflicting_system_binary(entry):
    name = Path(entry[0]).name.casefold()
    return (
        name.startswith(('api-ms-win-', 'ext-ms-win-', 'icu'))
        or name in {'ucrtbase.dll'}
    )

a = Analysis(
    ['codex_usage_widget.py'],
    pathex=[],
    # QtCore.pyd imports shiboken6.abi3.dll by name. Keep a copy next to the
    # PySide6 extension modules so Windows can resolve it without PATH lookup.
    binaries=[(str(shiboken6_dll), 'PySide6')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyside6_dll_path.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# The build environment exposes Poppler's ICU and UCRT shim DLLs through PATH.
# Shipping them beside Qt6Core makes Windows resolve the wrong ICU ABI first
# (Qt asks for ucnv_open, while that ICU exports ucnv_open_78). Let Windows use
# its system API-set/UCRT/ICU implementations instead.
bundle_binaries = [entry for entry in a.binaries if not is_conflicting_system_binary(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    bundle_binaries,
    a.datas,
    [],
    name='CodexUsageWidget',
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
)
