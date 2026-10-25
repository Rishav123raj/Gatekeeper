"""Editing trader/config.json safely: validate, show the diff, back up, then save.

`paper` can never be changed here. Going live is your own decision, made by editing the file
yourself; Gatekeeper refuses to save any change to it, whatever the form sent.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class TraderConfig(BaseModel):
    """The rules the skills read (trader-budget's config.example.json). Unknown keys are kept."""

    model_config = ConfigDict(extra="allow")

    budget: float = Field(gt=0)
    cash_buffer_pct: float = Field(ge=0, le=100)
    max_position_pct: float = Field(gt=0, le=100)
    max_order_usd: float = Field(gt=0)
    min_order_usd: float = Field(ge=0)
    max_loss_per_trade_usd: float = Field(gt=0)
    max_daily_loss_usd: float = Field(gt=0)
    max_trades_per_day: int = Field(ge=1)
    max_orders_per_day: int = Field(ge=1)
    min_reward_risk: float = Field(gt=0)
    require_stop: bool = True
    no_entries_before: str | None = "09:45"
    no_entries_after: str | None = "15:30"
    flat_by: str = "15:55"
    fractional: bool = False
    broker: str = "alpaca"
    paper: bool = True
    blocked: list[str] = []
    allow_options: bool = False
    allow_margin: bool = False
    allow_short: bool = False
    pdt_guard: bool = False
    sec_user_agent: str = ""

    @field_validator("no_entries_before", "no_entries_after", "flat_by")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v is not None and not HHMM.match(v):
            raise ValueError("use HH:MM, New York time (e.g. 09:45)")
        return v

    @field_validator("blocked")
    @classmethod
    def _tickers(cls, v: list[str]) -> list[str]:
        return sorted({t.strip().upper() for t in v if t.strip()})


class PaperChangeRefused(ValueError):
    """Raised for any attempt to change `paper` through Gatekeeper."""


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """(key, before, after) for every key that changes."""
    return [(k, old.get(k), new.get(k)) for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]


def validate(new: dict[str, Any]) -> dict[str, Any]:
    """The config as it would be saved (normalised), or a pydantic ValidationError."""
    return TraderConfig.model_validate(new).model_dump()


def save(path: Path, new: dict[str, Any], backups: Path) -> tuple[Path | None, list[tuple[str, Any, Any]]]:
    """Validates, refuses a `paper` change, backs up the current file, then writes the new one.

    Returns (the backup path, the changes). Nothing is written when nothing changes.
    """
    old = load(path)
    clean = validate(new)
    if old and bool(clean.get("paper")) != bool(old.get("paper", True)):
        raise PaperChangeRefused("paper can't be changed from Gatekeeper: edit trader/config.json yourself")
    if not old:
        clean["paper"] = True  # a new config always starts on paper
    changes = diff(old, clean)
    if not changes:
        return None, []
    backup = None
    if path.exists():
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup = backups / f"config-{stamp}.json"
        backup.write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return backup, changes
