from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .constants import default_state_dir
from .state import utc_now


@dataclass(frozen=True)
class QueuedNotification:
    ts: str
    title: str
    message: str
    reason: str | None = None


@dataclass(frozen=True)
class NotificationDelivery:
    notification: QueuedNotification
    delivered: bool
    error: str | None = None


def notify(title: str, message: str) -> tuple[bool, str | None]:
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    try:
        completed = subprocess.run(["osascript", "-e", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    except Exception as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or completed.stdout.strip()
    return True, None


def notify_or_queue(title: str, message: str, reason: str | None = None, state_dir: Path | None = None) -> tuple[bool, str | None, Path | None]:
    ok, error = notify(title, message)
    if ok:
        return True, None, None
    queue_path = queue_notification(title, message, reason=reason or error, state_dir=state_dir)
    return False, error, queue_path


def notification_queue_path(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "notifications.jsonl"


def queue_notification(title: str, message: str, reason: str | None = None, state_dir: Path | None = None) -> Path:
    path = notification_queue_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    item = QueuedNotification(ts=utc_now(), title=title, message=message, reason=reason)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(item), sort_keys=True) + "\n")
    return path


def drain_notifications(state_dir: Path | None = None, limit: int = 20, sender: Callable[[str, str], tuple[bool, str | None]] = notify) -> list[NotificationDelivery]:
    path = notification_queue_path(state_dir)
    if not path.exists():
        return []

    pending: list[QueuedNotification] = []
    malformed = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                pending.append(QueuedNotification(**{key: data.get(key) for key in ("ts", "title", "message", "reason")}))
            except Exception:
                malformed += 1

    delivered: list[NotificationDelivery] = []
    remaining = pending[:]
    for item in pending[: max(0, limit)]:
        ok, error = sender(item.title, item.message)
        delivered.append(NotificationDelivery(notification=item, delivered=ok, error=error))
        if ok:
            remaining.remove(item)
        else:
            break

    if malformed:
        remaining.append(
            QueuedNotification(
                ts=utc_now(),
                title="Meridian notification queue warning",
                message=f"{malformed} malformed notification record(s) were ignored.",
                reason="malformed queue records",
            )
        )
    _write_queue(path, remaining)
    return delivered


def watch_notification_queue(state_dir: Path | None = None, interval: int = 5) -> None:
    while True:
        drain_notifications(state_dir=state_dir)
        time.sleep(max(2, interval))


def queued_notification_count(state_dir: Path | None = None) -> int:
    path = notification_queue_path(state_dir)
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _write_queue(path: Path, items: list[QueuedNotification]) -> None:
    if not items:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(asdict(item), sort_keys=True) + "\n")
    tmp.replace(path)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')[:240]
