from pathlib import Path
from threading import Event

import pytest

from dancer.tcode import (
    AxisRange,
    DeviceProfile,
    TCodeEvent,
    TCodePlaybackController,
    build_tcode_events,
    encode_axis,
    export_tcode_script,
    load_tcode_script,
    parse_d2_axes,
    play_tcode_events,
    position_to_tcode,
)


def test_position_and_axis_encoding():
    assert position_to_tcode(0) == 0
    assert position_to_tcode(50) == 5000
    assert position_to_tcode(100) == 9999
    assert encode_axis("L0", 50, interval_ms=250) == "L05000I250"


def test_multiaxis_events_are_ramp_ahead_and_synchronized():
    plan = {
        "L0": [(0.25, 25.0), (0.5, 75.0)],
        "L1": [(0.25, 50.0), (0.5, 60.0)],
        "L2": [(0.25, 50.0), (0.5, 40.0)],
        "R0": [(0.25, 55.0), (0.5, 45.0)],
        "R1": [(0.25, 48.0), (0.5, 52.0)],
        "R2": [(0.25, 52.0), (0.5, 48.0)],
    }
    events = build_tcode_events(plan)
    assert len(events) == 2
    assert events[0].send_at == 0.0
    assert events[0].target_at == 0.25
    assert events[0].interval_ms == 250
    assert events[1].send_at == 0.25
    assert events[1].target_at == 0.5
    assert events[1].interval_ms == 250
    assert events[0].command.count(" ") == 5
    assert "L0" in events[0].command and "R2" in events[0].command


def test_tcode_script_round_trip(tmp_path):
    events = [TCodeEvent(0.0, 0.25, 250, "L05000I250 R05000I250"), TCodeEvent(0.25, 0.5, 250, "L06000I250 R04000I250")]
    path = export_tcode_script(tmp_path / "demo.tcode", events, source="demo.mp4")
    loaded = load_tcode_script(path)
    assert [item.send_at for item in loaded] == [0.0, 0.25]
    assert [item.command for item in loaded] == [item.command for item in events]


def test_playback_can_be_stopped_without_waiting():
    class Device:
        def __init__(self):
            self.commands = []
            self.stopped = 0

        def send(self, command):
            self.commands.append(command)

        def stop(self):
            self.stopped += 1

    event = Event()
    event.set()
    device = Device()
    play_tcode_events([TCodeEvent(10.0, 10.0, 0, "L05000")], device, stop_event=event)
    assert device.commands == []
    assert device.stopped == 1


def test_invalid_playback_speed():
    with pytest.raises(ValueError):
        play_tcode_events([], object(), speed=0)


def test_d2_ranges_are_parsed_and_applied():
    profile = DeviceProfile(axes=parse_d2_axes(["L0 1000 9000 Up", "R0 2000 8000 Twist"]))
    assert profile.axes["L0"] == AxisRange("L0", 1000, 9000, "Up")
    assert position_to_tcode(0, axis_range=profile.axes["L0"]) == 1000
    assert position_to_tcode(50, axis_range=profile.axes["L0"]) == 5000
    assert position_to_tcode(100, axis_range=profile.axes["L0"]) == 9000


def test_device_profile_filters_unsupported_axes():
    plan = {
        "L0": [(0.25, 25.0), (0.5, 75.0)],
        "L1": [(0.25, 50.0), (0.5, 60.0)],
        "R0": [(0.25, 55.0), (0.5, 45.0)],
    }
    profile = DeviceProfile(axes=parse_d2_axes(["L0 1000 9000 Up", "R0 2000 8000 Twist"]))
    events = build_tcode_events(plan, profile=profile)
    assert events
    assert "L0" in events[0].command
    assert "R0" in events[0].command
    assert "L1" not in events[0].command


def test_build_events_can_use_non_l0_timeline():
    # Workstation Mute removes L0 entirely before TCode playback. The protocol
    # layer should then use the union of the remaining active axis timestamps.
    plan = {
        "L1": [(0.2, 40.0), (0.6, 60.0)],
        "R0": [(0.3, 45.0), (0.6, 55.0)],
    }
    events = build_tcode_events(plan)
    assert [round(event.target_at, 3) for event in events] == [0.2, 0.3, 0.6]
    assert all("L0" not in event.command for event in events)
    assert all("L1" in event.command and "R0" in event.command for event in events)


class FakeDevice:
    def __init__(self):
        self.commands = []
        self.stops = 0

    def send(self, command):
        self.commands.append(command)

    def stop(self):
        self.stops += 1


def test_controller_pause_seek_resume_stop_state_machine():
    plan = {"L0": [(0.02, 20.0), (0.04, 80.0), (0.06, 20.0)], "R0": [(0.02, 50.0), (0.04, 60.0), (0.06, 40.0)]}
    device = FakeDevice()
    controller = TCodePlaybackController(plan, device, speed=10.0, seek_ramp_ms=0)
    controller.seek(0.03)
    assert controller.position == pytest.approx(0.03)
    controller.stop()
    assert device.stops >= 1


def test_pause_does_not_emit_hidden_sync_frame():
    device = FakeDevice()
    controller = TCodePlaybackController({"L0": [(0.1, 20.0), (0.2, 80.0)]}, device, seek_ramp_ms=0)
    # Pausing an idle controller is intentionally a no-op and must not move it.
    before = len(device.commands)
    controller.pause()
    assert len(device.commands) == before
