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
		"matplotlib.backends.backend_tkagg",
		"mpl_toolkits.mplot3d",
		"serial",
		"serial.tools.list_ports",
		"dancer.workstation_ui_v25",
		"dancer.workstation_ui_v25_final",
		"dancer.workstation_ui_v26",
		"dancer.workstation_ui_v26_final",
		"dancer.workstation_ui_v26_release",
		"dancer.editing",
		"dancer.safety",
		"dancer.project",
		"dancer.outputs",
		"dancer.tcode_speed",
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
		"dancer.cli_v26",
		"dancer.cli_v26_final",
		"dancer.cli_v26_release",
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
