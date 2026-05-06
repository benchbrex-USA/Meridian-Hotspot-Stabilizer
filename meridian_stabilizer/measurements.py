from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .parsers import NetworkQuality, PingStats, RouteInfo, parse_default_route, parse_network_quality, parse_ping


class CommandError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"{' '.join(args)} exited with {returncode}: {stderr.strip() or stdout.strip()}")


@dataclass(frozen=True)
class Snapshot:
    route: RouteInfo
    gateway_ping: PingStats | None
    internet_ping: PingStats | None
    quality: NetworkQuality | None


def run_command(args: list[str], timeout: int = 30) -> str:
    completed = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise CommandError(args, completed.returncode, completed.stdout, completed.stderr)
    return completed.stdout


def get_default_route() -> RouteInfo:
    return parse_default_route(run_command(["route", "-n", "get", "default"], timeout=10))


def ping_host(host: str, count: int = 8, timeout: int = 15) -> PingStats:
    return parse_ping(run_command(["ping", "-c", str(count), host], timeout=timeout))


def run_network_quality(timeout: int = 70) -> NetworkQuality:
    try:
        output = run_command(["networkQuality", "-c", "-s", "-M", "45"], timeout=timeout)
    except CommandError:
        output = run_command(["networkQuality", "-s"], timeout=timeout)
    return parse_network_quality(output)


def collect_snapshot(include_quality: bool = True, ping_count: int = 8, target: str = "1.1.1.1") -> Snapshot:
    route = get_default_route()
    gateway_ping = ping_host(route.gateway, count=ping_count) if route.gateway else None
    internet_ping = ping_host(target, count=ping_count)
    quality = run_network_quality() if include_quality else None
    return Snapshot(route=route, gateway_ping=gateway_ping, internet_ping=internet_ping, quality=quality)

