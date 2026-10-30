"""Running the jobs: live on APScheduler, or a replay day on a simulated clock.

Both read `SCHEDULE`: the live scheduler builds APScheduler cron triggers from it, and the
simulator asks the same triggers for their fire times inside the replay window, then runs
the due jobs in order without waiting (or slowed down with `speed`).
"""

from __future__ import annotations

import logging
import time as _time
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.engine import Engine

from gatekeeper import store
from gatekeeper.clock import NY, as_ny, now_ny
from gatekeeper.db import session
from gatekeeper.replay import ReplayContext, prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.settings import Settings
from gatekeeper.tables import ReplayState, utcnow
from worker.jobs import JOBS, SCHEDULE, JobContext, enabled_jobs, run_job

log = logging.getLogger("gatekeeper.worker")


def cron_triggers(job: str) -> list[CronTrigger]:
    return [CronTrigger(timezone=NY, **rule) for rule in SCHEDULE[job]]


def fire_times(job: str, start: datetime, end: datetime) -> list[datetime]:
    """When `job` fires between start and end (both New York, inclusive), from its cron rules."""
    times: set[datetime] = set()
    for trig in cron_triggers(job):
        t = trig.get_next_fire_time(None, start - timedelta(microseconds=1))
        while t is not None and t <= end:
            times.add(t)
            t = trig.get_next_fire_time(t, t + timedelta(seconds=1))
    return sorted(times)


def next_runs(jobs: list[str], now: datetime) -> dict[str, datetime | None]:
    out = {}
    for job in jobs:
        nxt = [t for t in (trig.get_next_fire_time(None, now) for trig in cron_triggers(job)) if t]
        out[job] = min(nxt) if nxt else None
    return out


# --- contexts --------------------------------------------------------------------------------


def live_context(settings: Settings, engine: Engine) -> JobContext:
    def make_runner(_now: datetime, job: str) -> SkillRunner:
        return SkillRunner.from_settings(
            settings,
            lock_timeout=settings.worker_lock_timeout,
            on_result=store.skill_run_logger(engine, "live", job),
        )

    from gatekeeper.notify import notify

    return JobContext(
        engine=engine,
        mode="live",
        settings=settings,
        make_runner=make_runner,
        clock=now_ny,
        notifier=lambda title, body, urgent=False: notify(title, body, urgent=urgent, settings=settings),
    )


class SimClock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def replay_context(
    settings: Settings,
    engine: Engine,
    day: date,
    start: time,
    *,
    workspace: Path | None = None,
    skills_dir: Path | None = None,
    fresh: bool = True,
) -> tuple[JobContext, SimClock]:
    """A replay context whose clock the simulator moves; `fresh` wipes the workspace's trader/ first."""
    clock = SimClock(datetime.combine(day, start, NY))
    # the workspace and skills of the settings passed in (a public-demo visitor has their own)
    workspace = Path(workspace or settings.resolve(settings.replay_workspace))
    skills = Path(skills_dir or settings.skills_path)
    if fresh:
        rctx = prepare_workspace(clock.t.replace(tzinfo=None), workspace, skills)
    else:
        rctx = ReplayContext(clock.t.replace(tzinfo=None), workspace, skills / "tests" / "fixtures")

    def make_runner(now: datetime, job: str) -> SkillRunner:
        return SkillRunner.from_settings(
            settings,
            replay=rctx.at(now.replace(tzinfo=None)),
            lock_timeout=settings.worker_lock_timeout,
            on_result=store.skill_run_logger(engine, "replay", job),
        )

    ctx = JobContext(engine=engine, mode="replay", settings=settings, make_runner=make_runner, clock=clock)
    return ctx, clock


# --- replay simulator ------------------------------------------------------------------------


def simulate(
    ctx: JobContext,
    clock: SimClock,
    day: date,
    start: time,
    end: time,
    jobs: list[str],
    *,
    speed: float = 0,
    on_fire: Callable[[datetime, str, str, str], None] | None = None,
) -> Counter[tuple[str, str]]:
    """Fires every due job from start to end on `day`, in schedule order. Returns (job, status) counts."""
    t0, t1 = datetime.combine(day, start, NY), datetime.combine(day, end, NY)
    due: dict[datetime, list[str]] = {}
    for job in jobs:
        for t in fire_times(job, t0, t1):
            due.setdefault(t, []).append(job)
    order = {j: i for i, j in enumerate(JOBS)}
    counts: Counter[tuple[str, str]] = Counter()
    prev = None
    for t in sorted(due):
        if speed and prev is not None:
            _time.sleep((t - prev).total_seconds() / speed)
        prev = clock.t = t
        for job in sorted(due[t], key=order.__getitem__):
            status, detail = run_job(ctx, job)
            counts[(job, status)] += 1
            if on_fire:
                on_fire(t, job, status, detail)
    return counts


