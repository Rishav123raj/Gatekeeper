"""The documented TSLA trade on Mon 2026-10-19, end to end through the wrappers.

Every number here is a golden number from IMPLEMENTATION_GUIDE.md. If one differs,
check the pinned skills commit first; never edit a number to make the test pass.
"""

import json
from datetime import date, datetime

import pytest

from gatekeeper.clock import market_day, session_phase
from gatekeeper.replay import prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.skills import alerts, broker, budget, entry, exit, risk, scanner, timemachine

D = (2026, 10, 19)


@pytest.fixture(scope="module")
def ctx(tmp_path_factory, skills_dir):
    return prepare_workspace(datetime(*D, 10, 15), tmp_path_factory.mktemp("replay"), skills_dir)


def at(ctx, h, m):
    return SkillRunner.from_settings(replay=ctx.at(datetime(*D, h, m)))


@pytest.fixture(scope="module")
def chain(ctx):
    """orb -> entry -> exit -> timemachine -> budget -> risk, at 10:15."""
    r = at(ctx, 10, 15)
    out = {}
    out["orb"], _ = scanner.orb(runner=r)
    out["entry"], _ = entry.check("TSLA", write=True, runner=r)
    out["plan"], _ = exit.plan(stop="or-mid", target="1R", runner=r)
    out["tm"], _ = timemachine.run(runner=r)
    out["size"], _ = budget.size(runner=r)
    out["risk"], res = risk.check(runner=r)
    out["risk_status"] = res.status
    return out


def test_orb_scan_with_no_price_floor(ctx):
    scan, res = scanner.orb(min_price=0, write=False, runner=at(ctx, 10, 15))
    assert res.status == "ok"
    assert len(scan.hits) == 42 and scan.scanned == 231
    tsla = next(h for h in scan.hits if h.symbol == "TSLA")
    assert (tsla.or_low, tsla.or_high, tsla.price, tsla.pct_over) == (354.47, 362.18, 364.18, 0.55)
    assert tsla.at == "10:15 AM"


def test_orb_scan_default_floor(chain):
    assert len(chain["orb"].hits) == 41


def test_entry_waiting_at_1012(ctx):
    status, res = entry.check("TSLA", runner=at(ctx, 10, 12))
    assert res.status == "empty"
    assert status.status == "waiting"
    assert status.last["close"] == 361.68 and status.level == 362.18
    assert round(status.level - status.last["close"], 2) == 0.50


def test_entry_triggered_at_1015(chain):
    trig = chain["entry"].trigger
    assert chain["entry"].triggered
    assert (trig.time, trig.price, trig.bar_index, trig.bar_start) == ("10:15 AM", 364.18, 8, "10:10")


def test_entry_with_volume_check(ctx):
    status, _ = entry.check("TSLA", min_volume_x=1, runner=at(ctx, 10, 40))
    assert (status.trigger.time, status.trigger.price) == ("10:35 AM", 365.75)


def test_exit_plan(chain):
    p = chain["plan"]
    assert (p.stop, p.target, p.risk_per_share) == (358.32, 370.04, 5.86)
    assert round(100 * p.risk_per_share / p.entry, 2) == 1.61


def test_time_machine(chain):
    mc, hist = chain["tm"].mc, chain["tm"].history
    assert (mc.seed, mc.replays, mc.until) == (19, 10_000, "16:00")
    assert (mc.p_target, mc.p_stop, mc.p_neither, mc.p_green) == (0.2938, 0.2548, 0.4514, 0.5168)
    assert mc.avg_R == 0.034
    assert (hist.sessions, hist.triggered, hist.target, hist.stop, hist.close) == (59, 33, 13, 15, 5)
    assert hist.avg_R == -0.062
    assert chain["tm"].verdict.startswith("Close to a coin flip")
    assert len(mc.sample_paths) == 160  # read back from the written file


