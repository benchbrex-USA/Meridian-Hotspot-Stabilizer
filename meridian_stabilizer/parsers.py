from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RouteInfo:
    interface: str
    gateway: str | None


@dataclass(frozen=True)
class PingStats:
    transmitted: int
    received: int
    loss_percent: float
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    stddev_ms: float | None


@dataclass(frozen=True)
class NetworkQuality:
    upload_mbps: float | None = None
    download_mbps: float | None = None
    upload_responsiveness: str | None = None
    download_responsiveness: str | None = None
    idle_latency_ms: float | None = None
    base_rtt_ms: float | None = None
    interface: str | None = None
    raw: dict[str, Any] | None = None


class ParseError(ValueError):
    pass


def parse_default_route(output: str) -> RouteInfo:
    interface = _match_line_value(output, "interface")
    gateway = _match_line_value(output, "gateway")
    if not interface:
        raise ParseError("default route did not include an interface")
    return RouteInfo(interface=interface, gateway=gateway)


def parse_ping(output: str) -> PingStats:
    packets = re.search(
        r"(?P<tx>\d+)\s+packets transmitted,\s+"
        r"(?P<rx>\d+)\s+packets received,\s+"
        r"(?P<loss>[0-9.]+)%\s+packet loss",
        output,
    )
    if not packets:
        raise ParseError("ping output did not include packet statistics")

    rtt = re.search(
        r"(?:round-trip|rtt) min/avg/max/(?:stddev|mdev)\s*=\s*"
        r"(?P<min>[0-9.]+)/(?P<avg>[0-9.]+)/(?P<max>[0-9.]+)/(?P<std>[0-9.]+)\s*ms",
        output,
    )

    return PingStats(
        transmitted=int(packets.group("tx")),
        received=int(packets.group("rx")),
        loss_percent=float(packets.group("loss")),
        min_ms=float(rtt.group("min")) if rtt else None,
        avg_ms=float(rtt.group("avg")) if rtt else None,
        max_ms=float(rtt.group("max")) if rtt else None,
        stddev_ms=float(rtt.group("std")) if rtt else None,
    )


def parse_network_quality(output: str) -> NetworkQuality:
    text = output.strip()
    if not text:
        raise ParseError("networkQuality produced no output")
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start != -1 and json_end > json_start:
        return _parse_network_quality_json(text[json_start : json_end + 1])
    return _parse_network_quality_summary(text)


def _parse_network_quality_json(text: str) -> NetworkQuality:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid networkQuality JSON: {exc}") from exc

    return NetworkQuality(
        upload_mbps=_bits_per_second_to_mbps(_first_number(data, "ul_throughput", "upload_throughput")),
        download_mbps=_bits_per_second_to_mbps(_first_number(data, "dl_throughput", "download_throughput")),
        upload_responsiveness=_responsiveness_from_json(data, "ul"),
        download_responsiveness=_responsiveness_from_json(data, "dl"),
        idle_latency_ms=_first_number(data, "idle_latency", "idle_latency_ms"),
        base_rtt_ms=_first_number(data, "base_rtt", "base_rtt_ms"),
        interface=data.get("interface_name"),
        raw=data,
    )


def _parse_network_quality_summary(text: str) -> NetworkQuality:
    return NetworkQuality(
        upload_mbps=_summary_mbps(text, "Uplink capacity"),
        download_mbps=_summary_mbps(text, "Downlink capacity"),
        upload_responsiveness=_summary_label(text, "Uplink Responsiveness"),
        download_responsiveness=_summary_label(text, "Downlink Responsiveness"),
        idle_latency_ms=_summary_latency(text, "Idle Latency"),
    )


def _match_line_value(output: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(?P<value>\S+)\s*$", output, re.MULTILINE)
    return match.group("value") if match else None


def _summary_mbps(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}:\s*(?P<value>[0-9.]+)\s*(?P<unit>[GMK]?bps|[GMK]?bit/s|Mbps)", text)
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    if unit.startswith("g"):
        return value * 1000.0
    if unit.startswith("k"):
        return value / 1000.0
    return value


def _summary_label(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}:\s*(?P<value>[A-Za-z]+)", text)
    return match.group("value") if match else None


def _summary_latency(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}:\s*(?P<value>[0-9.]+)\s+milliseconds", text)
    return float(match.group("value")) if match else None


def _first_number(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _bits_per_second_to_mbps(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1_000_000.0


def _responsiveness_from_json(data: dict[str, Any], prefix: str) -> str | None:
    for key in (f"{prefix}_responsiveness", f"{prefix}_responsiveness_classification"):
        value = data.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return _classify_responsiveness(float(value))
    return None


def _classify_responsiveness(rpm: float) -> str:
    if rpm < 100.0:
        return "Low"
    if rpm < 1000.0:
        return "Medium"
    return "High"
