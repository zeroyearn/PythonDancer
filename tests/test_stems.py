from pathlib import Path

from dancer import stems


def test_find_stem_files_prefers_complete_direct_directory(tmp_path):
    for name in stems.STEM_NAMES:
        (tmp_path / f"{name}.wav").write_bytes(b"stub")
    found = stems.find_stem_files(tmp_path)
    assert set(found) == set(stems.STEM_NAMES)
    assert all(path.parent == tmp_path for path in found.values())


def test_stem_mode_off_is_noop_with_status():
    data = {"beats": [0.5, 1.0], "energy": [0.2, 0.4]}
    enriched = stems.enrich_with_stems(data, "missing.wav", mode="off")
    assert enriched["energy"] == data["energy"]
    assert enriched["stem_analysis"]["status"] == "off"


def test_auto_mode_gracefully_falls_back_without_demucs(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "demucs_available", lambda: False)
    enriched = stems.enrich_with_stems({"beats": [0.5]}, tmp_path / "song.wav", mode="auto")
    assert enriched["stem_analysis"]["status"] == "unavailable"
    assert set(enriched["stem_analysis"]["missing"]) == set(stems.STEM_NAMES)


def test_required_mode_fails_without_stems_or_demucs(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "demucs_available", lambda: False)
    try:
        stems.enrich_with_stems({"beats": [0.5]}, tmp_path / "song.wav", mode="required")
    except RuntimeError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("required stem mode should fail when stems are unavailable")
