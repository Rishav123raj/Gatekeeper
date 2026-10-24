"""Gatekeeper's background worker.

    uv run python -m worker                       # live: run the jobs on the New York schedule
    uv run python -m worker --list                # the jobs and their next run (New York / IST)
    uv run python -m worker --once orb_scan       # run one job now (live)
    uv run python -m worker --run-for 600         # live for 10 minutes, then stop cleanly
    uv run python -m worker --add-pin TSLA,NVDA   # tickers the entry watch follows (--pins lists them)
    uv run python -m worker --replay --from 09:30 --to 10:30 --speed 600
                                                  # fast-forward the recorded day (2026-10-19)

Logs go to the console and to data/worker.log; results go to the database (DB_URL).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date, datetime, time

from gatekeeper import store
from gatekeeper.clock import fmt_dual, now_ny
from gatekeeper.db import get_engine, init_db, make_engine, session
from gatekeeper.replay import REPLAY_DATE
from gatekeeper.settings import ROOT, get_settings
from worker.jobs import JOBS, enabled_jobs, run_job
from worker.scheduler import live_context, next_runs, start_live, start_replay

log = logging.getLogger("gatekeeper.worker")


def setup_logging(quiet: bool = False) -> None:
    (ROOT / "data").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [logging.FileHandler(ROOT / "data" / "worker.log", encoding="utf-8")]
    if not quiet:
        handlers.append(logging.StreamHandler(sys.stdout))
    for h in handlers:
        h.setFormatter(fmt)
    root = logging.getLogger("gatekeeper")
    root.setLevel(logging.INFO)
    root.handlers[:] = handlers
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def hhmm(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"want HH:MM, got {value!r}") from e


def _tickers(value: str | None) -> list[str]:
    return [t.strip().upper() for t in (value or "").split(",") if t.strip()]


def print_summary(counts: Counter[tuple[str, str]]) -> None:
    print("\njob                 ok  empty skipped error")
    for job in JOBS:
        row = [counts[(job, st)] for st in ("ok", "empty", "skipped", "error")]
        if any(row):
            print(f"{job:18} {row[0]:3} {row[1]:6} {row[2]:7} {row[3]:5}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m worker", description="Gatekeeper's background worker.")
    ap.add_argument("--list", action="store_true", help="show the jobs and their next run, then exit")
    ap.add_argument("--once", metavar="JOB", choices=sorted(JOBS), help="run one job now (live), then exit")
    ap.add_argument("--run-for", type=float, metavar="SECONDS", help="live: stop cleanly after this long")
    ap.add_argument(
        "--replay", action="store_true", help="fast-forward a recorded day instead of running live"
    )
    ap.add_argument(
        "--date", default=REPLAY_DATE, help=f"replay day (default {REPLAY_DATE}, the recorded one)"
    )
    ap.add_argument(
        "--from", dest="start", type=hhmm, default=time(8, 0), help="replay start, HH:MM New York"
    )
    ap.add_argument("--to", dest="end", type=hhmm, default=time(16, 10), help="replay end, HH:MM New York")
    ap.add_argument(
        "--speed",
        type=float,
        default=0,
        help="replay pace: 600 = ten simulated minutes a second; 0 (default) = no waiting",
    )
    ap.add_argument("--pin", default="TSLA", help="replay: comma-separated tickers for the entry watch")
    ap.add_argument("--keep", action="store_true", help="replay: keep earlier replay rows in the database")
    ap.add_argument("--pins", action="store_true", help="live: list the tickers the entry watch follows")
    ap.add_argument(
        "--add-pin", metavar="TICKERS", help="live: pin comma-separated tickers for the entry watch"
    )
    ap.add_argument("--remove-pin", metavar="TICKERS", help="live: unpin comma-separated tickers")
    ap.add_argument("--db", help="database URL (default DB_URL from .env)")
    ap.add_argument("--quiet", action="store_true", help="log to data/worker.log only")
    a = ap.parse_args(argv)

    settings = get_settings()
    setup_logging(a.quiet)
    engine = init_db(make_engine(a.db)) if a.db else get_engine()
    jobs = enabled_jobs(settings)

    if a.pins or a.add_pin or a.remove_pin:
        with session(engine) as s:
            for sym in _tickers(a.add_pin):
                store.pin(s, sym, "live")
            for sym in _tickers(a.remove_pin):
                store.unpin(s, sym, "live")
        with session(engine) as s:
            print("Pinned (live): " + (", ".join(store.pinned(s, "live")) or "none"))
        return 0

    if a.list:
        now = now_ny()
        print(f"Now {fmt_dual(now)} ({now:%a %Y-%m-%d}). Next runs:")
        for job, t in next_runs(list(JOBS), now).items():
            state = "" if job in jobs else "   (disabled)"
            print(
                f"  {job:18} {fmt_dual(t) if t else 'never'}  {t:%a %d %b}{state}"
                if t
                else f"  {job:18} never"
            )
        return 0

    if a.once:
        status, detail = run_job(live_context(settings, engine), a.once)
        return 0 if status != "error" else 1

    if a.replay:
        day = date.fromisoformat(a.date)
        log.info(
            "replay %s %s to %s New York (speed %s), jobs: %s",
            day,
            a.start,
            a.end,
            a.speed or "max",
            ", ".join(jobs),
        )
        counts = start_replay(
            settings,
            engine,
            day,
            a.start,
            a.end,
            jobs,
            pins=_tickers(a.pin),
            fresh=not a.keep,
            speed=a.speed,
        )
        print_summary(counts)
        return 1 if any(st == "error" for _, st in counts) else 0

    start_live(live_context(settings, engine), jobs, run_for=a.run_for)
    return 0


if __name__ == "__main__":
    sys.exit(main())
