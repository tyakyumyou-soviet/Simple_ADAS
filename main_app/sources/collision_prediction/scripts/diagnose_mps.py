from __future__ import annotations

import platform
import subprocess
import sys

import torch


def _run(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, stderr=subprocess.STDOUT).decode().strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def main() -> None:
    print("machine:", platform.machine())
    print("python exec:", sys.executable)
    print("python file:", _run(["file", sys.executable]))
    print("arch:", _run(["arch"]))
    print("torch:", torch.__version__)
    print("MPS built:", torch.backends.mps.is_built())
    print("MPS available:", torch.backends.mps.is_available())
    print("macOS:", platform.mac_ver()[0])
    try:
        tensor = torch.tensor([1.0], device="mps")
        print("MPS tensor OK:", tensor)
    except Exception as exc:
        print("MPS tensor FAIL:", repr(exc))


if __name__ == "__main__":
    main()
