"""The paper-trading period (Phase P): your evening rules, the checklist, the weekly review.

Nothing here places orders or touches a broker. It sets up `trader/config.json` for the hours you
are awake in India, checks the Phase P checklist against what the database shows, and turns the
journal into one review row per week.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlmodel import Session, col, select

from gatekeeper import config_edit, journal, store
from gatekeeper.clock import IST, NY
from gatekeeper.settings import Settings
from gatekeeper.tables import Plan

# Entries 09:45 to 11:00 NY and flat by 12:00 NY: 19:15 to 21:30 IST in summer time, an hour
# later from the first Sunday of November. Both fit the default awake hours (18:30 to 23:30 IST).
EVENING_WINDOW = {"no_entries_before": "09:45", "no_entries_after": "11:00", "flat_by": "12:00"}
WEEKS = 8


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def ny_to_ist(hhmm: str, day: date) -> str:
    """A New York wall-clock time on `day`, as IST (HH:MM)."""
    return f"{datetime.combine(day, _t(hhmm), NY).astimezone(IST):%H:%M}"


def in_awake(ist: str, awake: str) -> bool:
    """True when an IST time falls inside AWAKE_IST (which may run past midnight, e.g. 18:30-01:30)."""
    start, end = (_t(x) for x in awake.split("-"))
    t = _t(ist)
    return start <= t <= end if start <= end else (t >= start or t <= end)


PLACEHOLDER_AGENT = "Your Name you@example.com"


def set_rules(
    path: Path, example: Path, backups: Path, window: dict[str, str] | None = None, sec_user_agent: str = ""
):
    """Writes the evening window into trader/config.json (from the skills' example when it's missing).

    A new file takes `sec_user_agent` from .env, never the example's placeholder. Returns (backup,
    changes) like `config_edit.save`. `paper` is never changed; a new file starts on paper.
    """
    doc = config_edit.load(path)
    if not doc:
        doc = json.loads(example.read_text(encoding="utf-8"))
        doc.pop("sec_user_agent", None)
        if sec_user_agent:
            doc["sec_user_agent"] = sec_user_agent
    elif doc.get("sec_user_agent") == PLACEHOLDER_AGENT:
        doc.pop("sec_user_agent")
        if sec_user_agent:
            doc["sec_user_agent"] = sec_user_agent
    return config_edit.save(path, {**doc, **(window or EVENING_WINDOW)}, backups)


# --- the checklist ---------------------------------------------------------------------------


@dataclass
class Item:
    check: str
    ok: bool | None  # None: only you can tell (e.g. the broker connection lives in Claude)
    detail: str


def last_weekday(today: date) -> date:
    """The latest Monday-to-Friday strictly before `today` (holidays aside)."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def period_start(s: Session, settings: Settings) -> date | None:
    """PAPER_START from .env, else the day of the first live plan."""
    if settings.paper_start:
        return date.fromisoformat(settings.paper_start)
    first = s.exec(select(Plan).where(Plan.mode == "live").order_by(col(Plan.date))).first()
    return date.fromisoformat(first.date) if first else None


def live_plans(s: Session, since: date | None, until: date) -> list[Plan]:
    """The latest plan per symbol per day, from `since` up to and including `until`."""
    days = sorted(
        {
            p.date
            for p in s.exec(select(Plan).where(Plan.mode == "live"))
            if (since is None or p.date >= since.isoformat()) and p.date <= until.isoformat()
        }
    )
    return [p for d in days for p in store.plans_for_day(s, "live", d)]


