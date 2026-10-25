"""The paper-trading period (Phase P) from the command line.

    uv run python scripts/paper.py rules            # trader/config.json for your evening (backed up first)
    uv run python scripts/paper.py start [--date D] # PAPER_START in .env: day 1 of the period (default today)
    uv run python scripts/paper.py status           # the Phase P checklist, from your real data
    uv run python scripts/paper.py review [--update-guide]   # one row per week; optionally into the tracker

Nothing here places orders or talks to a broker.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gatekeeper import envfile, paper, store  # noqa: E402
from gatekeeper.clock import now_ny  # noqa: E402
from gatekeeper.db import get_engine, session  # noqa: E402
from gatekeeper.settings import get_settings  # noqa: E402

MARK = {True: "✅", False: "⬜", None: "❔"}


def cmd_rules(_: argparse.Namespace) -> int:
    s = get_settings()
    path = s.trader_path / "config.json"
    example = s.skills_path / "trader-budget" / "config.example.json"
    backup, changes = paper.set_rules(
        path, example, s.resolve(s.backups_dir), sec_user_agent=s.sec_user_agent
    )
    if not changes and backup is None and path.exists():
        print(f"{path}: already set for the evening window, nothing written")
    else:
        print(f"{path}: written" + (f" (backup {backup})" if backup else " (new file, paper: true)"))
        for k, a, b in changes:
            print(f"  {k}: {a} -> {b}")
    today = now_ny().date()
    w = paper.EVENING_WINDOW
    print(
        f"Today that is entries {paper.ny_to_ist(w['no_entries_before'], today)}–"
        f"{paper.ny_to_ist(w['no_entries_after'], today)} IST, "
        f"flat by {paper.ny_to_ist(w['flat_by'], today)} IST."
    )
    print("Budget and max loss are the skills' example values: change them on the Settings page if you like.")
    return 0


def cmd_start(a: argparse.Namespace) -> int:
    s = get_settings()
    day = a.date or now_ny().date()
    backup = envfile.update(s.resolve(s.env_path), {"PAPER_START": day.isoformat()}, s.resolve(s.backups_dir))
    print(f"PAPER_START={day} written to {s.resolve(s.env_path)}" + (f" (backup {backup})" if backup else ""))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    s = get_settings()
    with session(get_engine()) as db:
        items = paper.checklist(db, s, s.trader_path, now_ny())
        start = paper.period_start(db, s)
    print(f"Paper-trading period: {'from ' + str(start) if start else 'not started (no live plans yet)'}\n")
    for i in items:
        print(f"  {MARK[i.ok]}  {i.check}\n      {i.detail}")
    return 0 if all(i.ok is not False for i in items) else 1


def cmd_review(a: argparse.Namespace) -> int:
    s = get_settings()
    with session(get_engine()) as db:
        start = paper.period_start(db, s)
        trades = store.journal_trades(db, "live")
    if start is None:
        print("No live plans yet: the review starts with your first plan (or set it with `paper.py start`).")
        return 0
    rows = paper.weekly_review(trades, start)
    print(
        "| Week | Plans | Taken | Skipped | Expectancy (taken) "
        "| Expectancy (all, incl. simulated) | Adherence | Notes |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        print(paper.review_line(r))
    if a.update_guide:
        guide = ROOT / "IMPLEMENTATION_GUIDE.md"
        text = guide.read_text(encoding="utf-8")
        new = paper.update_guide(text, [r for r in rows if r["plans"]])
        guide.write_bytes(new.encode("utf-8"))
        print(f"\n{guide.name}: weeks with plans written into the Phase P table")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # the checklist marks, on a Windows console too
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rules", help="set trader/config.json for the evening window")
    st = sub.add_parser("start", help="set PAPER_START in .env")
    st.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD (default: today in New York)")
    sub.add_parser("status", help="the Phase P checklist")
    rv = sub.add_parser("review", help="the weekly review table")
    rv.add_argument("--update-guide", action="store_true", help="write it into IMPLEMENTATION_GUIDE.md")
    a = ap.parse_args()
    return {"rules": cmd_rules, "start": cmd_start, "status": cmd_status, "review": cmd_review}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
