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


def test_cli_multiaxis_flags():
    args = cli_args().parse_args([
        "song.wav",
        "--cli",
        "--multiaxis",
        "--multiaxis_preset", "expressive",
        "--axis_strength", "1.25",
    ])
    assert args.multiaxis is True
    assert args.multiaxis_preset == "expressive"
    assert args.axis_strength == 1.25
