"""The end-of-day journal on the recorded day: simulated, real and 'needs fill' rows (task 7.7)."""

from datetime import date, time

import pytest
from sqlmodel import select

from gatekeeper import store
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.settings import get_settings
from gatekeeper.skills import broker, entry, exit
from gatekeeper.tables import TradeJournal
from worker.jobs import run_job
from worker.scheduler import replay_context

DAY = date(2026, 10, 19)


@pytest.fixture
def world(tmp_path):
    """The TSLA 1R plan made at 10:15 and stored, then the clock moved to 16:10."""
    engine = init_db(make_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}"))
    ctx, clock = replay_context(get_settings(), engine, DAY, time(10, 15), workspace=tmp_path / "ws")
    r = ctx.runner("test")
    entry.check("TSLA", write=True, runner=r)
    plan, _ = exit.plan(stop="or-mid", target="1R", runner=r)
    with session(engine) as s:
        plan_id = store.save_plan(s, plan, "replay").id
    clock.t = clock.t.replace(hour=16, minute=10)
    return engine, ctx, r, plan_id


def rows(engine):
    with session(engine) as s:
        return s.exec(select(TradeJournal)).all()


def test_no_decision_is_simulated(world):
    engine, ctx, _, plan_id = world
    status, detail = run_job(ctx, "eod_journal")
    assert status == "ok" and detail.startswith("TSLA simulated +0.43R (data_end)")
    (j,) = rows(engine)
    # the recorded bars stop at 10:45: out at that bar's close, 366.68 → (366.68 - 364.18) / 5.86
    assert (j.plan_id, j.simulated, j.exit_reason, j.exit_time, j.exit_fill) == (
        plan_id,
        True,
        "data_end",
        "10:45",
        366.68,
    )
    assert j.r_result == 0.427 and j.notes == "no decision: simulated"


def test_skipped_is_simulated_and_linked(world):
    engine, ctx, _, plan_id = world
    with session(engine) as s:
        did = store.save_decision(s, "replay", "SKIPPED", plan_id=plan_id, symbol="TSLA", note="coin flip").id
    run_job(ctx, "eod_journal")
    (j,) = rows(engine)
    assert (j.decision_id, j.simulated, j.r_result) == (did, True, 0.427)
    with session(engine) as s:
        (t,) = store.journal_trades(s, "replay")
    assert (t.taken, t.simulated, t.r, t.setup, t.entry_time) == (False, True, 0.427, "orb", "10:15 AM")


def test_taken_without_fills_needs_fill_then_gets_its_real_r(world):
    engine, ctx, r, plan_id = world
    with session(engine) as s:
        store.save_decision(s, "replay", "TAKEN", plan_id=plan_id, symbol="TSLA")
    assert run_job(ctx, "eod_journal")[1] == "TSLA needs fill"
    (j,) = rows(engine)
    assert (j.needs_fill, j.r_result, j.exit_reason) == (True, None, "needs_fill")
    broker.fill("TSLA", "buy", 8, 364.20, runner=r)
    broker.fill("TSLA", "sell", 8, 370.04, runner=r)
    assert run_job(ctx, "eod_journal")[1] == "TSLA taken +1.00R"
    (j,) = rows(engine)  # the same row, updated: one row per plan
    assert (j.needs_fill, j.simulated, j.entry_fill, j.exit_fill, j.r_result, j.exit_reason) == (
        False,
        False,
        364.2,
        370.04,
        0.997,
        "target",
    )


def test_no_plans_skips(tmp_path):
    engine = init_db(make_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}"))
    ctx, clock = replay_context(get_settings(), engine, DAY, time(16, 10), workspace=tmp_path / "ws")
    assert run_job(ctx, "eod_journal") == ("skipped", "no plans today")


def test_only_after_the_close(world):
    _, ctx, _, _ = world
    ctx.clock.t = ctx.clock.t.replace(hour=15, minute=0)
    assert run_job(ctx, "eod_journal") == ("skipped", "not now (entry_window)")
