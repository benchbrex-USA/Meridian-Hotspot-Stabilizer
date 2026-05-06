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
    description: str
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
    stable_avg_ms: float = 120.0
    stable_max_ms: float = 220.0
    stable_jitter_ms: float = 40.0
    reduce_upload_factor: float = 0.85
    reduce_download_factor: float = 0.90
    increase_upload_factor: float = 1.05
    increase_download_factor: float = 1.03


CALLS_PROFILE = Profile(
    name="calls",
    description="Protect video calls and work apps from upload-driven latency spikes.",
    upload_headroom=0.80,
    download_headroom=0.85,
    min_upload_mbps=3.0,
    min_download_mbps=25.0,
    fallback_upload_mbps=12.0,
    fallback_download_mbps=250.0,
    spike_avg_ms=180.0,
    spike_max_ms=350.0,
    spike_jitter_ms=80.0,
    loss_percent=1.0,
)

GAMING_PROFILE = Profile(
    name="gaming",
    description="Favor very low jitter and quick recovery over raw throughput.",
    upload_headroom=0.70,
    download_headroom=0.80,
    min_upload_mbps=2.0,
    min_download_mbps=20.0,
    fallback_upload_mbps=8.0,
    fallback_download_mbps=150.0,
    spike_avg_ms=90.0,
    spike_max_ms=180.0,
    spike_jitter_ms=25.0,
    loss_percent=0.5,
    stable_avg_ms=70.0,
    stable_max_ms=130.0,
    stable_jitter_ms=18.0,
    reduce_upload_factor=0.80,
    reduce_download_factor=0.88,
    increase_upload_factor=1.03,
    increase_download_factor=1.02,
)

DOWNLOADS_PROFILE = Profile(
    name="downloads",
    description="Keep bulk transfers fast while still preventing severe hotspot bufferbloat.",
    upload_headroom=0.88,
    download_headroom=0.94,
    min_upload_mbps=5.0,
    min_download_mbps=50.0,
    fallback_upload_mbps=20.0,
    fallback_download_mbps=500.0,
    spike_avg_ms=280.0,
    spike_max_ms=650.0,
    spike_jitter_ms=180.0,
    loss_percent=2.0,
    stable_avg_ms=180.0,
    stable_max_ms=380.0,
    stable_jitter_ms=90.0,
    reduce_upload_factor=0.90,
    reduce_download_factor=0.94,
    increase_upload_factor=1.08,
    increase_download_factor=1.05,
)

AUTO_PROFILE = Profile(
    name="auto",
    description="Balanced adaptive mode for mixed browsing, calls, and downloads.",
    upload_headroom=0.80,
    download_headroom=0.90,
    min_upload_mbps=3.0,
    min_download_mbps=25.0,
    fallback_upload_mbps=12.0,
    fallback_download_mbps=250.0,
    spike_avg_ms=160.0,
    spike_max_ms=320.0,
    spike_jitter_ms=70.0,
    loss_percent=1.0,
    stable_avg_ms=110.0,
    stable_max_ms=210.0,
    stable_jitter_ms=35.0,
)

PROFILES = {profile.name: profile for profile in (CALLS_PROFILE, GAMING_PROFILE, DOWNLOADS_PROFILE, AUTO_PROFILE)}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc


def profile_names() -> list[str]:
    return sorted(PROFILES)


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
        upload = max(profile.min_upload_mbps, current.upload_mbps * profile.reduce_upload_factor)
        download = max(profile.min_download_mbps, current.download_mbps * profile.reduce_download_factor)
        return TuneDecision(
            caps=_bounded_caps(upload, download, max_caps, profile),
            action="reduced",
            reason=f"latency, jitter, loss, or responsiveness is outside the {profile.name} profile target",
        )

    if _is_stable(internet_ping, profile):
        upload = current.upload_mbps * profile.increase_upload_factor
        download = current.download_mbps * profile.increase_download_factor
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


def _is_stable(ping: PingStats | None, profile: Profile) -> bool:
    if ping is None:
        return False
    if ping.loss_percent != 0:
        return False
    if ping.avg_ms is None or ping.stddev_ms is None or ping.max_ms is None:
        return False
    return ping.avg_ms < profile.stable_avg_ms and ping.stddev_ms < profile.stable_jitter_ms and ping.max_ms < profile.stable_max_ms


def _responsiveness_is_low(quality: NetworkQuality | None) -> bool:
    if quality is None:
        return False
    labels = (quality.upload_responsiveness, quality.download_responsiveness)
    return any(label and label.lower() == "low" for label in labels)
