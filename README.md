# Meridian Hotspot Stabilizer

Meridian Hotspot Stabilizer is a macOS-only CLI that reduces hotspot bufferbloat by applying conservative PF/dummynet bandwidth shaping on the active internet interface.

It cannot create cellular capacity that your phone/carrier does not have. Its job is to trade a little peak throughput for steadier calls, lower jitter, and fewer stalls when the hotspot link is under load.

## Quick Start

Run diagnostics without changing network settings:

```sh
python3 -m meridian_stabilizer doctor
```

Start shaping for work calls:

```sh
python3 -m meridian_stabilizer start --profile calls
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

Install a privileged background launchd service:

```sh
python3 -m meridian_stabilizer install-service
```

Remove the background service:

```sh
python3 -m meridian_stabilizer uninstall-service
```

## Notes

- `doctor` is read-only and does not require admin privileges.
- `start`, `stop`, `tune`, and service installation require admin privileges. The CLI invokes `sudo` for the underlying system commands when needed.
- The tool loads rules into a dedicated PF anchor under `com.apple/meridian-hotspot-stabilizer` and does not edit `/etc/pf.conf`.
- State and logs default to `~/.meridian-hotspot-stabilizer`.

## Development

Run the unit tests:

```sh
python3 -m unittest discover -s tests
```

Dry-run the generated system rules:

```sh
python3 -m meridian_stabilizer start --profile calls --dry-run
```

# Meridian-Hotspot-Stabilizer
