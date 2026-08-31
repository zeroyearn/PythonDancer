"""Runtime helpers for frozen desktop builds."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    executable = Path(sys.executable).resolve()
    roots.append(executable.parent)

    # macOS app bundle locations. PyInstaller may place collected binaries in
    # Contents/Frameworks while the launcher itself lives in Contents/MacOS.
    if executable.parent.name == "MacOS":
        contents = executable.parent.parent
        roots.extend((contents / "Frameworks", contents / "Resources"))

    # Development/build-tree conveniences.
    package_root = Path(__file__).resolve().parent.parent
    roots.extend((package_root / "dist", package_root / "bin"))

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def bundled_binary(name: str) -> Path | None:
    """Return a bundled executable path when present, otherwise PATH lookup."""
    names = [name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        names.insert(0, name + ".exe")

    for root in _candidate_roots():
        for candidate_name in names:
            candidate = root / candidate_name
            if candidate.is_file():
                return candidate

    found = shutil.which(name)
    return Path(found) if found else None


def command_path(name: str) -> str:
    path = bundled_binary(name)
    return str(path) if path else name


def prepare_runtime_path() -> None:
    """Prepend frozen bundle binary directories to PATH."""
    directories = [str(root) for root in _candidate_roots() if root.exists()]
    if not directories:
        return
    current = os.environ.get("PATH", "")
    existing = current.split(os.pathsep) if current else []
    ordered = directories + [item for item in existing if item not in directories]
    os.environ["PATH"] = os.pathsep.join(ordered)
