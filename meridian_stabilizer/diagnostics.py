from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .measurements import RuntimeSnapshot


DEFAULT_SITE_TARGETS = (
    "https://www.google.com/generate_204",
    "https://www.apple.com/library/test/success.html",
    "https://www.youtube.com/generate_204",
)


@dataclass(frozen=True)
class ProbeStep:
    name: str
    ok: bool
    detail: str
    elapsed_ms: float | None = None


@dataclass(frozen=True)
class SiteProbe:
    target: str
    url: str
    host: str
    port: int
    scheme: str
    ok: bool
    failure_stage: str | None
    summary: str
    status_code: int | None
    steps: tuple[ProbeStep, ...]


@dataclass(frozen=True)
class InternetDiagnosis:
    likely_cause: str
    recommendations: tuple[str, ...]
    probes: tuple[SiteProbe, ...]


def normalize_target(target: str) -> str:
    value = target.strip()
    if not value:
        raise ValueError("site target cannot be empty")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported site scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError(f"site target did not include a host: {target!r}")
    if not parsed.path:
        value += "/"
    return value


def probe_site(target: str, timeout: float = 6.0) -> SiteProbe:
    url = normalize_target(target)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    steps: list[ProbeStep] = []

    dns_started = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return _failed_probe(target, url, host, port, parsed.scheme, "dns", f"DNS failed: {exc}", steps)
    steps.append(ProbeStep("dns", True, _dns_detail(infos), _elapsed_ms(dns_started)))

    tcp_started = time.monotonic()
    tcp_error = _tcp_probe(infos, timeout)
    if tcp_error:
        steps.append(ProbeStep("tcp", False, tcp_error, _elapsed_ms(tcp_started)))
        return _failed_probe(target, url, host, port, parsed.scheme, "tcp", f"TCP connect failed: {tcp_error}", steps)
    steps.append(ProbeStep("tcp", True, f"connected to {host}:{port}", _elapsed_ms(tcp_started)))

    if parsed.scheme == "https":
        tls_started = time.monotonic()
        tls_result = _tls_probe(host, port, timeout)
        if not tls_result.ok:
            steps.append(ProbeStep("tls", False, tls_result.detail, _elapsed_ms(tls_started)))
            return _failed_probe(target, url, host, port, parsed.scheme, "tls", f"HTTPS handshake failed: {tls_result.detail}", steps)
        steps.append(ProbeStep("tls", True, tls_result.detail, _elapsed_ms(tls_started)))

    http_started = time.monotonic()
    http_status, http_detail = _http_probe(parsed.scheme, host, port, _request_path(parsed), timeout)
    http_ok = http_status is not None and (http_status < 500 or http_status in {401, 403, 405})
    steps.append(ProbeStep("http", http_ok, http_detail, _elapsed_ms(http_started)))
    if not http_ok:
        return _failed_probe(target, url, host, port, parsed.scheme, "http", http_detail, steps, status_code=http_status)

    return SiteProbe(
        target=target,
        url=url,
        host=host,
        port=port,
        scheme=parsed.scheme,
        ok=True,
        failure_stage=None,
        summary=http_detail,
        status_code=http_status,
        steps=tuple(steps),
    )


def diagnose_internet(snapshot: RuntimeSnapshot, probes: tuple[SiteProbe, ...]) -> InternetDiagnosis:
    if snapshot.route is None:
        return InternetDiagnosis(
            likely_cause="The Mac does not have a usable default route through the hotspot.",
            recommendations=(
                "Reconnect the hotspot or switch to USB tethering, then run internet-doctor again.",
                "Use panic if Meridian shaping was active before the route disappeared.",
            ),
            probes=probes,
        )

    if snapshot.internet_ping is None:
        return InternetDiagnosis(
            likely_cause="The hotspot route exists, but the internet probe is not getting through.",
            recommendations=(
                "Move the phone to stronger signal and confirm the phone itself can open websites.",
                "Reconnect the hotspot before trying any bandwidth shaping.",
            ),
            probes=probes,
        )

    if not probes:
        return InternetDiagnosis(
            likely_cause="The hotspot path is measurable, but no site probes were requested.",
            recommendations=("Run internet-doctor with at least one --site value.",),
            probes=probes,
        )

    failed = tuple(probe for probe in probes if not probe.ok)
    if not failed:
        return InternetDiagnosis(
            likely_cause="The tested sites are reachable; failures are likely intermittent congestion or site-specific media behavior.",
            recommendations=(
                "Keep using diagnostics first; do not enable shaping unless latency or packet loss is visible.",
                "If videos fail while pages load, test the exact video domain with --site.",
            ),
            probes=probes,
        )

    failed_stages = {probe.failure_stage for probe in failed}
    if failed_stages == {"dns"}:
        cause = "DNS is failing for the tested sites, so names are not turning into network addresses."
    elif failed_stages == {"tcp"}:
        cause = "DNS works, but TCP connections are not completing through the hotspot."
    elif failed_stages == {"tls"}:
        cause = "TCP works, but HTTPS/TLS handshakes are failing."
    elif failed_stages == {"http"}:
        cause = "The network path opens, but the web servers are returning errors or timing out."
    else:
        cause = "The failures are mixed, which points to an unstable hotspot path or site-specific blocking."

    recommendations = (
        "Run the same command once more; if the failing stage changes, the hotspot is unstable.",
        "If only one site fails, treat it as a site-specific or DNS-specific issue rather than a whole-laptop speed issue.",
        "Avoid enabling bandwidth shaping until basic DNS, TCP, and HTTPS checks are passing.",
    )
    return InternetDiagnosis(likely_cause=cause, recommendations=recommendations, probes=probes)


