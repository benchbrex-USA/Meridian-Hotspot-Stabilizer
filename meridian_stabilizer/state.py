from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import default_state_dir


@dataclass
class StabilizerState:
    active: bool = False
    profile: str = "calls"
    interface: str | None = None
    gateway: str | None = None
    upload_cap_mbps: float | None = None
    download_cap_mbps: float | None = None
    measured_upload_mbps: float | None = None
    measured_download_mbps: float | None = None
    pf_token: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    last_action: str | None = None
    last_gateway_avg_ms: float | None = None
    last_gateway_jitter_ms: float | None = None
    last_latency_avg_ms: float | None = None
    last_jitter_ms: float | None = None
    last_loss_percent: float | None = None
    run_pid: int | None = None
    heartbeat_at: str | None = None
    stopped_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StabilizerState":
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in allowed})


class StateStore:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or default_state_dir()
        self.state_file = self.state_dir / "state.json"
        self.log_file = self.state_dir / "stabilizer.log"
        self.incident_dir = self.state_dir / "incidents"

    def ensure_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> StabilizerState:
        if not self.state_file.exists():
            return StabilizerState()
        with self.state_file.open("r", encoding="utf-8") as handle:
            return StabilizerState.from_dict(json.load(handle))

    def save(self, state: StabilizerState) -> None:
        self.ensure_dir()
        state.updated_at = utc_now()
        tmp = self.state_file.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.replace(self.state_file)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
