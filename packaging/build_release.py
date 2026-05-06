#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INSTALL_ROOT = Path("/usr/local/meridian-hotspot-stabilizer")
BIN_PATH = Path("/usr/local/bin/meridian-stabilizer")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Meridian macOS release artifacts.")
    parser.add_argument("--version", default=_project_version(), help="Release version.")
    parser.add_argument("--sign", action="store_true", help="Sign the package using MERIDIAN_DEVELOPER_ID_INSTALLER.")
    parser.add_argument("--notarize", action="store_true", help="Submit the signed package with xcrun notarytool.")
    parser.add_argument("--notary-profile", default=os.environ.get("MERIDIAN_NOTARY_PROFILE"), help="notarytool keychain profile name.")
    args = parser.parse_args(argv)

    DIST.mkdir(exist_ok=True)
    staging = DIST / "pkg-root"
    if staging.exists():
        shutil.rmtree(staging)
    _stage_payload(staging)

    pkg_path = DIST / f"Meridian-Hotspot-Stabilizer-{args.version}.pkg"
    if pkg_path.exists():
        pkg_path.unlink()

    command = [
        "pkgbuild",
        "--root",
        str(staging),
        "--identifier",
        "com.meridian.hotspot-stabilizer",
        "--version",
        args.version,
        "--scripts",
        str(ROOT / "packaging" / "scripts"),
    ]
    if args.sign:
        identity = os.environ.get("MERIDIAN_DEVELOPER_ID_INSTALLER")
        if not identity:
            raise SystemExit("MERIDIAN_DEVELOPER_ID_INSTALLER is required when --sign is used.")
        command.extend(["--sign", identity])
    command.append(str(pkg_path))
    _run(command)

    if args.notarize:
        if not args.sign:
            raise SystemExit("--notarize requires --sign.")
        if not args.notary_profile:
            raise SystemExit("MERIDIAN_NOTARY_PROFILE or --notary-profile is required for notarization.")
        _run(["xcrun", "notarytool", "submit", str(pkg_path), "--keychain-profile", args.notary_profile, "--wait"])
        _run(["xcrun", "stapler", "staple", str(pkg_path)])

    print(pkg_path)
    return 0


def _stage_payload(staging: Path) -> None:
    app_root = staging / str(INSTALL_ROOT).lstrip("/")
    bin_root = staging / "usr" / "local" / "bin"
    app_root.mkdir(parents=True)
    bin_root.mkdir(parents=True)

    shutil.copytree(ROOT / "meridian_stabilizer", app_root / "meridian_stabilizer", ignore=_ignore_release_junk)
    shutil.copy2(ROOT / "README.md", app_root / "README.md")
    shutil.copy2(ROOT / "pyproject.toml", app_root / "pyproject.toml")

    wrapper = bin_root / "meridian-stabilizer"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH=\"{INSTALL_ROOT}:${{PYTHONPATH:-}}\"\n"
        "exec /usr/bin/env python3 -m meridian_stabilizer \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    _remove_release_junk(staging)


def _project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in pyproject.splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    return "0.0.0"


def _ignore_release_junk(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name == "__pycache__" or name == ".DS_Store" or name.startswith("._") or name.endswith(".pyc"):
            ignored.add(name)
    return ignored


def _remove_release_junk(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.name == "__pycache__" or path.name == ".DS_Store" or path.name.startswith("._") or path.suffix == ".pyc":
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def _run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
