from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .constants import default_state_dir
from .health import score_link
from .parsers import NetworkQuality, PingStats, RouteInfo
from .state import StabilizerState, utc_now


@dataclass(frozen=True)
class StoredEvent:
    ts: str
    kind: str
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class StoredSample:
    ts: str
    interface: str | None
    gateway: str | None
    profile: str
    active: bool
    upload_cap_mbps: float | None
    download_cap_mbps: float | None
    measured_upload_mbps: float | None
    measured_download_mbps: float | None
    gateway_avg_ms: float | None
    gateway_jitter_ms: float | None
    internet_avg_ms: float | None
    internet_jitter_ms: float | None
    internet_max_ms: float | None
    loss_percent: float | None
    upload_responsiveness: str | None
    download_responsiveness: str | None
    stability_score: int | None
    stability_label: str


class MetricsDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (default_state_dir() / "metrics.sqlite3")

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                create table if not exists events (
                    id integer primary key autoincrement,
                    ts text not null,
                    kind text not null,
                    message text not null,
                    data_json text not null
                );
                create index if not exists idx_events_ts on events(ts);

                create table if not exists samples (
                    id integer primary key autoincrement,
                    ts text not null,
                    interface text,
                    gateway text,
                    profile text not null,
                    active integer not null,
                    upload_cap_mbps real,
                    download_cap_mbps real,
                    measured_upload_mbps real,
                    measured_download_mbps real,
                    gateway_avg_ms real,
                    gateway_jitter_ms real,
                    internet_avg_ms real,
                    internet_jitter_ms real,
                    internet_max_ms real,
                    loss_percent real,
                    upload_responsiveness text,
                    download_responsiveness text,
                    stability_score integer,
                    stability_label text not null
                );
                create index if not exists idx_samples_ts on samples(ts);
                """
            )

    def record_event(self, kind: str, message: str, data: dict[str, Any] | None = None) -> StoredEvent:
        self.initialize()
        event = StoredEvent(ts=utc_now(), kind=kind, message=message, data=data or {})
        with self._connect() as con:
            con.execute(
                "insert into events(ts, kind, message, data_json) values (?, ?, ?, ?)",
                (event.ts, event.kind, event.message, json.dumps(event.data, sort_keys=True)),
            )
        return event

    def record_sample(
        self,
        state: StabilizerState,
        route: RouteInfo | None,
        gateway_ping: PingStats | None,
        internet_ping: PingStats | None,
        quality: NetworkQuality | None,
    ) -> StoredSample:
        self.initialize()
        health = score_link(internet_ping, quality)
        sample = StoredSample(
            ts=utc_now(),
            interface=(route.interface if route else state.interface),
            gateway=(route.gateway if route else state.gateway),
            profile=state.profile,
            active=state.active,
            upload_cap_mbps=state.upload_cap_mbps,
            download_cap_mbps=state.download_cap_mbps,
            measured_upload_mbps=quality.upload_mbps if quality else state.measured_upload_mbps,
            measured_download_mbps=quality.download_mbps if quality else state.measured_download_mbps,
            gateway_avg_ms=gateway_ping.avg_ms if gateway_ping else None,
            gateway_jitter_ms=gateway_ping.stddev_ms if gateway_ping else None,
            internet_avg_ms=internet_ping.avg_ms if internet_ping else None,
            internet_jitter_ms=internet_ping.stddev_ms if internet_ping else None,
            internet_max_ms=internet_ping.max_ms if internet_ping else None,
            loss_percent=internet_ping.loss_percent if internet_ping else None,
            upload_responsiveness=quality.upload_responsiveness if quality else None,
            download_responsiveness=quality.download_responsiveness if quality else None,
            stability_score=health.score,
            stability_label=health.label,
        )
        with self._connect() as con:
            con.execute(
                """
                insert into samples(
                    ts, interface, gateway, profile, active, upload_cap_mbps, download_cap_mbps,
                    measured_upload_mbps, measured_download_mbps, gateway_avg_ms, gateway_jitter_ms,
                    internet_avg_ms, internet_jitter_ms, internet_max_ms, loss_percent,
                    upload_responsiveness, download_responsiveness, stability_score, stability_label
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.ts,
                    sample.interface,
                    sample.gateway,
                    sample.profile,
                    int(sample.active),
                    sample.upload_cap_mbps,
                    sample.download_cap_mbps,
                    sample.measured_upload_mbps,
                    sample.measured_download_mbps,
                    sample.gateway_avg_ms,
                    sample.gateway_jitter_ms,
                    sample.internet_avg_ms,
                    sample.internet_jitter_ms,
                    sample.internet_max_ms,
                    sample.loss_percent,
                    sample.upload_responsiveness,
                    sample.download_responsiveness,
                    sample.stability_score,
                    sample.stability_label,
                ),
            )
        return sample

    def recent_events(self, limit: int = 20) -> list[StoredEvent]:
        self.initialize()
        with self._connect() as con:
            rows = con.execute(
                "select ts, kind, message, data_json from events order by id desc limit ?",
                (limit,),
            ).fetchall()
        return [StoredEvent(ts=row["ts"], kind=row["kind"], message=row["message"], data=json.loads(row["data_json"])) for row in rows]

    def recent_samples(self, limit: int = 20) -> list[StoredSample]:
        self.initialize()
        with self._connect() as con:
            rows = con.execute(
                """
                select ts, interface, gateway, profile, active, upload_cap_mbps, download_cap_mbps,
                       measured_upload_mbps, measured_download_mbps, gateway_avg_ms, gateway_jitter_ms,
                       internet_avg_ms, internet_jitter_ms, internet_max_ms, loss_percent,
                       upload_responsiveness, download_responsiveness, stability_score, stability_label
                from samples order by id desc limit ?
                """,
                (limit,),
            ).fetchall()
        return [self._sample_from_row(row) for row in rows]

    def latest_sample(self) -> StoredSample | None:
        samples = self.recent_samples(limit=1)
        return samples[0] if samples else None

    def export_report(self, limit: int = 20) -> dict[str, Any]:
        samples = self.recent_samples(limit=limit)
        events = self.recent_events(limit=limit)
        return {
            "database": str(self.path),
            "latest_sample": asdict(samples[0]) if samples else None,
            "recent_samples": [asdict(sample) for sample in samples],
            "recent_events": [asdict(event) for event in events],
        }

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _sample_from_row(row: sqlite3.Row) -> StoredSample:
        return StoredSample(
            ts=row["ts"],
            interface=row["interface"],
            gateway=row["gateway"],
            profile=row["profile"],
            active=bool(row["active"]),
            upload_cap_mbps=row["upload_cap_mbps"],
            download_cap_mbps=row["download_cap_mbps"],
            measured_upload_mbps=row["measured_upload_mbps"],
            measured_download_mbps=row["measured_download_mbps"],
            gateway_avg_ms=row["gateway_avg_ms"],
            gateway_jitter_ms=row["gateway_jitter_ms"],
            internet_avg_ms=row["internet_avg_ms"],
            internet_jitter_ms=row["internet_jitter_ms"],
            internet_max_ms=row["internet_max_ms"],
            loss_percent=row["loss_percent"],
            upload_responsiveness=row["upload_responsiveness"],
            download_responsiveness=row["download_responsiveness"],
            stability_score=row["stability_score"],
            stability_label=row["stability_label"],
        )

