"""The Risk & Size and Positions & Alerts pages in replay at 10:15, with the documented trade planned."""

import json
from datetime import datetime

import pytest
from streamlit.testing.v1 import AppTest

from gatekeeper.replay import ReplayContext
from gatekeeper.runner import SkillRunner
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.skills import broker, budget, entry, exit, risk

RISK = str(ROOT / "app" / "pages" / "4_Risk_Size.py")
POSITIONS = str(ROOT / "app" / "pages" / "5_Positions_Alerts.py")
LAB = str(ROOT / "app" / "pages" / "3_Trade_Lab.py")


def trader_dir():
    s = get_settings()
    return s.resolve(s.replay_workspace) / "trader"


@pytest.fixture(scope="module")
def planned(replay_env):
    """The documented trade in the replay workspace: entry, 1R plan, 8-share bracket, PASS."""
    s = get_settings()
    ctx = ReplayContext(
        datetime(2026, 10, 19, 10, 15), s.resolve(s.replay_workspace), s.skills_path / "tests" / "fixtures"
    )
    r = SkillRunner.from_settings(s, replay=ctx)
    entry.check("TSLA", write=True, runner=r)
    exit.plan(stop="or-mid", target="1R", runner=r)
    budget.size(runner=r)
    risk.check(runner=r)
    return r


def rules_table(at):
    return next(d.value for d in at.dataframe if "Level" in d.value.columns)


def text(at):
    return "\n".join(m.value for m in at.markdown)


def test_trade_lab_adds_the_plan_alerts(planned):
    at = AppTest.from_file(LAB, default_timeout=180).run()
    at.button(key="lab_check").click().run()
    at.selectbox(key="lab_target").select("1R").run()
    at.button(key="lab_plan").click().run()
    at.button(key="lab_alerts").click().run()
    assert any(
        s.value.startswith("Alerts set: tsla-plan-stop, tsla-plan-target, tsla-flat-by") for s in at.success
    )


def test_risk_page_shows_limits_and_the_pass(planned):
    at = AppTest.from_file(RISK, default_timeout=180).run()
    assert not at.exception and not at.error
    m = {x.label: x.value for x in at.metric}
    assert (m["Budget"], m["Max loss / trade"], m["Max loss / day"], m["Account"]) == (
        "$5,000.00",
        "$50.00",
        "$150.00",
        "PAPER",
    )
    assert "**8 shares** · $2,913.44 · $46.88 at the stop · bound by **max loss**" in text(at)
    assert [s.value for s in at.success] == [
        "PASS #1 buy TSLA 8 shares (entry): max loss $46.88, reward:risk 1.0"
    ]
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)  # the four limits, the binding one marked
    assert any("decides" in t for t in spec["data"][0]["text"])


def test_what_if_nine_shares_is_blocked_and_trader_is_untouched(planned):
    before = {p.name: p.read_bytes() for p in trader_dir().glob("*.json")}
    at = AppTest.from_file(RISK, default_timeout=180).run()
    at.number_input(key="wi_qty").set_value(9).run()
    at.button(key="wi_run").click().run()
    assert any(e.value.startswith("BLOCK: max loss $52.74") for e in at.error)
    assert {p.name: p.read_bytes() for p in trader_dir().glob("*.json")} == before


def test_positions_countdown_and_rules(planned):
    at = AppTest.from_file(POSITIONS, default_timeout=180).run()
    assert not at.exception
    assert at.info[0].value == "Flat by 15:55 NY · 01:25 IST: **5 h 40 min** left"
    rules = rules_table(at)
    assert list(rules["Id"]) == ["tsla-plan-stop", "tsla-plan-target", "tsla-flat-by"]
    assert list(rules["Level"]) == ["358.32", "370.04", "15:55"]


def test_record_a_fill_then_the_position_in_r(planned):
    at = AppTest.from_file(POSITIONS, default_timeout=180).run()
    next(w for w in at.text_input if w.label == "Ticker").input("TSLA")
    next(w for w in at.selectbox if w.label == "Side").select("buy")
    next(w for w in at.number_input if w.label == "Shares").set_value(8.0)
    next(w for w in at.number_input if w.label == "Price").set_value(364.20)
    next(b for b in at.button if b.label == "Record fill").click().run()
    assert any(s.value.startswith("Recorded buy 8.0 TSLA at $364.20") for s in at.success)
    at.run()
    pos = next(d.value for d in at.dataframe if "To stop (R)" in d.value.columns).iloc[0]
    assert (pos["Ticker"], pos["Shares"], pos["Avg cost"], pos["Last"]) == ("TSLA", 8.0, 364.2, 364.18)
    assert (pos["To stop (R)"], pos["To target (R)"]) == (1.0, 1.0)
    ledger = [r for r in broker.records(planned) if r.status == "filled"]
    assert [(r.side, r.qty, r.price) for r in ledger] == [("buy", "8", 364.2)]  # ticket.py writes "8"


def test_closing_ticket(planned):
    at = AppTest.from_file(POSITIONS, default_timeout=180).run()
    at.button(key="flat_go").click().run()
    assert [s.value for s in at.success] == ["check.py PASS: sell TSLA 8 shares (exit)"]
    (code,) = [c.value for c in at.code]
    assert "Ticket: SELL 8 shares of TSLA, market order" in code
    assert "Cancel the bracket's open stop-loss and take-profit orders" in text(at)
    orders = json.loads((trader_dir() / "orders.json").read_text(encoding="utf-8"))["orders"]
    assert [(o["side"], o["qty"]) for o in orders] == [("sell", "8")]  # a proposal only: nothing was sent


def test_add_a_rule(planned):
    at = AppTest.from_file(POSITIONS, default_timeout=180).run()
    form_select = next(w for w in at.selectbox if w.label == "When")
    form_select.select("pct")
    next(w for w in at.text_input if w.label == "Ticker (not for times / the bell)").input("TSLA")
    next(w for w in at.text_input if w.label == "Level, % or HH:MM").input("3")
    next(b for b in at.button if b.label == "Add rule").click().run()
    assert not at.error
    at.run()
    rules = rules_table(at)
    assert "3 %" in list(rules["Level"])
