from dancer.util import cli_args


def test_cli_v2_defaults():
    args = cli_args().parse_args(["song.wav", "--cli"])
    assert args.planner == "adaptive"
    assert args.subdivision == 0
    assert args.energy == 1.0
    assert args.max_speed == 400.0
    assert args.multiaxis is False
    assert args.multiaxis_preset == "balanced"
    assert args.axis_strength == 1.0
    assert args.choreography_mode == "choreography"
    assert args.gesture_strength == 1.0
    assert args.beats_per_bar == 4
    assert args.bars_per_phrase == 4
    assert args.section_bars == 4
    assert args.show_sections is False
    assert args.profile is None
    assert args.reference_bundle is None
    assert args.save_learned_profile is None
    assert args.stems == "off"
    assert args.stem_dir is None
    assert args.stem_cache == ".dancer_stems"
    assert args.demucs_model == "htdemucs"
    assert args.baud == 115200
    assert args.play_speed == 1.0
    assert args.start_at == 0.0
    assert args.seek_ramp_ms == 120
    assert args.no_device_ranges is False
    assert args.tcode is False
    assert args.serial_port is None
    assert args.intiface is False
    assert args.intiface_address == "ws://127.0.0.1:12345"
    assert args.intiface_device is None
    assert args.soft_start_ms == 750
    assert args.auto_home is True
    assert args.home_ms == 700


def test_cli_multiaxis_flags():
    args = cli_args().parse_args([
        "song.wav",
        "--cli",
        "--multiaxis",
        "--multiaxis_preset", "expressive",
        "--axis_strength", "1.25",
        "--choreography_mode", "reactive",
        "--gesture_strength", "1.4",
        "--beats_per_bar", "3",
        "--bars_per_phrase", "8",
        "--section_bars", "2",
        "--show_sections",
        "--reference_bundle", "reference.funscript",
        "--save_learned_profile", "style.json",
        "--profile_name", "favorite",
        "--stems", "required",
        "--stem_dir", "stems",
        "--stem_cache", "cache",
        "--demucs_model", "htdemucs_ft",
    ])
    assert args.multiaxis is True
    assert args.multiaxis_preset == "expressive"
    assert args.axis_strength == 1.25
    assert args.choreography_mode == "reactive"
    assert args.gesture_strength == 1.4
    assert args.beats_per_bar == 3
    assert args.bars_per_phrase == 8
    assert args.section_bars == 2
    assert args.show_sections is True
    assert args.reference_bundle == "reference.funscript"
    assert args.save_learned_profile == "style.json"
    assert args.profile_name == "favorite"
    assert args.stems == "required"
    assert args.stem_dir == "stems"
    assert args.stem_cache == "cache"
    assert args.demucs_model == "htdemucs_ft"


def test_cli_tcode_device_flags():
    args = cli_args().parse_args([
        "song.wav",
        "--cli",
        "--multiaxis",
        "--tcode",
        "--tcode_preview", "3",
        "--serial_port", "/dev/ttyUSB0",
        "--baud", "250000",
        "--play_speed", "1.5",
        "--start_at", "42.5",
        "--seek_ramp_ms", "180",
        "--soft_start_ms", "900",
        "--no-auto-home",
        "--home_ms", "850",
        "--no_device_ranges",
    ])
    assert args.tcode is True
    assert args.tcode_preview == 3
    assert args.serial_port == "/dev/ttyUSB0"
    assert args.baud == 250000
    assert args.play_speed == 1.5
    assert args.start_at == 42.5
    assert args.seek_ramp_ms == 180
    assert args.soft_start_ms == 900
    assert args.auto_home is False
    assert args.home_ms == 850
    assert args.no_device_ranges is True


def test_cli_intiface_flags():
    args = cli_args().parse_args([
        "song.wav", "--cli", "--multiaxis", "--intiface",
        "--intiface_address", "ws://localhost:23456",
        "--intiface_device", "3",
        "--play_speed", "0.75",
        "--start_at", "12.25",
        "--soft_start_ms", "1100",
        "--home_ms", "900",
    ])
    assert args.intiface is True
    assert args.intiface_address == "ws://localhost:23456"
    assert args.intiface_device == 3
    assert args.play_speed == 0.75
    assert args.start_at == 12.25
    assert args.soft_start_ms == 1100
    assert args.auto_home is True
    assert args.home_ms == 900
