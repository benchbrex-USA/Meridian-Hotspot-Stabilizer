from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .constants import ANCHOR, APP_NAME, DOWNLOAD_PIPE, UPLOAD_PIPE
from .database import MetricsDB
from .measurements import RuntimeSnapshot, collect_runtime_snapshot
from .notifier import notification_queue_path, queued_notification_count
from .service import notifier_status, service_status
from .state import StabilizerState, StateStore, utc_now
from .system import Shaper


@dataclass(frozen=True)
class DiagnosticBundle:
    path: Path
    manifest: dict[str, Any]


def create_diagnostic_bundle(
    store: StateStore | None = None,
    db: MetricsDB | None = None,
    output_dir: Path | None = None,
    include_live: bool = False,
    include_system: bool = False,
    target: str = "1.1.1.1",
    limit: int = 50,
) -> DiagnosticBundle:
    store = store or StateStore()
    db = db or MetricsDB()
    output_dir = output_dir or store.state_dir / "bundles"
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = utc_now()
    bundle_name = f"{APP_NAME}-diagnostics-{_stamp(generated_at)}"
    output_path = output_dir / f"{bundle_name}.tar.gz"

    with tempfile.TemporaryDirectory(prefix=f"{bundle_name}-") as tmp:
        root = Path(tmp) / bundle_name
        root.mkdir(parents=True, exist_ok=True)

        state = store.load()
        report = {"state": _redact_state(state), **db.export_report(limit=limit)}
        _write_json(root / "state.redacted.json", _redact_state(state))
        _write_json(root / "metrics-report.json", _redact_report(report))
        _write_json(root / "service-status.json", asdict(service_status()))
        _write_json(root / "notifier-status.json", asdict(notifier_status()))
        _write_json(
            root / "notification-queue.json",
            {
                "path": str(notification_queue_path(store.state_dir)),
                "queued_count": queued_notification_count(store.state_dir),
            },
        )
        _write_json(root / "environment.json", _environment_snapshot())

        live_snapshot: RuntimeSnapshot | None = None
        if include_live:
            live_snapshot = collect_runtime_snapshot(include_quality=True, ping_count=6, target=target)
            _write_json(root / "runtime-snapshot.json", _snapshot_to_dict(live_snapshot))

        if include_system:
            dnctl, pf = Shaper().status_text()
            _write_text(root / "pf-anchor.txt", pf or "")
            _write_text(root / "dummynet-pipes.txt", dnctl or "")

        _copy_if_exists(store.log_file, root / "stabilizer.log")
        _copy_if_exists(store.state_dir / "service.out.log", root / "service.out.log")
        _copy_if_exists(store.state_dir / "service.err.log", root / "service.err.log")
        _copy_if_exists(store.state_dir / "notifier.out.log", root / "notifier.out.log")
        _copy_if_exists(store.state_dir / "notifier.err.log", root / "notifier.err.log")
        _copy_recent_incidents(store.incident_dir, root / "incidents")

        manifest = {
            "bundle": bundle_name,
            "generated_at": generated_at,
            "real_data_only": True,
            "state_dir": str(store.state_dir),
            "database": str(db.path),
            "include_live": include_live,
            "include_system": include_system,
            "target": target if include_live else None,
            "owned_anchor": ANCHOR,
            "owned_pipes": [UPLOAD_PIPE, DOWNLOAD_PIPE],
            "files": sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()),
            "redactions": ["state.pf_token"],
            "live_errors": list(live_snapshot.errors) if live_snapshot else [],
        }
        _write_json(root / "manifest.json", manifest)

        with tarfile.open(output_path, "w:gz") as archive:
            archive.add(root, arcname=bundle_name)

    return DiagnosticBundle(path=output_path, manifest=manifest)


def release_readiness() -> dict[str, Any]:
    tools = ["route", "ping", "networkQuality", "pfctl", "dnctl", "launchctl", "pkgbuild", "productbuild", "xcrun", "codesign"]
    code_signing_identity = _command(["security", "find-identity", "-v", "-p", "codesigning"], timeout=20)
    installer_identity = _command(["security", "find-certificate", "-a", "-c", "Developer ID Installer", "-Z"], timeout=20)
    return {
        "generated_at": utc_now(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "macos": platform.mac_ver()[0] or None,
        "tools": {tool: shutil.which(tool) for tool in tools},
        "developer_id_application_present": "Developer ID Application" in code_signing_identity["stdout"],
        "developer_id_installer_present": installer_identity["returncode"] == 0 and "Developer ID Installer" in installer_identity["stdout"],
        "notarytool_available": shutil.which("xcrun") is not None,
        "signing_identity_check": {
            "returncode": code_signing_identity["returncode"],
            "stderr": code_signing_identity["stderr"],
        },
        "installer_identity_check": {
            "returncode": installer_identity["returncode"],
            "stderr": installer_identity["stderr"],
        },
    }


def render_readiness(payload: dict[str, Any]) -> str:
    lines = [
        "Meridian production readiness",
        f"Generated: {payload['generated_at']}",
        f"macOS: {payload['macos'] or 'unavailable'}",
        f"Python: {payload['python']}",
        "",
        "Required tools:",
    ]
    for tool, path in payload["tools"].items():
        lines.append(f"  {'OK' if path else 'MISS'} {tool}: {path or 'unavailable'}")
    lines.extend(
        [
            "",
            f"Developer ID Application identity: {'available' if payload['developer_id_application_present'] else 'unavailable'}",
            f"Developer ID Installer identity: {'available' if payload['developer_id_installer_present'] else 'unavailable'}",
            f"Notary tooling: {'available' if payload['notarytool_available'] else 'unavailable'}",
        ]
    )
    return "\n".join(lines) + "\n"


def _redact_state(state: StabilizerState) -> dict[str, Any]:
    data = asdict(state)
    if data.get("pf_token"):
        data["pf_token"] = "[redacted]"
    return data


def _redact_report(report: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(report))
    if redacted.get("state", {}).get("pf_token"):
        redacted["state"]["pf_token"] = "[redacted]"
    return redacted


def _snapshot_to_dict(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    return {
        "route": asdict(snapshot.route) if snapshot.route else None,
        "gateway_ping": asdict(snapshot.gateway_ping) if snapshot.gateway_ping else None,
        "internet_ping": asdict(snapshot.internet_ping) if snapshot.internet_ping else None,
        "quality": asdict(snapshot.quality) if snapshot.quality else None,
        "errors": list(snapshot.errors),
    }


def _environment_snapshot() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "platform": platform.platform(),
        "macos": platform.mac_ver()[0] or None,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "commands": {
            "route": shutil.which("route"),
            "ping": shutil.which("ping"),
            "networkQuality": shutil.which("networkQuality"),
            "pfctl": shutil.which("pfctl"),
            "dnctl": shutil.which("dnctl"),
            "launchctl": shutil.which("launchctl"),
        },
    }


def _copy_recent_incidents(source: Path, destination: Path, limit: int = 10) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    files = sorted((path for path in source.iterdir() if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[:limit]:
        shutil.copy2(path, destination / path.name)


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copy2(source, destination)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")


def _stamp(value: str) -> str:
    return value.replace(":", "").replace("+", "Z")


def _command(command: list[str], timeout: int = 10) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except Exception as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)}
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
