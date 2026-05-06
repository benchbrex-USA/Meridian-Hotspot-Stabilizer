from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .constants import ANCHOR, DOWNLOAD_PIPE, UPLOAD_PIPE
from .policy import Caps


class SystemCommandError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"{' '.join(command)} exited with {returncode}: {stderr.strip() or stdout.strip()}")


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, dry_run: bool = False, auto_sudo: bool = True) -> None:
        self.dry_run = dry_run
        self.auto_sudo = auto_sudo
        self.commands: list[list[str]] = []

    def run(
        self,
        command: list[str],
        privileged: bool = False,
        timeout: int = 30,
        check: bool = True,
        execute_during_dry_run: bool = False,
    ) -> CommandResult:
        effective = self._effective_command(command, privileged)
        self.commands.append(effective)
        if self.dry_run and not execute_during_dry_run:
            return CommandResult(effective, stdout="", stderr="")
        completed = subprocess.run(effective, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        if check and completed.returncode != 0:
            raise SystemCommandError(effective, completed.returncode, completed.stdout, completed.stderr)
        return CommandResult(effective, completed.stdout, completed.stderr)

    def _effective_command(self, command: list[str], privileged: bool) -> list[str]:
        if privileged and self.auto_sudo and os.geteuid() != 0:
            return ["/usr/bin/sudo", *command]
        return command


class Shaper:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def apply(self, interface: str, caps: Caps, existing_pf_token: str | None = None) -> str | None:
        validate_interface_name(interface)
        validate_caps(caps)
        self._dry_run_rules(interface, caps)

        pf_token = existing_pf_token
        if not pf_token:
            result = self.runner.run(["pfctl", "-E"], privileged=True, timeout=20)
            pf_token = parse_pf_token(result.stdout + result.stderr)

        try:
            self._configure_pipes(caps)
            self._load_anchor(interface)
        except Exception:
            if not existing_pf_token and pf_token:
                self.runner.run(["pfctl", "-X", pf_token], privileged=True, check=False, timeout=20)
            raise
        return pf_token

    def clear(self, pf_token: str | None = None) -> None:
        self.runner.run(["pfctl", "-a", ANCHOR, "-F", "all"], privileged=True, check=False, timeout=20)
        self.runner.run(["dnctl", "-q", "pipe", "delete", str(UPLOAD_PIPE), str(DOWNLOAD_PIPE)], privileged=True, check=False, timeout=20)
        if pf_token:
            self.runner.run(["pfctl", "-X", pf_token], privileged=True, check=False, timeout=20)

    def status_text(self) -> tuple[str | None, str | None]:
        dnctl = self.runner.run(["dnctl", "pipe", "show", str(UPLOAD_PIPE), str(DOWNLOAD_PIPE)], privileged=True, check=False, timeout=20)
        pf = self.runner.run(["pfctl", "-a", ANCHOR, "-sr"], privileged=True, check=False, timeout=20)
        return dnctl.stdout.strip() or dnctl.stderr.strip(), pf.stdout.strip() or pf.stderr.strip()

    def _dry_run_rules(self, interface: str, caps: Caps) -> None:
        rules = build_pf_rules(interface)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(rules)
            rule_path = Path(handle.name)
        try:
            self.runner.run(
                ["dnctl", "-n", "pipe", str(UPLOAD_PIPE), "config", "bw", format_mbit(caps.upload_mbps), "queue", "50"],
                timeout=20,
                execute_during_dry_run=True,
            )
            self.runner.run(
                ["dnctl", "-n", "pipe", str(DOWNLOAD_PIPE), "config", "bw", format_mbit(caps.download_mbps), "queue", "100"],
                timeout=20,
                execute_during_dry_run=True,
            )
            self.runner.run(["pfctl", "-a", ANCHOR, "-n", "-f", str(rule_path)], timeout=20, execute_during_dry_run=True)
        finally:
            try:
                rule_path.unlink()
            except FileNotFoundError:
                pass

    def _configure_pipes(self, caps: Caps) -> None:
        self.runner.run(["dnctl", "pipe", str(UPLOAD_PIPE), "config", "bw", format_mbit(caps.upload_mbps), "queue", "50"], privileged=True, timeout=20)
        self.runner.run(["dnctl", "pipe", str(DOWNLOAD_PIPE), "config", "bw", format_mbit(caps.download_mbps), "queue", "100"], privileged=True, timeout=20)

    def _load_anchor(self, interface: str) -> None:
        rules = build_pf_rules(interface)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(rules)
            rule_path = Path(handle.name)
        try:
            self.runner.run(["pfctl", "-a", ANCHOR, "-f", str(rule_path)], privileged=True, timeout=20)
        finally:
            try:
                rule_path.unlink()
            except FileNotFoundError:
                pass


def build_pf_rules(interface: str) -> str:
    validate_interface_name(interface)
    return (
        f"# {ANCHOR}: generated by Meridian Hotspot Stabilizer\n"
        f"dummynet out quick on {interface} all pipe {UPLOAD_PIPE}\n"
        f"dummynet in quick on {interface} all pipe {DOWNLOAD_PIPE}\n"
    )


def validate_interface_name(interface: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
        raise ValueError(f"unsafe interface name: {interface!r}")


def validate_caps(caps: Caps) -> None:
    for name, value in (("upload", caps.upload_mbps), ("download", caps.download_mbps)):
        if value <= 0:
            raise ValueError(f"{name} cap must be positive")
        if value > 10_000:
            raise ValueError(f"{name} cap is unreasonably high: {value} Mbps")


def parse_pf_token(output: str) -> str | None:
    match = re.search(r"Token\s*:\s*(?P<token>\S+)", output)
    return match.group("token") if match else None


def format_mbit(value: float) -> str:
    return f"{value:.3f}Mbit/s"