def checklist(s: Session, settings: Settings, trader_dir: Path, now: datetime) -> list[Item]:
    """The Phase P checklist, checked against the config, the worker's heartbeats and the database."""
    today = now.astimezone(NY).date()
    items = []

    cfg = config_edit.load(trader_dir / "config.json")
    if not cfg:
        items.append(Item("trader/config.json for your IST window", False, "missing: run `paper.py rules`"))
    else:
        times = {k: cfg.get(k) for k in ("no_entries_before", "no_entries_after", "flat_by")}
        ist = {k: ny_to_ist(v, today) for k, v in times.items() if v}
        late = [k for k, v in ist.items() if not in_awake(v, settings.awake_ist)]
        ok = bool(cfg.get("paper", True)) and not late and len(ist) == 3
        detail = (
            f"entries {times['no_entries_before']}–{times['no_entries_after']} NY "
            f"({ist.get('no_entries_before')}–{ist.get('no_entries_after')} IST), "
            f"flat by {times['flat_by']} NY "
            f"({ist.get('flat_by')} IST), paper={cfg.get('paper', True)}"
        )
        if late:
            detail += f"; outside AWAKE_IST {settings.awake_ist}: {', '.join(late)}"
        items.append(Item("trader/config.json for your IST window", ok, detail))

    items.append(
        Item(
            "Alpaca (or IBKR) paper account connected in Claude",
            None,
            "only you can check this: /trader-broker in Claude chat, paper mode, keys in env vars",
        )
    )

    beats = store.heartbeats(s, "live")
    # only weekday runs count: a weekend run (a test) says nothing about the trading days
    runs = sorted(
        b.last_run_ny for b in beats if b.last_run_ny and date.fromisoformat(b.last_run_ny[:10]).weekday() < 5
    )
    want = last_weekday(today)
    if not runs:
        items.append(
            Item("Worker running every US trading day", False, "the live worker hasn't run on a weekday yet")
        )
    else:
        last = runs[-1]
        items.append(
            Item(
                "Worker running every US trading day",
                last[:10] >= want.isoformat(),
                f"last live job at {last} NY (wanted on or after {want})",
            )
        )
    items.append(
        Item(
            "Notifications on",
            settings.notify != "none",
            f"NOTIFY={settings.notify}"
            + ("" if settings.notify != "none" else ": set toast or telegram in .env"),
        )
    )

    start = period_start(s, settings)
    plans = live_plans(s, start, today)
    setups = sorted({f"{p.setup or '?'} · {p.stop_rule or '?'} stop · {p.target_r or '?'}R" for p in plans})
    items.append(
        Item(
            "One setup only",
            len(setups) == 1 if setups else None,
            "no live plans yet" if not setups else "; ".join(setups),
        )
    )
    # today's plans can still be decided until the close, so they don't count as missing yet
    done = [p for p in plans if p.date < today.isoformat() or now.astimezone(NY).time() >= time(16, 0)]
    missing = [p for p in done if store.decision_for_plan(s, "live", p.id) is None]
    items.append(
        Item(
            "Every plan has a Taken or Skipped decision",
            not missing if done else None,
            f"{len(done) - len(missing)} of {len(done)} decided"
            + (f"; missing: {', '.join(f'{p.symbol} {p.date}' for p in missing[:5])}" if missing else ""),
        )
    )
    decided = len(done) - len(missing)
    items.append(
        Item(
            f"{journal.MIN_TRADES}+ decisions logged",
            decided >= journal.MIN_TRADES,
            f"{decided} of {journal.MIN_TRADES}" + (f" since {start}" if start else ""),
        )
    )
    return items


# --- the weekly review -----------------------------------------------------------------------


def weekly_review(trades: list[journal.Trade], start: date, weeks: int = WEEKS) -> list[dict]:
    """One row per week of the period: plans, taken, skipped, expectancy (taken / all), adherence."""
    rows = []
    for w in range(1, weeks + 1):
        lo, hi = start + timedelta(days=7 * (w - 1)), start + timedelta(days=7 * w)
        ts = [t for t in trades if t.day and lo.isoformat() <= t.day < hi.isoformat()]
        taken = [t for t in ts if t.taken and not t.simulated]
        rows.append(
            {
                "week": w,
                "from": lo.isoformat(),
                "plans": len(ts),
                "taken": sum(t.taken for t in ts),
                "skipped": sum(not t.taken and t.followed_rules is not None for t in ts),
                "expectancy_taken": journal.stats(taken)["expectancy_r"],
                "expectancy_all": journal.stats(ts)["expectancy_r"],
                "adherence": journal.stats(ts)["adherence_rate"],
            }
        )
    return rows


def _r(x: float | None) -> str:
    return "" if x is None else f"{x:+.2f}R"


def review_line(row: dict, notes: str = "") -> str:
    """The tracker's table row for one week (blank cells for a week with no plans)."""
    if not row["plans"]:
        return f"| {row['week']} | | | | | | |{' ' + notes + ' ' if notes else ' '}|"
    adh = "" if row["adherence"] is None else f"{row['adherence']:.0%}"
    return (
        f"| {row['week']} | {row['plans']} | {row['taken']} | {row['skipped']} "
        f"| {_r(row['expectancy_taken'])} "
        f"| {_r(row['expectancy_all'])} | {adh} | from {row['from']}{'; ' + notes if notes else ''} |"
    )


ROW = re.compile(r"^\| ([1-8]) \|.*\|$")


def update_guide(text: str, rows: list[dict]) -> str:
    """Rewrites the weeks of the Phase P table in IMPLEMENTATION_GUIDE.md, keeping everything else."""
    a = text.index("## Phase P:")
    b = text.index("\n---", a)
    by_week = {r["week"]: r for r in rows}
    out = []
    for line in text[a:b].split("\n"):
        m = ROW.match(line)
        out.append(review_line(by_week[int(m.group(1))]) if m and int(m.group(1)) in by_week else line)
    return text[:a] + "\n".join(out) + text[b:]
