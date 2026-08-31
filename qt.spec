# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

hiddenimports = sorted(set(
	collect_submodules("buttplug")
	+ [
		"librosa",
		"librosa.feature",
		"librosa.util",
		"librosa.util.utils",
		"librosa.feature.rhythm",
		"librosa.beat",
		"librosa.core",
		"serial",
		"serial.tools.list_ports",
		"dancer.workstation_ui_v25",
		"dancer.workstation_ui_v25_final",
		"dancer.editing",
		"dancer.safety",
		"dancer.project",
		"dancer.outputs",
	]
))


a = Analysis(
	['ui_entry.py'],
	pathex=[],
	binaries=[],
	hiddenimports=hiddenimports,
	hookspath=["extra-hooks"],
	hooksconfig={},
	runtime_hooks=[],
	excludes=[],
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
	name='PythonDancer.exe',
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=True,
	upx_exclude=[],
	runtime_tmpdir=None,
	console=True,
	disable_windowed_traceback=False,
	argv_emulation=False,
	target_arch=None,
	codesign_identity=None,
	entitlements_file=None,
)
