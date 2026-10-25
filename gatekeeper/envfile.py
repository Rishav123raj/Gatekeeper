"""Updating a few keys in .env without disturbing the rest (comments, order, secrets).

Only the dashboard's own, non-secret settings are written from the Settings page; keys and
tokens (ALPACA_*, TELEGRAM_BOT_TOKEN, SEC_USER_AGENT) are never shown or written there.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

EDITABLE = {"CORE_TICKERS", "AWAKE_IST", "NOTIFY", "DISABLED_JOBS", "FULL_UNIVERSE_ORB", "PAPER_START"}
EDITABLE_PREFIX = "GATE_"
LINE = re.compile(r"^\s*([A-Z0-9_]+)\s*=(.*)$")


def editable(key: str) -> bool:
    return key in EDITABLE or key.startswith(EDITABLE_PREFIX)


def update(path: Path, values: dict[str, str], backups: Path | None = None) -> Path | None:
    """Sets each key (replacing its line, or adding it at the end). Returns the backup, if any."""
    bad = [k for k in values if not editable(k)]
    if bad:
        raise ValueError(f"not editable from the dashboard: {', '.join(bad)}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    backup = None
    if path.exists() and backups is not None:
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"env-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.bak"
        shutil.copyfile(path, backup)
    left = dict(values)
    out = []
    for line in lines:
        m = LINE.match(line)
        if m and m.group(1) in left:
            out.append(f"{m.group(1)}={left.pop(m.group(1))}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in left.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return backup
