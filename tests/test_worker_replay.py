"""The worker on the recorded day (Mon 2026-10-19), and its weekend / holiday guards."""

import threading
from datetime import date, datetime, time

import pytest
from sqlmodel import func, select

from gatekeeper import store
from gatekeeper import tables as t
from gatekeeper.clock import NY
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.runner import RunResult
from gatekeeper.settings import get_settings
from gatekeeper.skills import entry, exit
from worker.__main__ import main as worker_main
from worker.jobs import JOBS, SCHEDULE, JobContext, enabled_jobs, run_job
from worker.scheduler import fire_times, replay_context, simulate, start_replay

DAY = date(2026, 10, 19)


def new_engine(tmp_path, name="g.db"):
    return init_db(make_engine(f"sqlite:///{(tmp_path / name).as_posix()}"))


def count(s, table, *where):
    return s.exec(select(func.count()).select_from(table).where(*where)).one()


# --- the schedule ----------------------------------------------------------------------------


def test_every_job_has_a_schedule():
    assert set(JOBS) == set(SCHEDULE)


def test_fire_times_on_the_recorded_day():
    t0, t1 = datetime.combine(DAY, time(7, 0), NY), datetime.combine(DAY, time(16, 10), NY)
    orb = [f"{x:%H:%M}" for x in fire_times("orb_scan", t0, t1)]
    assert orb[:4] == ["09:50", "10:00", "10:15", "10:30"] and orb[-1] == "15:45" and len(orb) == 25
    assert [f"{x:%H:%M}" for x in fire_times("daily_scan", t0, t1)] == ["08:30"]
    assert fire_times("universe", t0, t1) == []  # Sundays only
    assert len(fire_times("clock", t0, t1)) == 9 * 60 + 11


def test_disabled_jobs(monkeypatch):
    s = get_settings().model_copy(update={"disabled_jobs": ["pelosi", "nope"]})
    jobs = enabled_jobs(s)
    assert "pelosi" not in jobs and "clock" in jobs


# --- a whole replay day ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def day(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("day")
    engine = new_engine(tmp)
    fires = []
    counts = start_replay(
        get_settings(),
        engine,
        DAY,
        time(7, 0),
        time(16, 10),
        list(JOBS),
        pins=["TSLA"],
        workspace=tmp / "ws",
        on_fire=lambda *x: fires.append(x),
    )
    return engine, counts, fires


def test_no_job_failed(day):
    _, counts, fires = day
    errors = [(f"{tt:%H:%M}", job, detail) for tt, job, st, detail in fires if st == "error"]
    assert errors == []
    assert counts[("clock", "ok")] == 9 * 60 + 11
    late = [(f"{tt:%H:%M}", d) for tt, job, st, d in fires if job == "orb_scan" and st == "skipped"]
    assert late == [("15:30", "not now (late)"), ("15:45", "not now (late)")]


def test_scans(day):
    engine, *_ = day
    with session(engine) as s:
        assert count(s, t.ScanRun, t.ScanRun.scan_mode == "daily") == 1
        orbs = s.exec(select(t.ScanRun).where(t.ScanRun.scan_mode == "orb").order_by(t.ScanRun.id)).all()
        assert len(orbs) == 23  # 25 fire times, 9:50 to 15:45; 15:30 and 15:45 are after the entry cutoff
        assert orbs[0].as_of == "2026-10-19 09:50 ET" and orbs[-1].as_of == "2026-10-19 15:15 ET"
        at_1015 = orbs[2]
        assert (at_1015.as_of, at_1015.hits_count) == ("2026-10-19 10:15 ET", 41)
        tsla = next(h for h in store.scan_hits(s, at_1015) if h.symbol == "TSLA")
        assert (tsla.or_low, tsla.or_high, tsla.price) == (354.47, 362.18, 364.18)


def test_news(day):
    engine, *_ = day
    with session(engine) as s:
        assert count(s, t.NewsItem, t.NewsItem.symbol == "TSLA") > 0
        assert count(s, t.PriceMove, t.PriceMove.symbol == "TSLA") > 0


