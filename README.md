# Meridian Hotspot Stabilizer

Meridian Hotspot Stabilizer is a macOS CLI for making phone-hotspot internet more usable under unstable cellular conditions. It measures the active link, detects bufferbloat symptoms, and applies conservative PF/dummynet traffic shaping so latency-sensitive work stays responsive when the hotspot is under load.

Meridian is intentionally honest about the physics: it does not manufacture carrier bandwidth, bypass tower congestion, or turn a weak radio signal into a strong one. It improves the part the laptop can control: queue pressure, upload saturation, recovery behavior, and operator visibility.

There is no demo mode. There is no fake dashboard data. Every metric printed by the CLI comes from local system commands or the local SQLite history written by prior real runs. If a value cannot be measured, Meridian prints `unavailable`.

## What It Solves

Phone hotspots often look fast in a raw speed test but feel terrible during calls because upload traffic fills queues between the Mac, phone, carrier, and upstream network. That queueing delay shows up as jitter, stalls, robotic audio, frozen video, slow DNS, and remote desktop lag.

Meridian attacks that failure mode by keeping the laptop slightly below the point where the hotspot link starts buffering aggressively. The result is usually lower latency under load, fewer spikes, and a more stable working connection at the cost of some peak throughput.

## System Design

```text
meridian-stabilizer CLI
        |
        v
measurement layer
  - route
  - ping
  - networkQuality
        |
        v
policy engine
  - profiles
  - stability scoring
  - adaptive cap decisions
        |
        v
system shaper
  - PF anchor: com.apple/meridian-hotspot-stabilizer
  - dummynet pipes: owned Meridian pipe IDs only
        |
        v
local state
  - JSON state
  - SQLite metrics and events
  - local logs
```

The project is CLI-first by design. The dashboard is a terminal dashboard, not a web app. The background mode is launchd-backed, but it still runs the same CLI engine.

## Safety Model

Meridian is built around narrow ownership boundaries.

- It does not edit `/etc/pf.conf`.
- It loads rules into a dedicated PF anchor: `com.apple/meridian-hotspot-stabilizer`.
- It uses dedicated dummynet pipe IDs owned by Meridian.
- `stop` and `panic` remove only Meridian-owned PF/dnctl state.
- `preflight` validates the current route, required macOS commands, and generated PF/dnctl syntax before shaping.
- `doctor` and `dashboard` can run without changing network shaping rules.
- Privileged operations are explicit and use `sudo` when system shaping is required.

Current production boundary: Meridian is a hardened CLI foundation, not yet a signed macOS installer with a signed privileged helper. Until that layer exists, privileged operations remain sudo-backed.

## Installation

Requirements:

- macOS
- Python 3.11+
- Built-in macOS tools: `route`, `ping`, `networkQuality`, `pfctl`, `dnctl`, `launchctl`

Run from the repository root:

```sh
python3 -m meridian_stabilizer --help
```

Optional editable install:

```sh
python3 -m pip install -e .
```

After that, the console command is available as:

```sh
meridian-stabilizer --help
```

## Quick Start

Run a production preflight:

```sh
python3 -m meridian_stabilizer preflight
```

Inspect the current hotspot link without changing shaping:

```sh
python3 -m meridian_stabilizer doctor --profile calls
```

Start shaping for work calls:

```sh
python3 -m meridian_stabilizer start --profile calls
```

Run the adaptive tuner in the foreground:

```sh
python3 -m meridian_stabilizer run --profile calls
```

Open the real terminal dashboard:

```sh
python3 -m meridian_stabilizer dashboard
```

Stop shaping:

```sh
python3 -m meridian_stabilizer stop
```

Emergency stop:

```sh
python3 -m meridian_stabilizer panic
```

## Command Reference

