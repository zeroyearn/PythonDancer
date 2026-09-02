from dancer import tcode
from dancer.tcode_speed import SpeedAwareTCodePlaybackController, scale_tcode_intervals


class FakeDevice:
    def __init__(self):
        self.sent = []
        self.stop_count = 0

    def send(self, command):
        self.sent.append(command)

    def stop(self):
        self.stop_count += 1


def test_public_controller_is_speed_aware():
    assert tcode.TCodePlaybackController is SpeedAwareTCodePlaybackController


def test_scale_tcode_intervals_tracks_playback_speed():
    command = "L05000I250 R05000I250"
    assert scale_tcode_intervals(command, 2.0) == "L05000I125 R05000I125"
    assert scale_tcode_intervals(command, 0.5) == "L05000I500 R05000I500"
    assert scale_tcode_intervals(command, 1.0) == command


def test_seek_sync_keeps_real_safety_ramp_unscaled():
    plan = {
        "L0": [(0.0, 20.0), (1.0, 80.0)],
        "L1": [], "L2": [], "R0": [], "R1": [], "R2": [],
    }
    device = FakeDevice()
    controller = SpeedAwareTCodePlaybackController(plan, device, speed=2.0, seek_ramp_ms=120)

    controller.interval_device.send("L05000I200")
    assert device.sent[-1] == "L05000I100"

    controller._sync_position(0.5)
    assert "I120" in device.sent[-1]
    assert "I60" not in device.sent[-1]
