from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .health import score_link
from .measurements import RuntimeSnapshot
from .state import StabilizerState, utc_now


@dataclass(frozen=True)
class GuardianPolicy:
    max_loss_percent: float = 5.0
    max_avg_latency_ms: float = 500.0
    max_jitter_ms: float = 250.0
    max_gateway_loss_percent: float = 50.0
    max_consecutive_probe_failures: int = 3


@dataclass(frozen=True)
class GuardianDecision:
    action: str
    severity: str
    reason: str
    evidence: dict[str, Any]
    resolution: list[str]


def evaluate_guardian(snapshot: RuntimeSnapshot, state: StabilizerState, policy: GuardianPolicy, consecutive_failures: int = 0) -> GuardianDecision:
    evidence = _build_evidence(snapshot, state, consecutive_failures)

    if snapshot.route is None and consecutive_failures >= policy.max_consecutive_probe_failures:
        return _shutdown("critical", "default route is unavailable across repeated checks", evidence, _route_resolution())

    if snapshot.internet_ping is None and consecutive_failures >= policy.max_consecutive_probe_failures:
        return _shutdown("critical", "internet probe is unavailable across repeated checks", evidence, _connectivity_resolution())

    if snapshot.gateway_ping and snapshot.gateway_ping.loss_percent >= policy.max_gateway_loss_percent:
        return _shutdown("critical", "gateway packet loss indicates the Mac-to-phone link is unstable", evidence, _gateway_resolution())

    if snapshot.internet_ping:
        ping = snapshot.internet_ping
        if ping.loss_percent >= policy.max_loss_percent:
            return _shutdown("critical", f"internet packet loss reached {ping.loss_percent:.1f}%", evidence, _connectivity_resolution())
        if ping.avg_ms is not None and ping.avg_ms >= policy.max_avg_latency_ms:
            return _shutdown("high", f"average internet latency reached {ping.avg_ms:.1f} ms", evidence, _latency_resolution())
        if ping.stddev_ms is not None and ping.stddev_ms >= policy.max_jitter_ms:
            return _shutdown("high", f"internet jitter reached {ping.stddev_ms:.1f} ms", evidence, _latency_resolution())

    health = score_link(snapshot.internet_ping, snapshot.quality)
    return GuardianDecision(
        action="continue",
        severity="normal",
        reason=f"guardian checks passed; stability is {health.label}",
        evidence=evidence,
        resolution=["No shutdown needed. Continue monitoring real measurements."],
    )


def write_incident_report(incident_dir: Path, decision: GuardianDecision, snapshot: RuntimeSnapshot, state: StabilizerState) -> tuple[Path, Path]:
    incident_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_now().replace(":", "").replace("+", "Z")
    base = incident_dir / f"incident-{ts}"
    payload = {
        "generated_at": utc_now(),
        "decision": asdict(decision),
        "state": asdict(state),
        "snapshot": _snapshot_to_dict(snapshot),
    }
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_incident_markdown(payload), encoding="utf-8")
    return md_path, json_path


def _shutdown(severity: str, reason: str, evidence: dict[str, Any], resolution: list[str]) -> GuardianDecision:
    return GuardianDecision(action="shutdown", severity=severity, reason=reason, evidence=evidence, resolution=resolution)


def _build_evidence(snapshot: RuntimeSnapshot, state: StabilizerState, consecutive_failures: int) -> dict[str, Any]:
    return {
        "active": state.active,
        "profile": state.profile,
        "state_interface": state.interface,
        "state_gateway": state.gateway,
        "route_interface": snapshot.route.interface if snapshot.route else None,
        "route_gateway": snapshot.route.gateway if snapshot.route else None,
        "gateway_loss_percent": snapshot.gateway_ping.loss_percent if snapshot.gateway_ping else None,
        "gateway_avg_ms": snapshot.gateway_ping.avg_ms if snapshot.gateway_ping else None,
        "internet_loss_percent": snapshot.internet_ping.loss_percent if snapshot.internet_ping else None,
        "internet_avg_ms": snapshot.internet_ping.avg_ms if snapshot.internet_ping else None,
        "internet_jitter_ms": snapshot.internet_ping.stddev_ms if snapshot.internet_ping else None,
        "internet_max_ms": snapshot.internet_ping.max_ms if snapshot.internet_ping else None,
        "probe_errors": list(snapshot.errors),
        "consecutive_probe_failures": consecutive_failures,
    }


def _snapshot_to_dict(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    return {
        "route": asdict(snapshot.route) if snapshot.route else None,
        "gateway_ping": asdict(snapshot.gateway_ping) if snapshot.gateway_ping else None,
        "internet_ping": asdict(snapshot.internet_ping) if snapshot.internet_ping else None,
        "quality": asdict(snapshot.quality) if snapshot.quality else None,
        "errors": list(snapshot.errors),
    }


def _render_incident_markdown(payload: dict[str, Any]) -> str:
    decision = payload["decision"]
    evidence = decision["evidence"]
    lines = [
        "# Meridian Guardian Incident",
        "",
        f"Generated: {payload['generated_at']}",
        f"Action: {decision['action']}",
        f"Severity: {decision['severity']}",
        f"Reason: {decision['reason']}",
        "",
        "## What Happened",
        f"Meridian Guardian detected `{decision['reason']}` from real local measurements and selected `{decision['action']}`.",
        "",
        "## Evidence",
    ]
    for key, value in evidence.items():
        lines.append(f"- {key}: {value if value is not None else 'unavailable'}")
    lines.extend(["", "## Resolution Plan"])
    lines.extend(f"- {item}" for item in decision["resolution"])
    lines.extend(["", "## Raw Snapshot", "```json", json.dumps(payload["snapshot"], indent=2, sort_keys=True), "```"])
    return "\n".join(lines) + "\n"


def _route_resolution() -> list[str]:
    return [
        "Confirm the phone hotspot is still connected and the Mac has a default route.",
        "Reconnect Wi-Fi or USB hotspot if the route is missing.",
        "Run `python3 -m meridian_stabilizer preflight` before starting again.",
    ]


def _connectivity_resolution() -> list[str]:
    return [
        "Move the phone to stronger signal or reduce competing devices on the hotspot.",
        "Check whether the carrier link is congested or temporarily offline.",
        "Run `python3 -m meridian_stabilizer doctor --profile calls` after the link recovers.",
    ]


def _gateway_resolution() -> list[str]:
    return [
        "The Mac-to-phone hop is unstable; keep the phone near the Mac or use USB tethering.",
        "Disable/re-enable the hotspot if gateway packet loss continues.",
        "Restart Meridian only after gateway latency and loss look stable.",
    ]


def _latency_resolution() -> list[str]:
    return [
        "The link is showing severe bufferbloat or cellular congestion.",
        "Wait for latency to settle, then restart with a lower upload cap.",
        "Use `python3 -m meridian_stabilizer start --profile calls --upload-mbps 5 --download-mbps 15` if instability repeats.",
    ]