def start_replay(
    settings: Settings,
    engine: Engine,
    day: date,
    start: time,
    end: time,
    jobs: list[str],
    *,
    pins: list[str] = ("TSLA",),
    fresh: bool = True,
    speed: float = 0,
    workspace: Path | None = None,
    skills_dir: Path | None = None,
    on_fire: Callable[[datetime, str, str, str], None] | None = None,
) -> Counter[tuple[str, str]]:
    if fresh:
        with session(engine) as s:
            store.clear_mode(s, "replay")
    with session(engine) as s:
        for sym in pins:
            store.pin(s, sym, "replay")
    ctx, clock = replay_context(settings, engine, day, start, workspace=workspace, skills_dir=skills_dir)
    return simulate(ctx, clock, day, start, end, jobs, speed=speed, on_fire=on_fire)


REPLAY_DAY_START = time(7, 0)


def sync_replay(
    settings: Settings,
    engine: Engine,
    until: datetime,
    *,
    workspace: Path | None = None,
    skills_dir: Path | None = None,
) -> str:
    """Brings the replay day up to `until` (New York), simulating only what hasn't run yet.

    Moving forward continues from the last simulated minute; moving back (or a new day, or a
    missing workspace) starts again from 07:00 with a fresh workspace, keeping the replay pins.
    Returns what it did, in one line.
    """
    until = as_ny(until).replace(second=0, microsecond=0)
    day, end = until.date(), until.time()
    ws = Path(workspace or settings.resolve(settings.replay_workspace))
    jobs = enabled_jobs(settings)
    with session(engine) as s:
        st = s.get(ReplayState, 1)
        pins = store.pinned(s, "replay") or ["TSLA"]
    done = None
    if (
        st
        and st.day == day.isoformat()
        and st.workspace == str(ws)
        and (ws / "trader" / "config.json").exists()
    ):
        done = datetime.strptime(st.until_ny, "%H:%M").time()
    if done is not None and done == end:
        return f"replay already at {end:%H:%M}"
    if done is not None and done < end:
        nxt = (datetime.combine(day, done) + timedelta(minutes=1)).time()
        ctx, clock = replay_context(
            settings, engine, day, nxt, workspace=ws, skills_dir=skills_dir, fresh=False
        )
        counts = simulate(ctx, clock, day, nxt, end, jobs)
        how = f"replay moved on from {done:%H:%M} to {end:%H:%M}"
    else:
        start = min(REPLAY_DAY_START, end)
        counts = start_replay(
            settings, engine, day, start, end, jobs, pins=pins, workspace=ws, skills_dir=skills_dir
        )
        how = f"replay rebuilt from {start:%H:%M} to {end:%H:%M}"
    with session(engine) as s:
        st = s.get(ReplayState, 1) or ReplayState(day=day.isoformat(), until_ny="", workspace=str(ws))
        st.day, st.until_ny, st.workspace, st.updated_at = day.isoformat(), f"{end:%H:%M}", str(ws), utcnow()
        s.add(st)
    errors = sum(n for (_, status), n in counts.items() if status == "error")
    return how + (f" ({errors} job errors, see the worker health table)" if errors else "")


# --- live scheduler --------------------------------------------------------------------------


def start_live(ctx: JobContext, jobs: list[str], *, run_for: float | None = None) -> None:
    """Runs until Ctrl+C (or for `run_for` seconds), then shuts down cleanly."""
    sched = BackgroundScheduler(
        timezone=NY, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120}
    )
    for job in jobs:
        sched.add_job(run_job, OrTrigger(cron_triggers(job)), args=(ctx, job), id=job, name=job)
    sched.start()
    log.info("worker started: %d jobs, New York time; Ctrl+C to stop", len(jobs))
    deadline = _time.monotonic() + run_for if run_for else None
    try:
        while deadline is None or _time.monotonic() < deadline:
            _time.sleep(1)
    except KeyboardInterrupt:
        log.info("stopping (Ctrl+C)...")
    finally:
        sched.shutdown(wait=True)
        log.info("worker stopped cleanly")
