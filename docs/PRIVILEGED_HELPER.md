# Meridian Privileged Helper Contract

Meridian currently uses explicit sudo-backed commands for privileged operations. The production helper target is a signed macOS privileged helper with a narrow allowlist.

The helper must not be a general command runner.

## Allowed Authority

- configure Meridian-owned dummynet upload pipe `57001`
- configure Meridian-owned dummynet download pipe `57002`
- load PF rules only into anchor `com.apple/meridian-hotspot-stabilizer`
- flush only that PF anchor
- delete only Meridian-owned pipes `57001` and `57002`
- release only the PF token acquired by Meridian
- install or remove the Meridian launchd plist

## Forbidden Authority

- editing `/etc/pf.conf`
- loading arbitrary PF anchors
- executing shell strings
- accepting arbitrary command arrays from the client
- changing non-Meridian dummynet pipes
- reading browser, Claude, Codex, SSH, Apple ID, or API credentials
- sending network telemetry to a server

## Client Contract

The CLI sends structured requests. The helper validates every field before execution:

- operation name
- interface name
- upload/download caps
- owned pipe IDs
- owned PF anchor
- optional redacted PF token reference

The helper returns structured results:

- command outcome
- stdout/stderr summary
- applied owned resources
- explicit rollback status when an operation fails

## Current Code Hook

The Python module `meridian_stabilizer.privileged` defines the allowlisted command plan that the signed helper must preserve. It is intentionally boring and narrow; that is the security feature.
