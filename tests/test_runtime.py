from pathlib import Path

from dancer import runtime


def test_bundled_binary_prefers_meipass(tmp_path, monkeypatch):
    binary = tmp_path / ("ffmpeg.exe" if runtime.os.name == "nt" else "ffmpeg")
    binary.write_bytes(b"fake")
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(tmp_path), raising=False)

    found = runtime.bundled_binary("ffmpeg")
    assert found == binary
    assert runtime.command_path("ffmpeg") == str(binary)


def test_prepare_runtime_path_prepends_bundle_root(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PATH", "/existing/path")

    runtime.prepare_runtime_path()

    entries = runtime.os.environ["PATH"].split(runtime.os.pathsep)
    assert entries[0] == str(tmp_path)
    assert "/existing/path" in entries
