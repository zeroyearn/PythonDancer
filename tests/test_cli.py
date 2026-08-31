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
    assert args.baud == 115200
    assert args.play_speed == 1.0
    assert args.start_at == 0.0
    assert args.seek_ramp_ms == 120
    assert args.no_device_ranges is False
    assert args.tcode is False
    assert args.serial_port is None


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
        "--no_device_ranges",
    ])
    assert args.tcode is True
    assert args.tcode_preview == 3
    assert args.serial_port == "/dev/ttyUSB0"
    assert args.baud == 250000
    assert args.play_speed == 1.5
    assert args.start_at == 42.5
    assert args.seek_ramp_ms == 180
    assert args.no_device_ranges is True
