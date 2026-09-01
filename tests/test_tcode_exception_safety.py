from dancer.tcode import SerialTCodeDevice


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []
        self.closed = False

    def write(self, payload):
        self.writes.append(payload)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        self.is_open = False


def test_serial_context_sends_dstop_before_exceptional_close():
    device = SerialTCodeDevice("fake")
    device.serial = FakeSerial()

    device.__exit__(RuntimeError, RuntimeError("boom"), None)

    assert device.serial.writes == [b"DSTOP\n"]
    assert device.serial.closed is True


def test_serial_context_normal_exit_only_closes():
    device = SerialTCodeDevice("fake")
    device.serial = FakeSerial()

    device.__exit__(None, None, None)

    assert device.serial.writes == []
    assert device.serial.closed is True
