# Meridian Hotspot Stabilizer

Meridian Hotspot Stabilizer is a macOS-only production CLI that reduces phone-hotspot bufferbloat by applying conservative PF/dummynet bandwidth shaping on the active internet interface.

It cannot create cellular capacity that your phone/carrier does not have. Its job is to trade a little peak throughput for steadier calls, lower jitter, and fewer stalls when the hotspot link is under load.

Meridian does not ship demo data. Dashboard, reports, events, and recommendations use real local measurements only. If a metric cannot be collected, the CLI prints `unavailable` instead of inventing a value.

## Quick Start

Run preflight checks:

```sh
python3 -m meridian_stabilizer preflight
```

Run real diagnostics without changing network settings:

```sh
python3 -m meridian_stabilizer doctor
```

Start shaping for work calls:

```sh
python3 -m meridian_stabilizer start --profile calls
```

Run the adaptive tuner in the foreground:

```sh
python3 -m meridian_stabilizer run --profile calls
```

Open the real CLI dashboard:

```sh
python3 -m meridian_stabilizer dashboard
```

Check current status:

```sh
python3 -m meridian_stabilizer status
```

Tune the active caps after a fresh measurement:

```sh
python3 -m meridian_stabilizer tune
```

Stop shaping and remove only this tool's PF/dummynet rules:

```sh
python3 -m meridian_stabilizer stop
```

Emergency stop:

```sh
python3 -m meridian_stabilizer panic
```

Install a privileged background launchd service:

```sh
python3 -m meridian_stabilizer install-service
```

Remove the background service:

```sh
python3 -m meridian_stabilizer uninstall-service
```

## Production CLI Surface

- `preflight`: validates macOS, required commands, current route, live ping, and generated PF/dnctl syntax.
- `profiles`: lists `calls`, `gaming`, `downloads`, and `auto` tuning profiles.
- `doctor`: collects real diagnostics and recommends measured or fallback caps.
- `start`: applies owned PF/dnctl rules through the dedicated Meridian anchor.
- `run`: starts shaping and keeps the adaptive tuner alive in the foreground.
- `dashboard`: terminal dashboard backed by live ping data and optional real `networkQuality` measurements.
- `tune`: measures the active link and adjusts caps.
- `status`: prints current state, last metrics, and optional PF/dnctl system state.
- `events`: shows real events stored locally.
- `report`: exports a real local diagnostic report.
- `panic`: clears owned rules and marks Meridian inactive.

## Notes

- `doctor` is read-only and does not require admin privileges.
- `start`, `stop`, `tune`, and service installation require admin privileges. The CLI invokes `sudo` for the underlying system commands when needed.
- The tool loads rules into a dedicated PF anchor under `com.apple/meridian-hotspot-stabilizer` and does not edit `/etc/pf.conf`.
- State, logs, and the SQLite metrics database default to `~/.meridian-hotspot-stabilizer`.
- The dashboard is CLI-native; there is no web server, sample dataset, or fake full-stack demo.

## Development

Run the unit tests:

```sh
python3 -m unittest discover -s tests
```

Dry-run the generated system rules:

```sh
python3 -m meridian_stabilizer start --profile calls --dry-run
```
