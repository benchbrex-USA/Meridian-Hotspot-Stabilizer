from __future__ import annotations

import subprocess


def notify(title: str, message: str) -> tuple[bool, str | None]:
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    try:
        completed = subprocess.run(["osascript", "-e", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    except Exception as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or completed.stdout.strip()
    return True, None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')[:240]

