"""Windows release builder used by GitHub Actions."""
from __future__ import annotations

import subprocess
import sys


def main():
    print("Fetching FFmpeg binary...")
    subprocess.check_call([sys.executable, "scripts/fetch_binaries.py"])

    print("Building executable...")
    subprocess.check_call([
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "qt.spec",
    ])
    print("Done!")


if __name__ == "__main__":
    main()
