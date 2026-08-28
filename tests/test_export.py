import io
import json

from dancer.libfun import dump_funscript, render_heatmap


def test_empty_funscript_export_is_valid():
    buffer = io.StringIO()
    dump_funscript(buffer, [])
    payload = json.loads(buffer.getvalue())
    assert payload["actions"] == []
    assert payload["metadata"]["duration"] == 0


def test_heatmap_accepts_named_motion_parameters():
    data = {
        "beats": [0.5, 1.0],
        "energy": [0.2, 1.0],
        "pitch": [1.0, 1.2],
    }
    fig = render_heatmap(
        data,
        1.0,
        100,
        0,
        amplitude_centering=5,
        center_offset=10,
        w=320,
        h=32,
    )
    assert fig is not None
