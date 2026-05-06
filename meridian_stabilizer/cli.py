from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict

from .constants import APP_TITLE, ANCHOR, DOWNLOAD_PIPE, UPLOAD_PIPE
from .database import MetricsDB, StoredSample
from .health import score_link
from .measurements import (
    CommandError,
    RuntimeSnapshot,
    collect_runtime_snapshot,
    get_default_route,
    run_network_quality,
)
from .parsers import PingStats
from .policy import PROFILES, Caps, get_profile, initial_caps, profile_names, tune_caps
from .preflight import preflight_ok, run_preflight
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
    parser = argparse.ArgumentParser(prog="meridian-stabilizer", description="Production CLI for stabilizing macOS phone-hotspot bandwidth.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Run real diagnostics and recommend caps.")
    doctor.add_argument("--quick", action="store_true", help="Skip networkQuality and use ping-only diagnostics.")
    doctor.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    doctor.add_argument("--profile", default="calls", choices=profile_names())
    doctor.set_defaults(func=cmd_doctor)

    preflight = sub.add_parser("preflight", help="Check macOS commands, route, and PF/dnctl rule syntax.")
    preflight.set_defaults(func=cmd_preflight)

    profiles = sub.add_parser("profiles", help="List built-in stabilization profiles.")
    profiles.set_defaults(func=cmd_profiles)

    start = sub.add_parser("start", help="Apply hotspot stabilization rules.")
    add_start_args(start)
    start.add_argument("--watch", action="store_true", help=argparse.SUPPRESS)
    start.add_argument("--interval", type=int, default=60, help=argparse.SUPPRESS)
    start.set_defaults(func=cmd_start)

    run = sub.add_parser("run", help="Start shaping and keep the adaptive tuner running in the foreground.")
    add_start_args(run)
    run.add_argument("--interval", type=int, default=60, help="Adaptive tune interval in seconds.")
    run.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    run.add_argument("--quality-every", type=int, default=900, help="Run networkQuality every N seconds while watching.")
    run.set_defaults(func=cmd_run)

    stop = sub.add_parser("stop", help="Remove this tool's PF/dnctl rules.")
    stop.add_argument("--dry-run", action="store_true", help="Show commands without applying them.")
    stop.set_defaults(func=cmd_stop)

    panic = sub.add_parser("panic", help="Emergency stop: clear owned rules and mark Meridian inactive.")
    panic.add_argument("--dry-run", action="store_true", help="Show commands without applying them.")
    panic.add_argument("--service", action="store_true", help="Also unload the launchd service.")
    panic.set_defaults(func=cmd_panic)

    status = sub.add_parser("status", help="Show active caps, last metrics, and stored state.")
    status.add_argument("--system", action="store_true", help="Also query PF/dnctl state; may require sudo.")
    status.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    status.set_defaults(func=cmd_status)

    tune = sub.add_parser("tune", help="Measure and update active caps.")
    tune.add_argument("--dry-run", action="store_true", help="Show new caps without applying them.")
    tune.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    tune.set_defaults(func=cmd_tune)

    dashboard = sub.add_parser("dashboard", help="Live CLI dashboard using only real local measurements.")
    dashboard.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds.")
    dashboard.add_argument("--target", default="1.1.1.1", help="Internet probe target for ping diagnostics.")
    dashboard.add_argument("--quality-every", type=int, default=0, help="Run networkQuality every N seconds; 0 disables it.")
    dashboard.add_argument("--once", action="store_true", help="Render one real sample and exit.")
    dashboard.set_defaults(func=cmd_dashboard)

    events = sub.add_parser("events", help="Show stored real events.")
    events.add_argument("--limit", type=int, default=20)
    events.set_defaults(func=cmd_events)

    report = sub.add_parser("report", help="Print a real local diagnostic report.")
    report.add_argument("--limit", type=int, default=20)
    report.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    report.set_defaults(func=cmd_report)

    svc = sub.add_parser("install-service", help="Install and start the CLI watcher as a privileged launchd service.")
    svc.add_argument("--profile", default="calls", choices=profile_names())
    svc.add_argument("--interval", type=int, default=60, help="Background tune interval in seconds.")
    svc.add_argument("--dry-run", action="store_true", help="Show install commands without applying them.")
    svc.set_defaults(func=cmd_install_service)

    unsvc = sub.add_parser("uninstall-service", help="Remove the launchd service and stop shaping.")
    unsvc.add_argument("--keep-rules", action="store_true", help="Remove only the service, leaving current shaping rules in place.")
    unsvc.add_argument("--dry-run", action="store_true", help="Show commands without applying them.")
    unsvc.set_defaults(func=cmd_uninstall_service)

    return parser