def test_time_machine_variant_leaves_the_plan_alone(ctx, chain):
    plan_file = ctx.workspace / "trader" / "plan.json"
    before = plan_file.read_bytes()
    tm, res = timemachine.run_plan(
        "TSLA", "2026-10-19", 364.18, 358.32, 370.04, "10:15 AM", runner=at(ctx, 10, 15)
    )
    assert res.status == "ok"
    assert (tm.mc.p_target, tm.mc.p_stop) == (0.2938, 0.2548)  # same plan, same seed, same numbers
    assert plan_file.read_bytes() == before


def test_budget(chain):
    s = chain["size"].sizing
    assert (s.qty, s.cost, s.max_loss, s.bound_by) == (8, 2913.44, 46.88, "max loss")
    assert chain["size"].orders[0].qty == "8"


def test_risk_pass(chain):
    assert chain["risk_status"] == "ok"
    v = chain["risk"].results[0]
    assert v.verdict == "PASS" and v.max_loss == 46.88
    assert chain["risk"].cash_after == 2086.56


def test_risk_blocks_nine_shares(ctx, chain):
    doc = json.loads((ctx.workspace / "trader" / "orders.json").read_text(encoding="utf-8"))
    doc["orders"][0]["qty"] = "9"
    (ctx.workspace / "trader" / "orders-9.json").write_text(json.dumps(doc), encoding="utf-8")
    report, res = risk.check(no_write=True, orders_path="trader/orders-9.json", runner=at(ctx, 10, 15))
    assert res.status == "blocked"
    v = report.results[0]
    assert v.verdict == "BLOCK" and v.max_loss == 52.74
    assert any("$52.74" in r and "$50" in r for r in v.reasons)


def test_risk_blocks_before_the_window(ctx, chain):
    report, res = risk.check(no_write=True, runner=at(ctx, 9, 40))
    assert res.status == "blocked"
    assert report.results[0].reasons[0].startswith("window:")


def test_budget_refuses_a_far_stop(ctx, chain):
    plan = json.loads((ctx.workspace / "trader" / "plan.json").read_text(encoding="utf-8"))
    plan["stop"], plan["risk_per_share"] = 300.0, 64.18
    (ctx.workspace / "trader" / "plan-300.json").write_text(json.dumps(plan), encoding="utf-8")
    size, res = budget.size(plan_path="trader/plan-300.json", write=False, runner=at(ctx, 10, 15))
    assert res.status == "blocked" and size.refused
    assert "$64.18" in size.sizing.refusal


def test_ticket_and_the_yes(ctx, chain):
    r = at(ctx, 10, 15)
    tickets, res = broker.show(runner=r)
    assert res.status == "ok" and tickets[0].ready
    assert broker.approve(1, "sure", runner=r).status == "blocked"
    assert broker.approve(1, "yes", runner=r).status == "ok"
    rows, _ = broker.log(runner=r)
    assert [x.status for x in rows] == ["approved"]


def test_flat_by_alert(ctx, chain):
    rules, _ = alerts.add_from_plan(runner=at(ctx, 10, 15))
    assert {x.id for x in rules} == {"tsla-plan-stop", "tsla-plan-target", "tsla-flat-by"}
    result, res = alerts.check(no_write=True, runner=at(ctx, 15, 56))
    assert res.status == "ok"
    assert [x.id for x in result.rings] == ["tsla-flat-by"]


# --- the NYSE calendar in the session phase (task 1.19) -------------------------------------


def test_thanksgiving_is_closed():
    day = market_day(date(2026, 11, 26))
    assert day is not None and not day.trading_day
    assert session_phase(datetime(2026, 11, 26, 10, 15), day=day) == "closed"


def test_early_close_moves_the_cutoff():
    day = market_day(date(2026, 11, 27))
    assert day.closes == "13:00"
    assert session_phase(datetime(2026, 11, 27, 12, 15), day=day) == "entry_window"
    assert session_phase(datetime(2026, 11, 27, 12, 45), day=day) == "late"  # cutoff 15:30 -> 12:30
    assert session_phase(datetime(2026, 11, 27, 13, 0), day=day) == "after_close"


def test_regular_day_unchanged():
    day = market_day(date(2026, 10, 19))
    assert session_phase(datetime(2026, 10, 19, 15, 45), day=day) == "late"
