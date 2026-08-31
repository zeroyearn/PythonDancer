import asyncio

import dancer.outputs as outputs
from dancer.outputs import DEFAULT_INTIFACE_ADDRESS, intiface_frames


def test_intiface_frames_map_l0_motion_and_r0_rotation():
    plan = {
        "L0": [(0, 0), (1, 100), (2, 50)],
        "L1": [], "L2": [],
        "R0": [(0, 50), (1, 100), (2, 50)],
        "R1": [], "R2": [],
    }
    frames = intiface_frames(plan)
    assert DEFAULT_INTIFACE_ADDRESS.endswith(":12345")
    assert len(frames) == 3
    assert frames[0][2] == 0.0
    assert frames[1][2] == 1.0
    assert frames[1][4] == 1.0
    assert all(0 <= frame[3] <= 1 for frame in frames)


def test_intiface_soft_start_moves_to_start_pose_before_normal_outputs(monkeypatch):
    class OutputType:
        POSITION_WITH_DURATION = "position"
        VIBRATE = "vibrate"
        ROTATE = "rotate"

    class Command:
        def __init__(self, output_type, value, duration=None):
            self.output_type = output_type
            self.value = value
            self.duration = duration

    class Device:
        def __init__(self):
            self.name = "Fake"
            self.commands = []
            self.stop_count = 0

        def has_output(self, _kind):
            return True

        async def run_output(self, command):
            self.commands.append(command)

        async def stop(self):
            self.stop_count += 1

    class Client:
        last = None

        def __init__(self, _name):
            self.device = Device()
            self.devices = {7: self.device}
            self.disconnected = False
            Client.last = self

        async def connect(self, _address):
            return None

        async def disconnect(self):
            self.disconnected = True

        async def start_scanning(self):
            return None

        async def stop_scanning(self):
            return None

    monkeypatch.setattr(outputs, "_imports", lambda: (Client, Command, OutputType))
    plan = {
        "L0": [(0.0, 80.0), (0.01, 20.0)],
        "L1": [], "L2": [],
        "R0": [(0.0, 75.0), (0.01, 25.0)],
        "R1": [], "R2": [],
    }
    asyncio.run(outputs.play_plan_intiface(plan, device_index=7, soft_start_ms=1))

    device = Client.last.device
    assert device.commands[0].output_type == OutputType.POSITION_WITH_DURATION
    assert device.commands[0].value == 0.8
    assert device.commands[0].duration == 20  # protocol minimum duration
    assert device.commands[1].output_type == OutputType.VIBRATE
    assert device.commands[1].value == 0.0
    assert device.commands[2].output_type == OutputType.ROTATE
    assert device.commands[2].value == 0.0
    assert any(cmd.output_type == OutputType.VIBRATE and cmd.value > 0 for cmd in device.commands[3:])
    assert device.stop_count >= 1
    assert Client.last.disconnected is True
