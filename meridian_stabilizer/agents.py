from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from typing import Any

from .database import MetricsDB
from .measurements import RuntimeSnapshot, collect_runtime_snapshot
from .state import StabilizerState, utc_now


@dataclass(frozen=True)
class AgentProvider:
    name: str
    executable: str
    auth_model: str
    installed: bool
    path: str | None


PROVIDER_SPECS = {
    "codex": ("codex", "user-managed Codex CLI/account session"),
    "claude": ("claude", "user-managed Claude Code CLI/account session"),
}

SAFETY_BOUNDARIES = [
    "Meridian does not log into provider accounts.",
    "Meridian does not store provider passwords, API keys, or tokens.",
    "Meridian does not send metrics to a remote service from this codebase.",
    "Agent context is built from real local measurements and stored real events only.",
    "Agent-initiated shaping must still go through start, tune, stop, or panic.",
]

ALLOWED_AGENT_WORK = [
    "inspect local diagnostics",
    "explain cap changes from measured fields",
    "summarize local events",
    "prepare diagnostic context",
    "recommend bounded Meridian CLI commands",
]


def detect_providers(provider: str = "all") -> list[AgentProvider]:
    names = sorted(PROVIDER_SPECS) if provider == "all" else [provider]
    providers: list[AgentProvider] = []
    for name in names:
        executable, auth_model = PROVIDER_SPECS[name]
        path = shutil.which(executable)
        providers.append(AgentProvider(name=name, executable=executable, auth_model=auth_model, installed=path is not None, path=path))
    return providers


def build_agent_context(
    state: StabilizerState,
    db: MetricsDB,
    provider: str = "all",
    include_live: bool = True,
    target: str = "1.1.1.1",
) -> dict[str, Any]:
    live_snapshot = collect_runtime_snapshot(include_quality=False, ping_count=4, target=target) if include_live else None
    latest = db.latest_sample()
    return {
        "generated_at": utc_now(),
        "product": "Meridian Hotspot Stabilizer",
        "provider": provider,
        "provider_detection": [asdict(item) for item in detect_providers(provider)],
        "safety_boundaries": SAFETY_BOUNDARIES,
        "allowed_agent_work": ALLOWED_AGENT_WORK,
        "state": asdict(state),
        "latest_sample": asdict(latest) if latest else None,
        "recent_samples": [asdict(sample) for sample in db.recent_samples(limit=5)],
        "recent_events": [asdict(event) for event in db.recent_events(limit=10)],
        "live_snapshot": _snapshot_to_dict(live_snapshot) if live_snapshot else None,
    }


def render_agent_context_markdown(context: dict[str, Any]) -> str:
    lines = [
        "# Meridian Agent Context",
        "",
        f"Generated: {context['generated_at']}",
        f"Provider target: {context['provider']}",
        "",
        "## Provider Detection",
    ]
    for provider in context["provider_detection"]:
        status = "installed" if provider["installed"] else "not installed"
        path = provider["path"] or "unavailable"
        lines.append(f"- {provider['name']}: {status}; executable `{provider['executable']}`; path `{path}`; auth `{provider['auth_model']}`")

    lines.extend(["", "## Safety Boundaries"])
    lines.extend(f"- {item}" for item in context["safety_boundaries"])

    lines.extend(["", "## Allowed Agent Work"])
    lines.extend(f"- {item}" for item in context["allowed_agent_work"])

    state = context["state"]
    lines.extend(
        [
            "",
            "## Current State",
            f"- active: {state['active']}",
            f"- profile: {state['profile']}",
            f"- interface: {state['interface'] or 'unavailable'}",
            f"- gateway: {state['gateway'] or 'unavailable'}",
            f"- upload cap Mbps: {_fmt(state['upload_cap_mbps'])}",
            f"- download cap Mbps: {_fmt(state['download_cap_mbps'])}",
            f"- last action: {state['last_action'] or 'none'}",
        ]
    )

    live = context["live_snapshot"]
    lines.extend(["", "## Live Snapshot"])
    if live:
        lines.extend(
            [
                f"- interface: {live['route']['interface'] if live['route'] else 'unavailable'}",
                f"- gateway: {live['route']['gateway'] if live['route'] else 'unavailable'}",
                f"- gateway ping avg ms: {_nested_fmt(live, 'gateway_ping', 'avg_ms')}",
                f"- internet ping avg ms: {_nested_fmt(live, 'internet_ping', 'avg_ms')}",
                f"- internet jitter ms: {_nested_fmt(live, 'internet_ping', 'stddev_ms')}",
                f"- internet loss percent: {_nested_fmt(live, 'internet_ping', 'loss_percent')}",
            ]
        )
        if live["errors"]:
            lines.append("- unavailable data: " + "; ".join(live["errors"]))
    else:
        lines.append("- live collection disabled")

    lines.extend(["", "## Latest Stored Sample"])
    latest = context["latest_sample"]
    if latest:
        lines.extend(
            [
                f"- timestamp: {latest['ts']}",
                f"- stability: {_fmt(latest['stability_score'])} ({latest['stability_label']})",
                f"- internet avg ms: {_fmt(latest['internet_avg_ms'])}",
                f"- internet jitter ms: {_fmt(latest['internet_jitter_ms'])}",
                f"- loss percent: {_fmt(latest['loss_percent'])}",
            ]
        )
    else:
        lines.append("- unavailable")

    lines.extend(["", "## Raw JSON", "```json", json.dumps(context, indent=2, sort_keys=True), "```"])
    return "\n".join(lines) + "\n"


def _snapshot_to_dict(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    return {
        "route": asdict(snapshot.route) if snapshot.route else None,
        "gateway_ping": asdict(snapshot.gateway_ping) if snapshot.gateway_ping else None,
        "internet_ping": asdict(snapshot.internet_ping) if snapshot.internet_ping else None,
        "quality": asdict(snapshot.quality) if snapshot.quality else None,
        "errors": list(snapshot.errors),
    }


def _fmt(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def _nested_fmt(data: dict[str, Any], section: str, key: str) -> str:
    nested = data.get(section)
    if not nested:
        return "unavailable"
    return _fmt(nested.get(key))

