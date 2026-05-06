# Security Policy

Meridian Hotspot Stabilizer is local-only network control software. Its safety model is based on narrow ownership and explicit rollback.

## Boundaries

- Meridian does not edit `/etc/pf.conf`.
- Meridian owns only PF anchor `com.apple/meridian-hotspot-stabilizer`.
- Meridian owns only dummynet pipes `57001` and `57002`.
- Meridian does not store provider API keys, passwords, Apple credentials, Claude credentials, or Codex credentials.
- Meridian does not send diagnostics to a server.
- AI agent support exports local context only; authentication stays inside the provider's own tooling.

## Privileged Operations

Current releases use explicit sudo-backed commands for shaping and service installation. The privileged-helper milestone must preserve the allowlist documented in `docs/PRIVILEGED_HELPER.md`.

## Reporting

Until a public security address is assigned, open a private GitHub security advisory on the repository. Do not post credentials, packet captures with private data, or full diagnostic bundles in public issues.

## Diagnostic Bundles

`meridian-stabilizer bundle` redacts the stored PF token and includes only local product evidence. Users should still review bundles before sharing them because interface names, local gateway addresses, timestamps, and logs may reveal operational context.
