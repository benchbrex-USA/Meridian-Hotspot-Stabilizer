from __future__ import annotations

from dataclasses import dataclass

from .parsers import NetworkQuality, PingStats


@dataclass(frozen=True)
class HealthScore:
    score: int | None
    label: str
    reason: str


def score_link(internet_ping: PingStats | None, quality: NetworkQuality | None = None) -> HealthScore:
    if internet_ping is None:
        return HealthScore(score=None, label="Unavailable", reason="internet latency data is unavailable")

    score = 100.0
    reasons: list[str] = []

    if internet_ping.loss_percent > 0:
        penalty = min(50.0, internet_ping.loss_percent * 20.0)
        score -= penalty
        reasons.append(f"packet loss {internet_ping.loss_percent:.1f}%")

    if internet_ping.avg_ms is not None and internet_ping.avg_ms > 60.0:
        penalty = min(30.0, (internet_ping.avg_ms - 60.0) / 4.0)
        score -= penalty
        reasons.append(f"average latency {internet_ping.avg_ms:.1f} ms")

    if internet_ping.stddev_ms is not None and internet_ping.stddev_ms > 15.0:
        penalty = min(25.0, (internet_ping.stddev_ms - 15.0) / 3.0)
        score -= penalty
        reasons.append(f"jitter {internet_ping.stddev_ms:.1f} ms")

    if internet_ping.max_ms is not None and internet_ping.max_ms > 180.0:
        penalty = min(20.0, (internet_ping.max_ms - 180.0) / 10.0)
        score -= penalty
        reasons.append(f"latency spike {internet_ping.max_ms:.1f} ms")

    low_labels = [
        label
        for label in (quality.upload_responsiveness if quality else None, quality.download_responsiveness if quality else None)
        if label and label.lower() == "low"
    ]
    if low_labels:
        score -= 15.0
        reasons.append("networkQuality responsiveness Low")

    bounded = max(0, min(100, round(score)))
    return HealthScore(score=bounded, label=_label_for_score(bounded), reason=", ".join(reasons) or "latency, jitter, and loss are within target")


def _label_for_score(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Unstable"
    return "Poor"

