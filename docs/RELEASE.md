# Meridian Release Process

Meridian release artifacts are built from the CLI code in this repository. The build path supports unsigned local packages for internal testing and signed/notarized packages when Apple credentials are present.

## Local Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q -x '(^|/)\._' meridian_stabilizer tests
python3 -m meridian_stabilizer readiness
```

## Build Unsigned Package

```sh
python3 packaging/build_release.py
```

The unsigned package is written to `dist/`.

## Build Signed Package

Set the installer identity exactly as it appears in Keychain:

```sh
export MERIDIAN_DEVELOPER_ID_INSTALLER="Developer ID Installer: Example, Inc. (TEAMID)"
python3 packaging/build_release.py --sign
```

## Notarize

Store Apple notary credentials in a keychain profile outside this repository:

```sh
xcrun notarytool store-credentials meridian-notary
export MERIDIAN_NOTARY_PROFILE="meridian-notary"
python3 packaging/build_release.py --sign --notarize
```

No Apple credentials, passwords, API keys, Claude keys, or Codex tokens belong in this repository.

## Release Standard

- release artifacts are produced from committed source
- signing identities come from Keychain or CI secrets
- notarization credentials come from a keychain profile
- diagnostic and product telemetry remains local unless the user explicitly shares a bundle
- missing production inputs are reported as unavailable, never invented
