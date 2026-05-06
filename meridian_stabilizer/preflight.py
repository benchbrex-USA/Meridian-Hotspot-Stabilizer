from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass

from .measurements import collect_runtime_snapshot
from .policy import initial_caps
from .system import CommandRunner, Shaper


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run_preflight() -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    checks.append(
        PreflightCheck(
            name="macOS",
            ok=platform.system() == "Darwin",
            detail=f"platform={platform.system()} release={platform.release()}",
        )
    )

    for command in ("route", "ping", "networkQuality", "pfctl", "dnctl", "launchctl"):
        path = shutil.which(command)
        checks.append(PreflightCheck(name=f"command:{command}", ok=path is not None, detail=path or "not found", required=command not in {"networkQuality", "launchctl"}))

    snapshot = collect_runtime_snapshot(include_quality=False, ping_count=2)
    checks.append(
        PreflightCheck(
            name="default-route",
            ok=snapshot.route is not None,
            detail=f"interface={snapshot.route.interface} gateway={snapshot.route.gateway}" if snapshot.route else "; ".join(snapshot.errors) or "unavailable",
        )
    )
    checks.append(
        PreflightCheck(
            name="internet-ping",
            ok=snapshot.internet_ping is not None and snapshot.internet_ping.received > 0,
            detail=_ping_detail(snapshot.internet_ping) if snapshot.internet_ping else "; ".join(snapshot.errors) or "unavailable",
            required=False,
        )
    )

    if snapshot.route:
        try:
            Shaper(CommandRunner(dry_run=True, auto_sudo=False)).apply(snapshot.route.interface, initial_caps(None))
            checks.append(PreflightCheck(name="pf-dnctl-syntax", ok=True, detail="generated dummynet rules parse successfully"))
        except Exception as exc:
            checks.append(PreflightCheck(name="pf-dnctl-syntax", ok=False, detail=str(exc)))

    return checks


def preflight_ok(checks: list[PreflightCheck]) -> bool:
    return all(check.ok for check in checks if check.required)


def _ping_detail(ping: object | None) -> str:
    if ping is None:
        return "unavailable"
    return f"avg={ping.avg_ms}ms loss={ping.loss_percent}%"