def test_entry_flips_to_triggered_at_1015(day):
    engine, *_ = day
    with session(engine) as s:
        rows = s.exec(select(t.EntrySignal).order_by(t.EntrySignal.id)).all()
    assert [(r.status, r.checked_ny) for r in rows] == [
        ("waiting", "2026-10-19 09:45:00"),
        ("triggered", "2026-10-19 10:15:00"),
    ]
    assert rows[1].trigger_price == 364.18


def test_entry_watch_stops_after_the_trigger(day):
    _, _, fires = day
    after = [st for tt, job, st, _ in fires if job == "entry_watch" and tt.time() > time(10, 15)]
    assert after and set(after) == {"skipped"}


def test_earnings_and_congress(day):
    engine, *_ = day
    with session(engine) as s:
        assert {e.symbol for e in s.exec(select(t.EarningsSnapshot))} == {"AAPL", "KO"}
        assert count(s, t.PelosiFiling) > 0


def test_heartbeats_for_every_job_that_fired(day):
    engine, *_ = day
    with session(engine) as s:
        beats = {h.job: h for h in store.heartbeats(s, "replay")}
    assert set(beats) == set(JOBS) - {"universe"}  # universe runs on Sundays
    assert all(h.errors == 0 for h in beats.values())
    assert beats["regime"].last_detail == "market context arrives in Phase 3"
    assert beats["eod_journal"].last_status == "skipped"


def test_skill_runs_logged_and_never_overlapping(day):
    engine, *_ = day
    with session(engine) as s:
        runs = s.exec(select(t.SkillRun).where(t.SkillRun.writes_state).order_by(t.SkillRun.started_at)).all()
        total = count(s, t.SkillRun)
    assert total > 50 and runs
    for a, b in zip(runs, runs[1:], strict=False):
        assert (b.started_at - a.started_at).total_seconds() >= a.duration_s - 0.01


# --- alerts and quotes once a plan exists ----------------------------------------------------


def test_flat_by_alert_and_quotes(tmp_path):
    engine = new_engine(tmp_path)
    s0 = get_settings()
    ctx, clock = replay_context(s0, engine, DAY, time(10, 15), workspace=tmp_path / "ws")
    r = ctx.runner("test")
    entry.check("TSLA", write=True, runner=r)
    plan, _ = exit.plan(stop="or-mid", target="1R", runner=r)
    from gatekeeper.skills import alerts

    alerts.add_from_plan(runner=r)
    counts = simulate(ctx, clock, DAY, time(15, 50), time(16, 0), ["quotes", "alerts_check"])
    assert counts[("quotes", "ok")] == 2  # 15:50 and 15:55: a plan for today exists
    with session(engine) as s:
        fired = s.exec(select(t.AlertFired)).all()
    assert [(a.rule_id, a.fired_ny) for a in fired] == [("tsla-flat-by", "2026-10-19 15:56")]


# --- concurrent jobs share trader/ safely ----------------------------------------------------


def test_concurrent_state_writers_do_not_overlap(tmp_path):
    engine = new_engine(tmp_path)
    ctx, clock = replay_context(get_settings(), engine, DAY, time(10, 15), workspace=tmp_path / "ws")
    with session(engine) as s:
        store.pin(s, "TSLA", "replay")
    jobs = ["orb_scan", "intraday_news", "orb_scan", "intraday_news"]
    threads = [threading.Thread(target=run_job, args=(ctx, j)) for j in jobs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    with session(engine) as s:
        runs = s.exec(select(t.SkillRun).where(t.SkillRun.writes_state).order_by(t.SkillRun.started_at)).all()
    assert len(runs) == 4
    for a, b in zip(runs, runs[1:], strict=False):
        assert (b.started_at - a.started_at).total_seconds() >= a.duration_s - 0.01


# --- weekend and holiday guards (task 2.11) --------------------------------------------------


class FakeRunner:
    """Records calls; answers every skill with an error, so a job that runs shows "error"."""

    def __init__(self, trader_dir):
        self.trader_dir = trader_dir
        self.calls = []

    def run(self, tool, args=(), **kw):
        self.calls.append((tool, list(args)))
        return RunResult(tool, list(args), "error", 1, message="fake runner")


@pytest.fixture
def guard_ctx(tmp_path):
    engine = new_engine(tmp_path)
    (tmp_path / "trader").mkdir()
    fake = FakeRunner(tmp_path / "trader")
    holder = {"now": None}
    ctx = JobContext(
        engine=engine,
        mode="live",
        settings=get_settings(),
        make_runner=lambda now, job: fake,
        clock=lambda: holder["now"],
    )
    with session(engine) as s:
        store.pin(s, "TSLA", "live")
    return ctx, holder, fake


def at(holder, d, hh, mm):
    holder["now"] = datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY)


