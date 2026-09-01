# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    raise RuntimeError("macOS release build requires ffmpeg on PATH")

hiddenimports = sorted(set(
    collect_submodules("librosa")
    + collect_submodules("buttplug")
    + [
        "matplotlib.backends.backend_tkagg",
        "mpl_toolkits.mplot3d",
        "serial",
        "serial.tools.list_ports",
        "serial.tools.list_ports_osx",
        "dancer.cli",
        "dancer.cli_v26",
        "dancer.cli_v26_final",
        "dancer.cli_v26_release",
        "dancer.ui",
        "dancer.multiaxis_ui",
        "dancer.choreography",
        "dancer.choreo_profile",
        "dancer.style",
        "dancer.stems",
        "dancer.tcode",
        "dancer.tcode_speed",
        "dancer.runtime",
        "dancer.workstation_ui_v25",
        "dancer.workstation_ui_v25_final",
        "dancer.workstation_ui_v26",
        "dancer.workstation_ui_v26_final",
        "dancer.workstation_ui_v26_release",
        "dancer.editing",
        "dancer.safety",
        "dancer.project",
        "dancer.outputs",
        "dancer.intent",
        "dancer.independent_planner",
        "dancer.optimizer",
        "dancer.reference_library",
        "dancer.latency",
        "dancer.calibration",
        "dancer.generation_limits",
        "dancer.kinematics",
        "dancer.geometry_profile",
        "dancer.i18n",
        "dancer.i18n_safe",
    ]
))

a = Analysis(
    [str(project_root / "macos_entry.py")],
    pathex=[str(project_root)],
    binaries=[(ffmpeg, ".")],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "extra-hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PythonDancer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PythonDancer")

app = BUNDLE(
    coll,
    name="PythonDancer.app",
    icon=None,
    bundle_identifier="com.pythondancer.app",
    info_plist={
        "CFBundleDisplayName": "PythonDancer",
        "CFBundleName": "PythonDancer",
        "CFBundleShortVersionString": "2.6.0",
        "CFBundleVersion": "2.6.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "PythonDancer contributors",
    },
)