def add_start_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default="calls", choices=profile_names())
    parser.add_argument("--upload-mbps", type=float, help="Override upload cap.")
    parser.add_argument("--download-mbps", type=float, help="Override download cap.")
    parser.add_argument("--no-measure", action="store_true", help="Use fallback or provided caps without networkQuality.")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip startup preflight checks.")
    parser.add_argument("--dry-run", action="store_true", help="Show commands and rules without applying them.")


def cmd_doctor(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    profile = get_profile(args.profile)
    print(f"{APP_TITLE} doctor")
    snapshot = collect_runtime_snapshot(include_quality=not args.quick, ping_count=8, target=args.target)
    _print_runtime_snapshot(snapshot)
    caps = initial_caps(snapshot.quality, profile)
    print()
    cap_basis = "measured" if snapshot.quality and (snapshot.quality.upload_mbps or snapshot.quality.download_mbps) else "fallback"
    print(f"{cap_basis.capitalize()} {profile.name} caps: upload {caps.upload_mbps:.3f} Mbps, download {caps.download_mbps:.3f} Mbps")
    print("All values above are measured live; unavailable values are not estimated.")
    db.record_sample(state, snapshot.route, snapshot.gateway_ping, snapshot.internet_ping, snapshot.quality)
    if snapshot.errors:
        db.record_event("doctor-warning", "doctor completed with unavailable data", {"errors": list(snapshot.errors)})
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    checks = run_preflight()
    print(f"{APP_TITLE} preflight")
    for check in checks:
        marker = "OK" if check.ok else ("WARN" if not check.required else "FAIL")
        print(f"{marker:4} {check.name}: {check.detail}")
    ok = preflight_ok(checks)
    print()
    print("Preflight result: " + ("ready" if ok else "blocked"))
    return 0 if ok else 1


def cmd_profiles(args: argparse.Namespace) -> int:
    print(f"{APP_TITLE} profiles")
    for name in profile_names():
        profile = PROFILES[name]
        print()
        print(f"{profile.name}: {profile.description}")
        print(f"  headroom: upload {profile.upload_headroom:.0%}, download {profile.download_headroom:.0%}")
        print(f"  fallback caps: upload {profile.fallback_upload_mbps:.3f} Mbps, download {profile.fallback_download_mbps:.3f} Mbps")
        print(f"  spike target: avg>{profile.spike_avg_ms:.0f} ms, max>{profile.spike_max_ms:.0f} ms, jitter>{profile.spike_jitter_ms:.0f} ms, loss>{profile.loss_percent:.1f}%")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    profile = get_profile(args.profile)

    if not args.skip_preflight:
        checks = run_preflight()
        if not preflight_ok(checks):
            for check in checks:
                if check.required and not check.ok:
                    print(f"Preflight failed: {check.name}: {check.detail}", file=sys.stderr)
            return 1

    route = get_default_route()
    quality = None if args.no_measure else run_network_quality()
    caps = initial_caps(quality, profile)
    if args.upload_mbps is not None:
        caps = Caps(upload_mbps=args.upload_mbps, download_mbps=caps.download_mbps)
    if args.download_mbps is not None:
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
        run_pid=os.getpid() if args.watch and not args.dry_run else None,
        heartbeat_at=utc_now() if args.watch and not args.dry_run else state.heartbeat_at,
    )
    if not args.dry_run:
        store.save(state)
        db.record_event("start", "shaping started", {"profile": args.profile, "interface": route.interface, "gateway": route.gateway, "upload_cap_mbps": caps.upload_mbps, "download_cap_mbps": caps.download_mbps})
        db.record_sample(state, route, None, None, quality)

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
        return watch_loop(state, store, db, interval=max(15, args.interval), target=getattr(args, "target", "1.1.1.1"), quality_every=getattr(args, "quality_every", 900))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    args.watch = True
    return cmd_start(args)