THANKSGIVING = date(2026, 11, 26)
EARLY_CLOSE = date(2026, 11, 27)


@pytest.mark.parametrize(
    ("job", "hhmm"),
    [
        ("analyst_watchlist", (7, 0)),
        ("daily_scan", (8, 30)),
        ("premarket_news", (8, 45)),
        ("orb_scan", (10, 15)),
        ("intraday_news", (10, 15)),
        ("entry_watch", (10, 15)),
        ("quotes", (10, 15)),
        ("alerts_check", (10, 16)),
        ("eod_journal", (16, 10)),
    ],
)
def test_holiday_skips(guard_ctx, job, hhmm):
    ctx, holder, fake = guard_ctx
    at(holder, THANKSGIVING, *hhmm)
    status, detail = run_job(ctx, job)
    assert status == "skipped" and "Thanksgiving" in detail
    assert fake.calls == []


def test_weekend_skips(guard_ctx):
    ctx, holder, fake = guard_ctx
    at(holder, date(2026, 10, 24), 10, 15)  # Saturday
    assert {run_job(ctx, j)[0] for j in ("orb_scan", "intraday_news", "entry_watch", "pelosi")} == {"skipped"}
    assert fake.calls == []


def test_early_close_cuts_the_jobs(guard_ctx):
    ctx, holder, fake = guard_ctx
    at(holder, EARLY_CLOSE, 12, 15)
    assert run_job(ctx, "orb_scan")[0] == "error"  # in the entry window: it ran (the fake runner errs)
    at(holder, EARLY_CLOSE, 12, 45)  # after the 12:30 cutoff, before the 13:00 close
    assert run_job(ctx, "orb_scan")[1] == "not now (late)"
    assert run_job(ctx, "entry_watch")[1] == "not now (late)"
    assert run_job(ctx, "intraday_news")[0] == "error"  # news still runs until the close
    at(holder, EARLY_CLOSE, 13, 0)
    for job in ("orb_scan", "intraday_news", "entry_watch", "quotes", "alerts_check", "regime"):
        assert run_job(ctx, job)[1] == "not now (after_close)", job


# --- the command line ------------------------------------------------------------------------


def test_cli_list_and_once(tmp_path, capsys):
    db = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    assert worker_main(["--list", "--quiet"]) == 0
    assert "orb_scan" in capsys.readouterr().out
    assert worker_main(["--once", "clock", "--db", db, "--quiet"]) == 0  # live clock: no network needed
    engine = init_db(make_engine(db))
    with session(engine) as s:
        (hb,) = store.heartbeats(s, "live")
        assert (hb.job, hb.last_status) == ("clock", "ok")
        assert count(s, t.SkillRun, t.SkillRun.tool == "alerts") == 1


def test_cli_replay_window(tmp_path, capsys):
    db = f"sqlite:///{(tmp_path / 'r.db').as_posix()}"
    assert worker_main(["--replay", "--from", "10:10", "--to", "10:16", "--db", db, "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "entry_watch" in out and "orb_scan" in out
    with session(init_db(make_engine(db))) as s:
        assert store.latest_entry(s, "replay", "TSLA", "2026-10-19").status == "triggered"


def test_cli_pins(tmp_path, capsys):
    db = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    assert worker_main(["--add-pin", "tsla,nvda", "--db", db, "--quiet"]) == 0
    assert worker_main(["--remove-pin", "NVDA", "--db", db, "--quiet"]) == 0
    assert worker_main(["--pins", "--db", db, "--quiet"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Pinned (live): TSLA"
