from threading import Event

import pytest

from dancer.tcode import (
    TCodeEvent,
    build_tcode_events,
    encode_axis,
    export_tcode_script,
    load_tcode_script,
    play_tcode_events,
    position_to_tcode,
)


def test_position_and_axis_encoding():
    assert position_to_tcode(0) == 0
    assert position_to_tcode(50) == 5000
    assert position_to_tcode(100) == 9999
    assert encode_axis("L0", 50, interval_ms=250) == "L05000I250"
    assert encode_axis("R2", 100) == "R29999"


def test_multiaxis_events_are_ramp_ahead_and_synchronized():
    plan = {
        "L0": [(0.5, 10), (1.0, 90)],
        "L1": [(0.5, 20), (1.0, 80)],
        "L2": [(0.5, 30), (1.0, 70)],
        "R0": [(0.5, 40), (1.0, 60)],
        "R1": [(0.5, 50), (1.0, 50)],
        "R2": [(0.5, 60), (1.0, 40)],
    }
    events = build_tcode_events(plan)
    assert len(events) == 2
    assert events[0].send_at == 0.0
    assert events[0].target_at == 0.5
    assert events[0].interval_ms == 500
    assert "L01000I500" in events[0].command
    assert "R25999I500" in events[0].command
    assert events[1].send_at == 0.5
    assert events[1].target_at == 1.0
    assert len(events[0].command.split()) == 6


def test_tcode_script_round_trip(tmp_path):
    events = [
        TCodeEvent(0.0, 0.5, 500, "L05000I500 R05000I500"),
        TCodeEvent(0.5, 1.0, 500, "L09000I500 R01000I500"),
    ]
    output = export_tcode_script(tmp_path / "scene.tcode", events, source="scene.mp4")
    loaded = load_tcode_script(output)
    assert [event.send_at for event in loaded] == [0.0, 0.5]
    assert loaded[1].command == "L09000I500 R01000I500"


def test_playback_can_be_stopped_without_waiting():
    class FakeDevice:
        def __init__(self):
            self.sent = []
            self.stopped = False

        def send(self, command):
            self.sent.append(command)

        def stop(self):
            self.stopped = True

    stop = Event()
    stop.set()
    device = FakeDevice()
    play_tcode_events(
        [TCodeEvent(10.0, 10.5, 500, "L05000I500")],
        device,
        stop_event=stop,
    )
    assert device.stopped is True
    assert device.sent == []


def test_invalid_playback_speed():
    class FakeDevice:
        def send(self, command):
            pass

        def stop(self):
            pass

    with pytest.raises(ValueError):
        play_tcode_events([TCodeEvent(0.0, 0.0, 0, "L05000")], FakeDevice(), speed=0)
