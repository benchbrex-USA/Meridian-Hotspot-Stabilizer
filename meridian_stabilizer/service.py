from __future__ import annotations

import plistlib
import sys
import tempfile
from pathlib import Path

from .constants import PLIST_LABEL, PLIST_PATH, default_state_dir, project_root
from .system import CommandRunner


def build_launchd_plist(profile: str = "calls", interval: int = 60, guardian: bool = False) -> dict[str, object]:
    state_dir = default_state_dir()
    python = Path(sys.executable)
    program_arguments = [
        str(python),
        "-m",
        "meridian_stabilizer",
        "run",
        "--profile",
        profile,
        "--interval",
        str(interval),
    ]
    if guardian:
        program_arguments.append("--guardian")
    return {
        "Label": PLIST_LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(project_root()),
        "EnvironmentVariables": {
            "MERIDIAN_STATE_DIR": str(state_dir),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(state_dir / "service.out.log"),
        "StandardErrorPath": str(state_dir / "service.err.log"),
    }


def install_service(profile: str = "calls", interval: int = 60, runner: CommandRunner | None = None, guardian: bool = False) -> Path:
    runner = runner or CommandRunner()
    state_dir = default_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    plist = build_launchd_plist(profile=profile, interval=interval, guardian=guardian)
    with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
        plistlib.dump(plist, handle)
        temp_path = Path(handle.name)
    try:
        runner.run(["install", "-o", "root", "-g", "wheel", "-m", "644", str(temp_path), str(PLIST_PATH)], privileged=True, timeout=30)
        runner.run(["launchctl", "bootout", "system", str(PLIST_PATH)], privileged=True, check=False, timeout=30)
        runner.run(["launchctl", "bootstrap", "system", str(PLIST_PATH)], privileged=True, timeout=30)
        runner.run(["launchctl", "kickstart", "-k", f"system/{PLIST_LABEL}"], privileged=True, check=False, timeout=30)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return PLIST_PATH


def uninstall_service(runner: CommandRunner | None = None) -> Path:
    runner = runner or CommandRunner()
    runner.run(["launchctl", "bootout", "system", str(PLIST_PATH)], privileged=True, check=False, timeout=30)
    runner.run(["rm", "-f", str(PLIST_PATH)], privileged=True, timeout=30)
    return PLIST_PATH
