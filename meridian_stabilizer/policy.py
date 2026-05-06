from __future__ import annotations

from dataclasses import dataclass

from .parsers import NetworkQuality, PingStats
from .state import StabilizerState


@dataclass(frozen=True)
class Caps:
    upload_mbps: float
    download_mbps: float


@dataclass(frozen=True)
class TuneDecision:
    caps: Caps
    action: str
    reason: str


@dataclass(frozen=True)
class Profile:
    name: str
    upload_headroom: float
    download_headroom: float
    min_upload_mbps: float
    min_download_mbps: float
    fallback_upload_mbps: float
    fallback_download_mbps: float
    spike_avg_ms: float
    spike_max_ms: float
    spike_jitter_ms: float
    loss_percent: float


CALLS_PROFILE = Profile(
    name="calls",
    upload_headroom=0.80,
    download_headroom=0.85,
    min_upload_mbps=1.0,
    min_download_mbps=3.0,
    fallback_upload_mbps=8.0,
    fallback_download_mbps=25.0,
    spike_avg_ms=180.0,
    spike_max_ms=350.0,
    spike_jitter_ms=80.0,
    loss_percent=1.0,
)

PROFILES = {CALLS_PROFILE.name: CALLS_PROFILE}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc


def initial_caps(quality: NetworkQuality | None, profile: Profile = CALLS_PROFILE) -> Caps:
    measured_up = quality.upload_mbps if quality else None
    measured_down = quality.download_mbps if quality else None
    upload = (measured_up * profile.upload_headroom) if measured_up else profile.fallback_upload_mbps
    download = (measured_down * profile.download_headroom) if measured_down else profile.fallback_download_mbps
    return Caps(
        upload_mbps=round(max(profile.min_upload_mbps, upload), 3),
        download_mbps=round(max(profile.min_download_mbps, download), 3),
    )


def tune_caps(
    state: StabilizerState,
    internet_ping: PingStats | None,
    quality: NetworkQuality | None,
    profile: Profile = CALLS_PROFILE,
) -> TuneDecision:
    current = Caps(
        upload_mbps=state.upload_cap_mbps or profile.fallback_upload_mbps,
        download_mbps=state.download_cap_mbps or profile.fallback_download_mbps,
    )
    max_caps = _max_caps_from_measurement(state, quality, profile)

    if _is_spiky(internet_ping, profile) or _responsiveness_is_low(quality):
        upload = max(profile.min_upload_mbps, current.upload_mbps * 0.85)
        download = max(profile.min_download_mbps, current.download_mbps * 0.90)
        return TuneDecision(
            caps=_bounded_caps(upload, download, max_caps, profile),
            action="reduced",
            reason="latency, jitter, loss, or responsiveness is outside the calls profile target",
        )

    if _is_stable(internet_ping):
        upload = current.upload_mbps * 1.05
        download = current.download_mbps * 1.03
        bounded = _bounded_caps(upload, download, max_caps, profile)
        if bounded == current:
            return TuneDecision(caps=current, action="held", reason="link is stable and caps are already at the measured limit")
        return TuneDecision(caps=bounded, action="increased", reason="link is stable, so caps were raised slowly")

    return TuneDecision(caps=current, action="held", reason="link is usable but not stable enough to raise caps")


def _max_caps_from_measurement(
    state: StabilizerState,
    quality: NetworkQuality | None,
    profile: Profile,
) -> Caps:
    measured_up = (quality.upload_mbps if quality else None) or state.measured_upload_mbps
    measured_down = (quality.download_mbps if quality else None) or state.measured_download_mbps
    return Caps(
        upload_mbps=max(profile.min_upload_mbps, (measured_up * profile.upload_headroom) if measured_up else state.upload_cap_mbps or profile.fallback_upload_mbps),
        download_mbps=max(profile.min_download_mbps, (measured_down * profile.download_headroom) if measured_down else state.download_cap_mbps or profile.fallback_download_mbps),
    )


def _bounded_caps(upload: float, download: float, max_caps: Caps, profile: Profile) -> Caps:
    return Caps(
        upload_mbps=round(max(profile.min_upload_mbps, min(upload, max_caps.upload_mbps)), 3),
        download_mbps=round(max(profile.min_download_mbps, min(download, max_caps.download_mbps)), 3),
    )


def _is_spiky(ping: PingStats | None, profile: Profile) -> bool:
    if ping is None:
        return False
    if ping.loss_percent > profile.loss_percent:
        return True
    if ping.avg_ms is not None and ping.avg_ms > profile.spike_avg_ms:
        return True
    if ping.max_ms is not None and ping.max_ms > profile.spike_max_ms:
        return True
    if ping.stddev_ms is not None and ping.stddev_ms > profile.spike_jitter_ms:
        return True
    return False


def _is_stable(ping: PingStats | None) -> bool:
    if ping is None:
        return False
    if ping.loss_percent != 0:
        return False
    if ping.avg_ms is None or ping.stddev_ms is None or ping.max_ms is None:
        return False
    return ping.avg_ms < 120.0 and ping.stddev_ms < 40.0 and ping.max_ms < 220.0


def _responsiveness_is_low(quality: NetworkQuality | None) -> bool:
    if quality is None:
        return False
    labels = (quality.upload_responsiveness, quality.download_responsiveness)
    return any(label and label.lower() == "low" for label in labels)