def cmd_stop(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    runner = CommandRunner(dry_run=args.dry_run)
    Shaper(runner).clear(pf_token=state.pf_token)
    if not args.dry_run:
        state.active = False
        state.pf_token = None
        state.run_pid = None
        state.last_action = "stopped"
        state.stopped_at = utc_now()
        store.save(state)
        db.record_event("stop", "owned PF/dnctl rules removed", {"anchor": ANCHOR, "pipes": [UPLOAD_PIPE, DOWNLOAD_PIPE]})
    print("Dry run: stop commands prepared." if args.dry_run else "Stopped and removed Meridian PF/dnctl rules.")
    return 0


def cmd_panic(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    runner = CommandRunner(dry_run=args.dry_run)
    Shaper(runner).clear(pf_token=state.pf_token)
    if args.service:
        uninstall_service(runner=runner)
    if not args.dry_run:
        state.active = False
        state.pf_token = None
        state.run_pid = None
        state.last_action = "panic stop"
        state.stopped_at = utc_now()
        store.save(state)
        db.record_event("panic", "emergency stop cleared owned rules", {"service": bool(args.service)})
    if args.dry_run:
        print("Dry run: panic commands prepared:")
        for command in runner.commands:
            print("  " + " ".join(command))
    else:
        print("Panic stop complete. Owned Meridian rules are cleared.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    latest = db.latest_sample()
    payload = {"state": asdict(state), "latest_sample": asdict(latest) if latest else None, "database": str(db.path)}

    if args.system:
        dnctl, pf = Shaper().status_text()
        payload["system"] = {"anchor": ANCHOR, "pf_rules": pf, "dummynet": dnctl}

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"{APP_TITLE} status")
    print(f"Active: {'yes' if state.active else 'no'}")
    print(f"Profile: {state.profile}")
    print(f"Interface: {state.interface or 'unavailable'}")
    print(f"Gateway: {state.gateway or 'unavailable'}")
    print(f"Upload cap: {_fmt_optional(state.upload_cap_mbps)} Mbps")
    print(f"Download cap: {_fmt_optional(state.download_cap_mbps)} Mbps")
    print(f"Last action: {state.last_action or 'none'}")
    print(f"Watcher PID: {state.run_pid or 'none'}")
    print(f"Heartbeat: {state.heartbeat_at or 'none'}")
    print(f"Last gateway avg: {_fmt_optional(state.last_gateway_avg_ms)} ms")
    print(f"Last gateway jitter: {_fmt_optional(state.last_gateway_jitter_ms)} ms")
    print(f"Last internet avg: {_fmt_optional(state.last_latency_avg_ms)} ms")
    print(f"Last internet jitter: {_fmt_optional(state.last_jitter_ms)} ms")
    print(f"Last loss: {_fmt_optional(state.last_loss_percent)}%")
    if latest:
        print(f"Latest stored stability: {_fmt_score(latest)}")
    print(f"State file: {store.state_file}")
    print(f"Metrics database: {db.path}")
    print(f"Log file: {store.log_file}")

    if args.system:
        print()
        print(f"PF anchor: {ANCHOR}")
        print(payload["system"]["pf_rules"] or "No PF rules reported.")
        print()
        print(f"Dummynet pipes: {UPLOAD_PIPE}, {DOWNLOAD_PIPE}")
        print(payload["system"]["dummynet"] or "No dummynet pipe state reported.")
    return 0


def cmd_tune(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    state = store.load()
    if not state.active or not state.interface:
        print("Stabilizer is not active. Run start first.")
        return 1

    snapshot = collect_runtime_snapshot(include_quality=True, ping_count=8, target=args.target)
    quality = snapshot.quality
    internet_ping = snapshot.internet_ping
    decision = tune_caps(state, internet_ping, quality, get_profile(state.profile))
    route = snapshot.route

    state.upload_cap_mbps = decision.caps.upload_mbps
    state.download_cap_mbps = decision.caps.download_mbps
    state.interface = route.interface if route else state.interface
    state.gateway = route.gateway if route else state.gateway
    state.measured_upload_mbps = quality.upload_mbps if quality and quality.upload_mbps is not None else state.measured_upload_mbps
    state.measured_download_mbps = quality.download_mbps if quality and quality.download_mbps is not None else state.measured_download_mbps
    _update_state_metrics(state, snapshot)
    state.last_action = f"{decision.action}: {decision.reason}"

    if not args.dry_run:
        Shaper().apply(state.interface, decision.caps, existing_pf_token=state.pf_token)
        store.save(state)
        db.record_event("tune", decision.reason, {"action": decision.action, "upload_cap_mbps": decision.caps.upload_mbps, "download_cap_mbps": decision.caps.download_mbps})
        db.record_sample(state, snapshot.route, snapshot.gateway_ping, snapshot.internet_ping, snapshot.quality)

    print(f"{'Dry run: ' if args.dry_run else ''}{decision.action.capitalize()} caps.")
    print(f"Reason: {decision.reason}")
    print(f"Upload cap: {decision.caps.upload_mbps:.3f} Mbps")
    print(f"Download cap: {decision.caps.download_mbps:.3f} Mbps")
    if snapshot.errors:
        print("Unavailable data:")
        for error in snapshot.errors:
            print(f"  {error}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    last_quality_at = 0.0
    while True:
        include_quality = args.quality_every > 0 and (time.monotonic() - last_quality_at >= args.quality_every or last_quality_at == 0.0)
        snapshot = collect_runtime_snapshot(include_quality=include_quality, ping_count=4, target=args.target)
        if include_quality:
            last_quality_at = time.monotonic()
        state = store.load()
        sample = db.record_sample(state, snapshot.route, snapshot.gateway_ping, snapshot.internet_ping, snapshot.quality)
        _render_dashboard(state, snapshot, sample, db)
        if args.once:
            return 0
        time.sleep(max(2, args.interval))


def cmd_events(args: argparse.Namespace) -> int:
    db = MetricsDB()
    events = db.recent_events(limit=max(1, args.limit))
    if not events:
        print("No stored events yet.")
        return 0
    for event in events:
        suffix = f" {json.dumps(event.data, sort_keys=True)}" if event.data else ""
        print(f"{event.ts} {event.kind}: {event.message}{suffix}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    store = StateStore()
    db = MetricsDB()
    payload = {"state": asdict(store.load()), **db.export_report(limit=max(1, args.limit))}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"{APP_TITLE} real-data report")
    print(f"State active: {'yes' if payload['state']['active'] else 'no'}")
    print(f"Profile: {payload['state']['profile']}")
    print(f"Interface: {payload['state']['interface'] or 'unavailable'}")
    print(f"Upload cap: {_fmt_optional(payload['state']['upload_cap_mbps'])} Mbps")
    print(f"Download cap: {_fmt_optional(payload['state']['download_cap_mbps'])} Mbps")
    print(f"Database: {payload['database']}")
    latest = payload["latest_sample"]
    if latest:
        print()
        print("Latest real sample:")
        print(f"  timestamp: {latest['ts']}")
        print(f"  stability: {latest['stability_score'] if latest['stability_score'] is not None else 'unavailable'} ({latest['stability_label']})")
        print(f"  internet avg/jitter/loss: {_fmt_optional(latest['internet_avg_ms'])} ms / {_fmt_optional(latest['internet_jitter_ms'])} ms / {_fmt_optional(latest['loss_percent'])}%")
        print(f"  measured upload/download: {_fmt_optional(latest['measured_upload_mbps'])} Mbps / {_fmt_optional(latest['measured_download_mbps'])} Mbps")
    print()
    print(f"Recent events: {len(payload['recent_events'])}")
    for event in payload["recent_events"][:5]:
        print(f"  {event['ts']} {event['kind']}: {event['message']}")
    return 0


def cmd_install_service(args: argparse.Namespace) -> int:
    runner = CommandRunner(dry_run=args.dry_run)
    path = install_service(profile=args.profile, interval=max(15, args.interval), runner=runner)
    if args.dry_run:
        print("Dry run: service install commands prepared:")
        for command in runner.commands:
            print("  " + " ".join(command))
    else:
        MetricsDB().record_event("service-install", "launchd service installed", {"path": str(path), "profile": args.profile, "interval": args.interval})
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
        MetricsDB().record_event("service-uninstall", "launchd service removed", {"path": str(path), "keep_rules": args.keep_rules})
        print(f"Removed launchd service: {path}")
    return 0


def watch_loop(state: StabilizerState, store: StateStore, db: MetricsDB, interval: int, target: str, quality_every: int) -> int:
    logging.info("watch loop started with interval=%s target=%s quality_every=%s", interval, target, quality_every)
    db.record_event("watch-start", "foreground adaptive watcher started", {"pid": os.getpid(), "interval": interval, "target": target})
    last_quality_at = time.monotonic()
    try:
        while True:
            include_quality = quality_every > 0 and time.monotonic() - last_quality_at >= quality_every
            snapshot = collect_runtime_snapshot(include_quality=include_quality, ping_count=6, target=target)
            if include_quality:
                last_quality_at = time.monotonic()
            route_changed = _route_changed(state, snapshot)
            if route_changed and snapshot.route:
                db.record_event("route-change", "default route changed", {"old_interface": state.interface, "new_interface": snapshot.route.interface, "old_gateway": state.gateway, "new_gateway": snapshot.route.gateway})
                state.interface = snapshot.route.interface
                state.gateway = snapshot.route.gateway

            decision = tune_caps(state, snapshot.internet_ping, quality=snapshot.quality, profile=get_profile(state.profile))
            should_apply = decision.action != "held" or route_changed
            if should_apply and state.interface:
                pf_token = Shaper().apply(state.interface, decision.caps, existing_pf_token=state.pf_token)
                state.pf_token = pf_token or state.pf_token
                state.upload_cap_mbps = decision.caps.upload_mbps
                state.download_cap_mbps = decision.caps.download_mbps

            if snapshot.quality:
                state.measured_upload_mbps = snapshot.quality.upload_mbps or state.measured_upload_mbps
                state.measured_download_mbps = snapshot.quality.download_mbps or state.measured_download_mbps
            state.run_pid = os.getpid()
            state.heartbeat_at = utc_now()
            _update_state_metrics(state, snapshot)
            state.last_action = f"watch {decision.action}: {decision.reason}"
            store.save(state)
            db.record_sample(state, snapshot.route, snapshot.gateway_ping, snapshot.internet_ping, snapshot.quality)
            if should_apply:
                db.record_event("watch-tune", decision.reason, {"action": decision.action, "upload_cap_mbps": decision.caps.upload_mbps, "download_cap_mbps": decision.caps.download_mbps})
            logging.info("watch tune: %s upload=%.3f download=%.3f", decision.action, decision.caps.upload_mbps, decision.caps.download_mbps)
            time.sleep(interval)
    except KeyboardInterrupt:
        db.record_event("watch-stop", "foreground adaptive watcher interrupted", {"pid": os.getpid()})
        state.run_pid = None
        store.save(state)
        raise


def setup_logging() -> None:
    store = StateStore()
    try:
        store.ensure_dir()
        logging.basicConfig(filename=store.log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _print_runtime_snapshot(snapshot: RuntimeSnapshot) -> None:
    print(f"Interface: {snapshot.route.interface if snapshot.route else 'unavailable'}")
    print(f"Gateway: {snapshot.route.gateway if snapshot.route else 'unavailable'}")
    if snapshot.gateway_ping:
        print(f"Gateway latency: {_ping_line(snapshot.gateway_ping)}")
    else:
        print("Gateway latency: unavailable")
    if snapshot.internet_ping:
        print(f"Internet latency: {_ping_line(snapshot.internet_ping)}")
        health = score_link(snapshot.internet_ping, snapshot.quality)
        print(f"Stability score: {_fmt_health(health.score, health.label)}")
        print(f"Stability basis: {health.reason}")
    else:
        print("Internet latency: unavailable")
        print("Stability score: unavailable")
    if snapshot.quality:
        print(f"Measured upload: {_fmt_optional(snapshot.quality.upload_mbps)} Mbps")
        print(f"Measured download: {_fmt_optional(snapshot.quality.download_mbps)} Mbps")
        print(f"Upload responsiveness: {snapshot.quality.upload_responsiveness or 'unavailable'}")
        print(f"Download responsiveness: {snapshot.quality.download_responsiveness or 'unavailable'}")
        latency = snapshot.quality.idle_latency_ms or snapshot.quality.base_rtt_ms
        print(f"Idle latency: {_fmt_optional(latency)} ms")
    if snapshot.errors:
        print("Unavailable data:")
        for error in snapshot.errors:
            print(f"  {error}")


def _render_dashboard(state: StabilizerState, snapshot: RuntimeSnapshot, sample: StoredSample, db: MetricsDB) -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    print(f"{APP_TITLE} CLI dashboard")
    print("Real data only. Unavailable means the local measurement could not be collected.")
    print(f"Timestamp: {sample.ts}")
    print()
    print(f"Active: {'yes' if state.active else 'no'} | Profile: {state.profile} | Interface: {sample.interface or 'unavailable'} | Gateway: {sample.gateway or 'unavailable'}")
    print(f"Caps: upload {_fmt_optional(sample.upload_cap_mbps)} Mbps | download {_fmt_optional(sample.download_cap_mbps)} Mbps")
    print(f"Stability: {_fmt_score(sample)}")
    print()
    print("Live latency")
    print(f"  Gateway avg/jitter: {_fmt_optional(sample.gateway_avg_ms)} ms / {_fmt_optional(sample.gateway_jitter_ms)} ms")
    print(f"  Internet avg/jitter/max/loss: {_fmt_optional(sample.internet_avg_ms)} ms / {_fmt_optional(sample.internet_jitter_ms)} ms / {_fmt_optional(sample.internet_max_ms)} ms / {_fmt_optional(sample.loss_percent)}%")
    print()
    print("Measured capacity")
    print(f"  Upload: {_fmt_optional(sample.measured_upload_mbps)} Mbps | responsiveness: {sample.upload_responsiveness or 'unavailable'}")
    print(f"  Download: {_fmt_optional(sample.measured_download_mbps)} Mbps | responsiveness: {sample.download_responsiveness or 'unavailable'}")
    if snapshot.errors:
        print()
        print("Unavailable data")
        for error in snapshot.errors:
            print(f"  {error}")
    events = db.recent_events(limit=5)
    if events:
        print()
        print("Recent real events")
        for event in events:
            print(f"  {event.ts} {event.kind}: {event.message}")


def _update_state_metrics(state: StabilizerState, snapshot: RuntimeSnapshot) -> None:
    state.last_gateway_avg_ms = snapshot.gateway_ping.avg_ms if snapshot.gateway_ping else state.last_gateway_avg_ms
    state.last_gateway_jitter_ms = snapshot.gateway_ping.stddev_ms if snapshot.gateway_ping else state.last_gateway_jitter_ms
    state.last_latency_avg_ms = snapshot.internet_ping.avg_ms if snapshot.internet_ping else state.last_latency_avg_ms
    state.last_jitter_ms = snapshot.internet_ping.stddev_ms if snapshot.internet_ping else state.last_jitter_ms
    state.last_loss_percent = snapshot.internet_ping.loss_percent if snapshot.internet_ping else state.last_loss_percent


def _route_changed(state: StabilizerState, snapshot: RuntimeSnapshot) -> bool:
    if not snapshot.route:
        return False
    return snapshot.route.interface != state.interface or snapshot.route.gateway != state.gateway


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
        return "unavailable"
    return f"{value:.3f}"


def _fmt_health(score: int | None, label: str) -> str:
    if score is None:
        return "unavailable"
    return f"{score}/100 ({label})"


def _fmt_score(sample: StoredSample) -> str:
    if sample.stability_score is None:
        return f"unavailable ({sample.stability_label})"
    return f"{sample.stability_score}/100 ({sample.stability_label})"