def _failed_probe(
    target: str,
    url: str,
    host: str,
    port: int,
    scheme: str,
    stage: str,
    summary: str,
    steps: list[ProbeStep],
    status_code: int | None = None,
) -> SiteProbe:
    return SiteProbe(
        target=target,
        url=url,
        host=host,
        port=port,
        scheme=scheme,
        ok=False,
        failure_stage=stage,
        summary=summary,
        status_code=status_code,
        steps=tuple(steps),
    )


@dataclass(frozen=True)
class _TlsResult:
    ok: bool
    detail: str


def _tcp_probe(infos: list[tuple], timeout: float) -> str | None:
    last_error: str | None = None
    for family, socktype, proto, _, sockaddr in infos[:6]:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return None
        except OSError as exc:
            last_error = str(exc)
        finally:
            sock.close()
    return last_error or "no resolved address accepted a connection"


def _tls_probe(host: str, port: int, timeout: float) -> _TlsResult:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                version = tls.version() or "TLS"
                return _TlsResult(True, f"{version} handshake completed")
    except ssl.SSLCertVerificationError as exc:
        retry = _tls_reachability_probe(host, port, timeout)
        if retry.ok:
            return _TlsResult(True, f"TLS reached server; certificate verification failed: {_ssl_detail(exc)}")
        return retry
    except (OSError, ssl.SSLError) as exc:
        return _TlsResult(False, str(exc))


def _http_probe(scheme: str, host: str, port: int, path: str, timeout: float) -> tuple[int | None, str]:
    try:
        return _http_request(scheme, host, port, path, timeout, context=ssl.create_default_context())
    except ssl.SSLCertVerificationError as exc:
        if scheme != "https":
            return None, f"HTTP request failed: {_ssl_detail(exc)}"
        try:
            status, detail = _http_request(scheme, host, port, path, timeout, context=_unverified_context())
        except OSError as retry_exc:
            return None, f"HTTP request failed after certificate retry: {retry_exc}"
        suffix = f"; certificate verification failed: {_ssl_detail(exc)}"
        return status, detail + suffix
    except OSError as exc:
        return None, f"HTTP request failed: {exc}"


def _http_request(
    scheme: str,
    host: str,
    port: int,
    path: str,
    timeout: float,
    context: ssl.SSLContext,
) -> tuple[int | None, str]:
    connection: http.client.HTTPConnection
    if scheme == "https":
        connection = http.client.HTTPSConnection(host, port=port, timeout=timeout, context=context)
    else:
        connection = http.client.HTTPConnection(host, port=port, timeout=timeout)
    try:
        connection.request("HEAD", path, headers={"User-Agent": "Meridian-Hotspot-Stabilizer/0.3", "Accept": "*/*"})
        response = connection.getresponse()
        response.read(1024)
        return response.status, f"HTTP {response.status} {response.reason}"
    finally:
        connection.close()


def _tls_reachability_probe(host: str, port: int, timeout: float) -> _TlsResult:
    context = _unverified_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                version = tls.version() or "TLS"
                return _TlsResult(True, f"{version} unverified handshake completed")
    except (OSError, ssl.SSLError) as exc:
        return _TlsResult(False, str(exc))


def _ssl_detail(exc: ssl.SSLError) -> str:
    return getattr(exc, "verify_message", None) or str(exc)


def _unverified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _request_path(parsed: object) -> str:
    path = getattr(parsed, "path", "") or "/"
    query = getattr(parsed, "query", "")
    return f"{path}?{query}" if query else path


def _dns_detail(infos: list[tuple]) -> str:
    families = {item[0] for item in infos}
    labels = []
    if socket.AF_INET in families:
        labels.append("IPv4")
    if socket.AF_INET6 in families:
        labels.append("IPv6")
    family_text = "/".join(labels) if labels else "address"
    return f"{len(infos)} {family_text} result(s)"


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)
