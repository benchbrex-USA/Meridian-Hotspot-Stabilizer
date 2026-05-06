from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "meridian-hotspot-stabilizer"
APP_TITLE = "Meridian Hotspot Stabilizer"
ANCHOR = "com.apple/meridian-hotspot-stabilizer"
UPLOAD_PIPE = 57001
DOWNLOAD_PIPE = 57002
PLIST_LABEL = "com.meridian.hotspot-stabilizer"
PLIST_PATH = Path("/Library/LaunchDaemons") / f"{PLIST_LABEL}.plist"
NOTIFIER_PLIST_LABEL = "com.meridian.hotspot-stabilizer.notify"
NOTIFIER_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{NOTIFIER_PLIST_LABEL}.plist"


def default_state_dir() -> Path:
    override = os.environ.get("MERIDIAN_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".meridian-hotspot-stabilizer"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