| Command | Purpose |
| --- | --- |
| `preflight` | Validate macOS support, required commands, active route, live ping, and PF/dnctl syntax. |
| `profiles` | List the built-in tuning profiles. |
| `doctor` | Run real diagnostics and recommend measured or fallback caps. |
| `start` | Apply Meridian-owned PF/dnctl shaping rules. |
| `run` | Start shaping and keep the adaptive tuner running in the foreground. |
| `dashboard` | Render a live terminal dashboard using real local measurements. |
| `tune` | Measure the current link and adjust active caps. |
| `status` | Print stored state, last metrics, and optional system shaper state. |
| `events` | Show local real events recorded by Meridian. |
| `report` | Print or export a local real-data diagnostic report. |
| `stop` | Remove Meridian-owned shaping rules. |
| `panic` | Emergency stop that clears owned rules and marks Meridian inactive. |
| `install-service` | Install the launchd-backed CLI watcher. |
| `uninstall-service` | Remove the launchd service. |

## Profiles

Meridian ships with four explicit operating profiles:

- `calls`: protects video calls and work apps from upload-driven latency spikes.
- `gaming`: favors very low jitter and quick recovery over raw throughput.
- `downloads`: keeps bulk transfers fast while still limiting severe bufferbloat.
- `auto`: balanced adaptive mode for mixed browsing, calls, and downloads.

List exact thresholds and fallback caps:

```sh
python3 -m meridian_stabilizer profiles
```

## Data and Storage

Meridian stores local operational data under:

```text
~/.meridian-hotspot-stabilizer/
```

Files include:

- `state.json`: current active state, caps, interface, gateway, and watcher heartbeat.
- `metrics.sqlite3`: real samples and events.
- `stabilizer.log`: local operational logs.
- `service.out.log` / `service.err.log`: launchd service logs when installed.

No metrics are sent anywhere by this codebase. The current product is local-only.

## Real-Data Dashboard

The dashboard is deliberately plain and trustworthy:

```sh
python3 -m meridian_stabilizer dashboard
```

It shows:

- active profile and shaping state
- active interface and gateway
- current upload/download caps
- gateway latency and jitter
- internet latency, jitter, max spike, and packet loss
- measured capacity when `networkQuality` is requested
- recent local events
- stability score derived from measured latency, jitter, loss, and responsiveness

To render one sample and exit:

```sh
python3 -m meridian_stabilizer dashboard --once
```

To include periodic `networkQuality` capacity measurements:

```sh
python3 -m meridian_stabilizer dashboard --quality-every 300
```

## Background Operation

Install the launchd watcher:

```sh
python3 -m meridian_stabilizer install-service --profile calls --interval 60
```

Remove it:

```sh
python3 -m meridian_stabilizer uninstall-service
```

The service uses the same CLI engine as foreground `run`. It records real samples and events into the local SQLite database.

## Operational Examples

Run a full read-only inspection:

```sh
python3 -m meridian_stabilizer preflight
python3 -m meridian_stabilizer doctor --profile calls
python3 -m meridian_stabilizer report
```

Start cautiously with a dry run:

```sh
python3 -m meridian_stabilizer start --profile calls --dry-run
```

Start with manual caps:

```sh
python3 -m meridian_stabilizer start --profile calls --upload-mbps 8 --download-mbps 25
```

Inspect system shaping state:

```sh
python3 -m meridian_stabilizer status --system
```

Export a machine-readable report:

```sh
python3 -m meridian_stabilizer report --json
```

## Development

Run tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Run a syntax-only shaping dry run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m meridian_stabilizer start --profile calls --dry-run
```

Compile-check the package:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q -x '(^|/)\._' meridian_stabilizer tests
```

## Production Roadmap

The next production hardening milestones are:

- signed macOS `.pkg` installer
- signed privileged helper instead of raw sudo-backed commands
- stricter service lifecycle supervision
- automatic diagnostic bundle generation
- better per-application traffic awareness where macOS exposes reliable signals
- release artifacts and reproducible build pipeline

Meridian should earn trust by being boring in the right places: real measurements, narrow system ownership, explicit failure modes, clean rollback, and no invented data.
