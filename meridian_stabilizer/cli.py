from __future__ import annotations

import argparse
import logging
import sys
import time

from .constants import APP_TITLE, ANCHOR, DOWNLOAD_PIPE, UPLOAD_PIPE
from .measurements import CommandError, collect_snapshot, get_default_route, ping_host, run_network_quality
from .parsers import NetworkQuality, PingStats
from .policy import Caps, get_profile, initial_caps, tune_caps
from .service import install_service, uninstall_service
from .state import StabilizerState, StateStore, utc_now
from .system import CommandRunner, Shaper, SystemCommandError, build_pf_rules


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except (CommandError, SystemCommandError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meridian-stabilizer", description="Stabilize macOS phone-hotspot bandwidth for work calls.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Run read-only diagnostics and recommend caps.")
    doctor.add_argument("--quick", action="store_true", help="Skip networkQuality and use ping-only diagnostics.")
    doctor.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    doctor.set_defaults(func=cmd_doctor)

    start = sub.add_parser("start", help="Apply hotspot stabilization rules.")
    start.add_argument("--profile", default="calls", choices=["calls"])
    start.add_argument("--upload-mbps", type=float, help="Override upload cap.")
    start.add_argument("--download-mbps", type=float, help="Override download cap.")
    start.add_argument("--no-measure", action="store_true", help="Use fallback or provided caps without networkQuality.")
    start.add_argument("--dry-run", action="store_true", help="Show commands and rules without applying them.")
    start.add_argument("--watch", action="store_true", help=argparse.SUPPRESS)
    start.add_argument("--interval", type=int, default=60, help=argparse.SUPPRESS)
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser("stop", help="Remove this tool's PF/dnctl rules.")
    stop.add_argument("--dry-run", action="store_true", help="Show commands without applying them.")
    stop.set_defaults(func=cmd_stop)

    status = sub.add_parser("status", help="Show active caps and recent link health.")
    status.add_argument("--system", action="store_true", help="Also query PF/dnctl state; may require sudo.")
    status.set_defaults(func=cmd_status)

    tune = sub.add_parser("tune", help="Measure and update active caps.")
    tune.add_argument("--dry-run", action="store_true", help="Show new caps without applying them.")
    tune.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    tune.set_defaults(func=cmd_tune)

    svc = sub.add_parser("install-service", help="Install and start a privileged launchd service.")
    svc.add_argument("--profile", default="calls", choices=["calls"])
    svc.add_argument("--interval", type=int, default=60, help="Background tune interval in seconds.")
    svc.add_argument("--dry-run", action="store_true", help="Show install commands without applying them.")
    svc.set_defaults(func=cmd_install_service)

    unsvc = sub.add_parser("uninstall-service", help="Remove the launchd service and stop shaping.")
    unsvc.add_argument("--keep-rules", action="store_true", help="Remove only the service, leaving current shaping rules in place.")
    unsvc.add_argument("--dry-run", action="store_true", help="Show commands without applying them.")
    unsvc.set_defaults(func=cmd_uninstall_service)

    return parser


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"{APP_TITLE} doctor")
    snapshot = collect_snapshot(include_quality=not args.quick, target=args.target)
    _print_snapshot(snapshot.route.interface, snapshot.route.gateway, snapshot.gateway_ping, snapshot.internet_ping, snapshot.quality)
    caps = initial_caps(snapshot.quality, get_profile("calls"))
    print()
    print(f"Recommended calls caps: upload {caps.upload_mbps:.3f} Mbps, download {caps.download_mbps:.3f} Mbps")
    print("Recommendation: start with these caps, then let tune reduce them if latency spikes under load.")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    profile = get_profile(args.profile)
    route = get_default_route()
    quality = None if args.no_measure else run_network_quality()
    caps = initial_caps(quality, profile)
    if args.upload_mbps:
        caps = Caps(upload_mbps=args.upload_mbps, download_mbps=caps.download_mbps)
    if args.download_mbps:
        caps = Caps(upload_mbps=caps.upload_mbps, download_mbps=args.download_mbps)

    runner = CommandRunner(dry_run=args.dry_run)
    shaper = Shaper(runner)
    pf_token = shaper.apply(route.interface, caps, existing_pf_token=state.pf_token if state.active else None)

    state = StabilizerState(
        active=not args.dry_run,
        profile=args.profile,
        interface=route.interface,
        gateway=route.gateway,
        upload_cap_mbps=caps.upload_mbps,
        download_cap_mbps=caps.download_mbps,
        measured_upload_mbps=quality.upload_mbps if quality else state.measured_upload_mbps,
        measured_download_mbps=quality.download_mbps if quality else state.measured_download_mbps,
        pf_token=pf_token if not args.dry_run else state.pf_token,
        started_at=state.started_at or utc_now(),
        updated_at=utc_now(),
        last_action="dry-run start" if args.dry_run else "started",
    )
    if not args.dry_run:
        store.save(state)

    print(_apply_summary("Dry run" if args.dry_run else "Started", route.interface, caps))
    if args.dry_run:
        print()
        print("Commands:")
        for command in runner.commands:
            print("  " + " ".join(command))
        print()
        print("PF rules:")
        print(build_pf_rules(route.interface), end="")
        return 0

    if args.watch:
        return watch_loop(state, store, interval=max(15, args.interval))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    shaper = Shaper(CommandRunner(dry_run=args.dry_run))
    shaper.clear(pf_token=state.pf_token)
    if not args.dry_run:
        state.active = False
        state.pf_token = None
        state.last_action = "stopped"
        store.save(state)
    print("Dry run: stop commands prepared." if args.dry_run else "Stopped and removed Meridian PF/dnctl rules.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    print(f"{APP_TITLE} status")
    print(f"Active: {'yes' if state.active else 'no'}")
    print(f"Profile: {state.profile}")
    print(f"Interface: {state.interface or 'unknown'}")
    print(f"Gateway: {state.gateway or 'unknown'}")
    print(f"Upload cap: {_fmt_optional(state.upload_cap_mbps)} Mbps")
    print(f"Download cap: {_fmt_optional(state.download_cap_mbps)} Mbps")
    print(f"Last action: {state.last_action or 'none'}")
    print(f"Last gateway avg: {_fmt_optional(state.last_gateway_avg_ms)} ms")
    print(f"Last gateway jitter: {_fmt_optional(state.last_gateway_jitter_ms)} ms")
    print(f"Last latency avg: {_fmt_optional(state.last_latency_avg_ms)} ms")
    print(f"Last jitter: {_fmt_optional(state.last_jitter_ms)} ms")
    print(f"Last loss: {_fmt_optional(state.last_loss_percent)}%")
    print(f"State file: {store.state_file}")
    print(f"Log file: {store.log_file}")

    if args.system:
        dnctl, pf = Shaper().status_text()
        print()
        print(f"PF anchor: {ANCHOR}")
        print(pf or "No PF rules reported.")
        print()
        print(f"Dummynet pipes: {UPLOAD_PIPE}, {DOWNLOAD_PIPE}")
        print(dnctl or "No dummynet pipe state reported.")
    return 0


def cmd_tune(args: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    if not state.active or not state.interface:
        print("Stabilizer is not active. Run start first.")
        return 1

    quality = run_network_quality()
    gateway_ping = ping_host(state.gateway, count=5) if state.gateway else None
    internet_ping = ping_host(args.target, count=8)
    decision = tune_caps(state, internet_ping, quality, get_profile(state.profile))

    state.upload_cap_mbps = decision.caps.upload_mbps
    state.download_cap_mbps = decision.caps.download_mbps
    state.measured_upload_mbps = quality.upload_mbps or state.measured_upload_mbps
    state.measured_download_mbps = quality.download_mbps or state.measured_download_mbps
    state.last_gateway_avg_ms = gateway_ping.avg_ms if gateway_ping else state.last_gateway_avg_ms
    state.last_gateway_jitter_ms = gateway_ping.stddev_ms if gateway_ping else state.last_gateway_jitter_ms
    state.last_latency_avg_ms = internet_ping.avg_ms
    state.last_jitter_ms = internet_ping.stddev_ms
    state.last_loss_percent = internet_ping.loss_percent
    state.last_action = f"{decision.action}: {decision.reason}"

    if not args.dry_run:
        Shaper().apply(state.interface, decision.caps, existing_pf_token=state.pf_token)
        store.save(state)

    print(f"{'Dry run: ' if args.dry_run else ''}{decision.action.capitalize()} caps.")
    print(f"Reason: {decision.reason}")
    print(f"Upload cap: {decision.caps.upload_mbps:.3f} Mbps")
    print(f"Download cap: {decision.caps.download_mbps:.3f} Mbps")
    return 0


def cmd_install_service(args: argparse.Namespace) -> int:
    runner = CommandRunner(dry_run=args.dry_run)
    path = install_service(profile=args.profile, interval=max(15, args.interval), runner=runner)
    if args.dry_run:
        print("Dry run: service install commands prepared:")
        for command in runner.commands:
            print("  " + " ".join(command))
    else:
        print(f"Installed and started launchd service: {path}")
    return 0


def cmd_uninstall_service(args: argparse.Namespace) -> int:
    runner = CommandRunner(dry_run=args.dry_run)
    path = uninstall_service(runner=runner)
    if not args.keep_rules:
        cmd_stop(argparse.Namespace(dry_run=args.dry_run))
    if args.dry_run:
        print("Dry run: service uninstall commands prepared:")
        for command in runner.commands:
            print("  " + " ".join(command))
    else:
        print(f"Removed launchd service: {path}")
    return 0


def watch_loop(state: StabilizerState, store: StateStore, interval: int) -> int:
    logging.info("watch loop started with interval=%s", interval)
    last_quality_at = time.monotonic()
    while True:
        try:
            target = "1.1.1.1"
            gateway_ping = ping_host(state.gateway, count=3, timeout=8) if state.gateway else None
            internet_ping = ping_host(target, count=6, timeout=12)
            quality = None
            if time.monotonic() - last_quality_at >= 900:
                quality = run_network_quality()
                last_quality_at = time.monotonic()
                state.measured_upload_mbps = quality.upload_mbps or state.measured_upload_mbps
                state.measured_download_mbps = quality.download_mbps or state.measured_download_mbps
            decision = tune_caps(state, internet_ping, quality=quality, profile=get_profile(state.profile))
            if decision.action != "held":
                Shaper().apply(state.interface or "en0", decision.caps, existing_pf_token=state.pf_token)
                state.upload_cap_mbps = decision.caps.upload_mbps
                state.download_cap_mbps = decision.caps.download_mbps
            state.last_gateway_avg_ms = gateway_ping.avg_ms if gateway_ping else state.last_gateway_avg_ms
            state.last_gateway_jitter_ms = gateway_ping.stddev_ms if gateway_ping else state.last_gateway_jitter_ms
            state.last_latency_avg_ms = internet_ping.avg_ms
            state.last_jitter_ms = internet_ping.stddev_ms
            state.last_loss_percent = internet_ping.loss_percent
            state.last_action = f"watch {decision.action}: {decision.reason}"
            store.save(state)
            logging.info(
                "watch tune: %s upload=%.3f download=%.3f gateway_avg=%s internet_avg=%s jitter=%s loss=%s",
                decision.action,
                decision.caps.upload_mbps,
                decision.caps.download_mbps,
                gateway_ping.avg_ms if gateway_ping else None,
                internet_ping.avg_ms,
                internet_ping.stddev_ms,
                internet_ping.loss_percent,
            )
        except Exception as exc:
            logging.exception("watch loop failed: %s", exc)
        time.sleep(interval)


def setup_logging() -> None:
    store = StateStore()
    try:
        store.ensure_dir()
        logging.basicConfig(filename=store.log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _print_snapshot(
    interface: str,
    gateway: str | None,
    gateway_ping: PingStats | None,
    internet_ping: PingStats | None,
    quality: NetworkQuality | None,
) -> None:
    print(f"Interface: {interface}")
    print(f"Gateway: {gateway or 'unknown'}")
    if gateway_ping:
        print(f"Gateway latency: {_ping_line(gateway_ping)}")
    if internet_ping:
        print(f"Internet latency: {_ping_line(internet_ping)}")
    if quality:
        print(f"Measured upload: {_fmt_optional(quality.upload_mbps)} Mbps")
        print(f"Measured download: {_fmt_optional(quality.download_mbps)} Mbps")
        print(f"Upload responsiveness: {quality.upload_responsiveness or 'unknown'}")
        print(f"Download responsiveness: {quality.download_responsiveness or 'unknown'}")
        latency = quality.idle_latency_ms or quality.base_rtt_ms
        print(f"Idle latency: {_fmt_optional(latency)} ms")


def _ping_line(stats: PingStats) -> str:
    return (
        f"avg {_fmt_optional(stats.avg_ms)} ms, "
        f"max {_fmt_optional(stats.max_ms)} ms, "
        f"jitter {_fmt_optional(stats.stddev_ms)} ms, "
        f"loss {stats.loss_percent:.1f}%"
    )


def _apply_summary(label: str, interface: str, caps: Caps) -> str:
    return f"{label} on {interface}: upload {caps.upload_mbps:.3f} Mbps, download {caps.download_mbps:.3f} Mbps"


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.3f}"
