from __future__ import annotations

import plistlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .constants import NOTIFIER_PLIST_LABEL, NOTIFIER_PLIST_PATH, PLIST_LABEL, PLIST_PATH, default_state_dir, project_root
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
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ExitTimeOut": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(state_dir / "service.out.log"),
        "StandardErrorPath": str(state_dir / "service.err.log"),
    }


def build_notifier_launchd_plist(interval: int = 5) -> dict[str, object]:
    state_dir = default_state_dir()
    python = Path(sys.executable)
    return {
        "Label": NOTIFIER_PLIST_LABEL,
        "ProgramArguments": [
            str(python),
            "-m",
            "meridian_stabilizer",
            "notify-drain",
            "--watch",
            "--interval",
            str(max(2, interval)),
        ],
        "WorkingDirectory": str(project_root()),
        "EnvironmentVariables": {
            "MERIDIAN_STATE_DIR": str(state_dir),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ExitTimeOut": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(state_dir / "notifier.out.log"),
        "StandardErrorPath": str(state_dir / "notifier.err.log"),
    }


def install_service(profile: str = "calls", interval: int = 60, runner: CommandRunner | None = None, guardian: bool = False) -> Path:
    runner = runner or CommandRunner()
    state_dir = default_state_dir()
    if not runner.dry_run:
        state_dir.mkdir(parents=True, exist_ok=True)
    plist = build_launchd_plist(profile=profile, interval=interval, guardian=guardian)
    with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
        plistlib.dump(plist, handle)
        temp_path = Path(handle.name)
    try:
        runner.run(["install", "-o", "root", "-g", "wheel", "-m", "644", str(temp_path), str(PLIST_PATH)], privileged=True, timeout=30)
        runner.run(["launchctl", "bootout", "system", str(PLIST_PATH)], privileged=True, check=False, timeout=30)
        runner.run(["launchctl", "bootstrap", "system", str(PLIST_PATH)], privileged=True, timeout=30)
        runner.run(["launchctl", "enable", f"system/{PLIST_LABEL}"], privileged=True, check=False, timeout=30)
        runner.run(["launchctl", "kickstart", "-k", f"system/{PLIST_LABEL}"], privileged=True, check=False, timeout=30)
        runner.run(["launchctl", "print", f"system/{PLIST_LABEL}"], privileged=True, check=False, timeout=30)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return PLIST_PATH


def uninstall_service(runner: CommandRunner | None = None) -> Path:
    runner = runner or CommandRunner()
    runner.run(["launchctl", "bootout", "system", str(PLIST_PATH)], privileged=True, check=False, timeout=30)
    runner.run(["launchctl", "disable", f"system/{PLIST_LABEL}"], privileged=True, check=False, timeout=30)
    runner.run(["rm", "-f", str(PLIST_PATH)], privileged=True, timeout=30)
    return PLIST_PATH


def install_notifier(interval: int = 5, runner: CommandRunner | None = None) -> Path:
    runner = runner or CommandRunner()
    state_dir = default_state_dir()
    if not runner.dry_run:
        state_dir.mkdir(parents=True, exist_ok=True)
        NOTIFIER_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist = build_notifier_launchd_plist(interval=interval)
    with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
        plistlib.dump(plist, handle)
        temp_path = Path(handle.name)
    try:
        runner.run(["install", "-m", "644", str(temp_path), str(NOTIFIER_PLIST_PATH)], timeout=30)
        runner.run(["launchctl", "bootout", "gui/%s" % _uid(), str(NOTIFIER_PLIST_PATH)], check=False, timeout=30)
        runner.run(["launchctl", "bootstrap", "gui/%s" % _uid(), str(NOTIFIER_PLIST_PATH)], timeout=30)
        runner.run(["launchctl", "enable", f"gui/{_uid()}/{NOTIFIER_PLIST_LABEL}"], check=False, timeout=30)
        runner.run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{NOTIFIER_PLIST_LABEL}"], check=False, timeout=30)
        runner.run(["launchctl", "print", f"gui/{_uid()}/{NOTIFIER_PLIST_LABEL}"], check=False, timeout=30)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return NOTIFIER_PLIST_PATH


def uninstall_notifier(runner: CommandRunner | None = None) -> Path:
    runner = runner or CommandRunner()
    runner.run(["launchctl", "bootout", "gui/%s" % _uid(), str(NOTIFIER_PLIST_PATH)], check=False, timeout=30)
    runner.run(["launchctl", "disable", f"gui/{_uid()}/{NOTIFIER_PLIST_LABEL}"], check=False, timeout=30)
    runner.run(["rm", "-f", str(NOTIFIER_PLIST_PATH)], timeout=30)
    return NOTIFIER_PLIST_PATH


@dataclass(frozen=True)
class LaunchdStatus:
    label: str
    domain: str
    plist_path: str
    plist_exists: bool
    print_returncode: int
    state: str | None
    pid: int | None
    last_exit_code: int | None
    runs: int | None
    stdout: str
    stderr: str


def service_status() -> LaunchdStatus:
    return _launchd_status(PLIST_LABEL, "system", PLIST_PATH)


def notifier_status() -> LaunchdStatus:
    return _launchd_status(NOTIFIER_PLIST_LABEL, f"gui/{_uid()}", NOTIFIER_PLIST_PATH)


def _launchd_status(label: str, domain: str, plist_path: Path) -> LaunchdStatus:
    try:
        completed = subprocess.run(["launchctl", "print", f"{domain}/{label}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    except Exception as exc:
        return LaunchdStatus(
            label=label,
            domain=domain,
            plist_path=str(plist_path),
            plist_exists=plist_path.exists(),
            print_returncode=1,
            state=None,
            pid=None,
            last_exit_code=None,
            runs=None,
            stdout="",
            stderr=str(exc),
        )
    return LaunchdStatus(
        label=label,
        domain=domain,
        plist_path=str(plist_path),
        plist_exists=plist_path.exists(),
        print_returncode=completed.returncode,
        state=_extract_text(completed.stdout, "state"),
        pid=_extract_int(completed.stdout, "pid"),
        last_exit_code=_extract_int(completed.stdout, "last exit code"),
        runs=_extract_int(completed.stdout, "runs"),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _extract_text(output: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", output, flags=re.MULTILINE)
    return match.group(1) if match else None


def _extract_int(output: str, key: str) -> int | None:
    value = _extract_text(output, key)
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else None


def _uid() -> str:
    return str(os.getuid())
