from dancer.util import cli_args


def test_cli_v2_defaults():
    args = cli_args().parse_args(["song.wav", "--cli"])
    assert args.planner == "adaptive"
    assert args.subdivision == 0
    assert args.energy == 1.0
    assert args.max_speed == 400.0
