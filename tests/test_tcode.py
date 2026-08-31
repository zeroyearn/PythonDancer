from threading import Event, Thread
from time import sleep

import pytest

from dancer.tcode import (
    AxisRange,
    DeviceProfile,
    TCodeEvent,
    TCodePlaybackController,
    build_tcode_events,
    encode_axis,
    encode_plan_frame,
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
    assert encode_axis("R2", 100) == "R29999"


def test_d2_axis_ranges_are_parsed_and_applied():
    axes = parse_d2_axes(["L0 1000 9000 Up", "R0 2000 8000 Twist", "Ready!"])
    assert axes["L0"] == AxisRange("L0", 1000, 9000, "Up")
    assert position_to_tcode(0, axis_range=axes["L0"]) == 1000
    assert position_to_tcode(50, axis_range=axes["L0"]) == 5000
    assert position_to_tcode(100, axis_range=axes["R0"]) == 8000


def test_device_profile_filters_unsupported_axes():
    plan = {
        "L0": [(0.5, 0), (1.0, 100)],
        "L1": [(0.5, 25), (1.0, 75)],
        "R0": [(0.5, 50), (1.0, 50)],
    }
    profile = DeviceProfile(axes=parse_d2_axes(["L0 1000 9000 Up", "R0 2000 8000 Twist"]))
    events = build_tcode_events(plan, profile=profile)
    assert len(events) == 2
    assert "L01000I500" in events[0].command
    assert "R05000I500" in events[0].command
    assert "L1" not in events[0].command
    assert "L09000I500" in events[1].command


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


def test_build_events_can_use_non_l0_timeline():
    plan = {
        "L1": [(0.2, 40.0), (0.6, 60.0)],
        "R0": [(0.3, 45.0), (0.6, 55.0)],
    }
    events = build_tcode_events(plan)
    assert [round(event.target_at, 3) for event in events] == [0.2, 0.3, 0.6]
    assert all("L0" not in event.command for event in events)
    assert all("L1" in event.command and "R0" in event.command for event in events)


def test_seeked_schedule_starts_from_requested_timeline_position():
    plan = {"L0": [(1.0, 0), (2.0, 50), (3.0, 100)]}
    events = build_tcode_events(plan, start_at=1.5)
    assert [event.target_at for event in events] == [2.0, 3.0]
    assert events[0].send_at == 1.5
    assert events[0].interval_ms == 500
    assert events[1].send_at == 2.0
    assert encode_plan_frame(plan, 1.5) == "L02500"


def test_tcode_script_round_trip(tmp_path):
    events = [
        TCodeEvent(0.0, 0.5, 500, "L05000I500 R05000I500"),
        TCodeEvent(0.5, 1.0, 500, "L09000I500 R01000I500"),
    ]
    output = export_tcode_script(tmp_path / "scene.tcode", events, source="scene.mp4")
    loaded = load_tcode_script(output)
    assert [event.send_at for event in loaded] == [0.0, 0.5]
    assert loaded[1].command == "L09000I500 R01000I500"


def test_playback_controller_pause_seek_resume_stop():
    class FakeDevice:
        def __init__(self):
            self.sent = []
            self.stop_count = 0

        def send(self, command):
            self.sent.append(command)

        def stop(self):
            self.stop_count += 1

    plan = {"L0": [(5.0, 0), (10.0, 100)], "R0": [(5.0, 25), (10.0, 75)]}
    device = FakeDevice()
    controller = TCodePlaybackController(plan, device, seek_ramp_ms=0)
    thread = Thread(target=controller.play, daemon=True)
    thread.start()
    sleep(0.03)
    before_pause = len(device.sent)
    controller.pause()
    assert controller.state == "paused"
    sleep(0.03)
    assert len(device.sent) == before_pause
    controller.seek(7.0)
    sleep(0.03)
    assert controller.position == pytest.approx(7.0, abs=0.1)
    controller.resume()
    sleep(0.03)
    controller.stop()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert device.stop_count >= 2
    assert any(command.startswith("L0") for command in device.sent)


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
    play_tcode_events([TCodeEvent(10.0, 10.5, 500, "L05000I500")], device, stop_event=stop)
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
