"""The Trade Lab page in replay at 10:15: every golden number on the page, the comparison,
and the banner when trader/plan.json changes outside the dashboard."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from gatekeeper.settings import ROOT, get_settings

PAGE = str(ROOT / "app" / "pages" / "3_Trade_Lab.py")


def plan_file():
    s = get_settings()
    return s.resolve(s.replay_workspace) / "trader" / "plan.json"


def metrics(at):
    return {m.label: m.value for m in at.metric}


def markdown(at):
    return "\n".join(m.value for m in at.markdown)


@pytest.fixture(scope="module")
def lab(replay_env):
    """Entry checked, exit planned at 1R, Time Machine run to the close: the documented trade."""
    at = AppTest.from_file(PAGE, default_timeout=180).run()
    assert at.selectbox(key="lab_pick").value == "TSLA"
    at.button(key="lab_check").click().run()
    at.selectbox(key="lab_target").select("1R").run()
    at.button(key="lab_plan").click().run()
    at.radio(key="lab_until").set_value("close").run()
    at.button(key="lab_tm").click().run()
    return at


def test_no_errors(lab):
    assert not lab.exception and not lab.error, [e.value for e in [*lab.exception, *lab.error]]


def test_entry_triggered(lab):
    text = markdown(lab)
    assert ":green-badge[TRIGGERED]" in text
    assert "Triggered **10:15 AM** at **$364.18**: the 10:10 bar (bar 8)" in text


def test_chart_has_the_trigger_and_the_plan(lab):
    spec = json.loads(lab.get("plotly_chart")[0].proto.spec)
    marker = next(t for t in spec["data"] if t.get("name") == "entry trigger")
    assert marker["y"] == [364.18]
    notes = [a["text"] for a in spec["layout"]["annotations"]]
    assert {"entry 364.18", "stop 358.32", "target 370.04", "flat by 15:55"} <= set(notes)


def test_exit_plan(lab):
    m = metrics(lab)
    assert (m["Entry"], m["Stop"], m["Target"], m["Risk / share"], m["Reward : risk"]) == (
        "$364.18",
        "$358.32",
        "$370.04",
        "$5.86",
        "1.0",
    )
    assert m["Flat by"] == "15:55 NY"
    assert plan_file().exists()


def test_time_machine(lab):
    m = metrics(lab)
    assert (m["Target first"], m["Stop first"], m["Neither by 16:00"], m["Green"], m["Average R"]) == (
        "29.4 %",
        "25.5 %",
        "45.1 %",
        "51.7 %",
        "+0.034",
    )
    text = markdown(lab)
    assert "**Close to a coin flip: target first 29.4 % vs stop first 25.5 %.**" in text
    assert "fired 33 times: 13 target, 15 stop, 5 neither" in text
    assert "45.1 % of the replays hit neither by 4:00 PM" in text  # the tool's note, verbatim
    assert any("seed 19" in c.value for c in lab.caption)
    assert len(lab.get("plotly_chart")) == 4  # candles, odds, fan, histogram


def test_compare_leaves_plan_json_alone(lab):
    before = plan_file().read_bytes()
    lab.button(key="lab_compare").click().run()
    assert plan_file().read_bytes() == before
    df = lab.dataframe[-1].value
    assert list(df["Plan"]) == ["or-mid / 1R", "or-mid / 2R", "or-low / 1R", "or-low / 2R"]
    one_r = df.iloc[0]
    assert (one_r["Target first %"], one_r["Stop first %"], one_r["Neither %"]) == (29.4, 25.5, 45.1)
    assert (df.iloc[1]["Target"], df.iloc[2]["Stop"]) == (375.9, 354.47)


def test_go_no_go_before_sizing_is_no_trade(lab):
    assert any(m.value == "#### Trade: TSLA: :red-badge[NO TRADE]" for m in lab.markdown)
    assert any("⛔ **Risk check** · not checked yet: run Size & check" in m.value for m in lab.markdown)


def test_size_and_check_then_caution(lab):
    lab.button(key="lab_size").click().run()
    assert not lab.exception and not lab.error
    text = markdown(lab)
    assert "**8 shares** · $2,913.44 · $46.88 at the stop · bound by **max loss**" in text
    assert any(s.value.startswith("check.py PASS") for s in lab.success)
    assert "#### Trade: TSLA: :orange-badge[CAUTION]" in text
    assert (
        "⚠️ **Time Machine verdict** · Close to a coin flip: target first 29.4 % vs stop first 25.5 %" in text
    )
    assert "⚠️ **Earnings outside the trade**" in text
    assert "✅ **Risk check** · PASS: max loss $46.88, reward:risk 1.0" in text
    (code,) = [c.value for c in lab.code]
    assert code.startswith("/trader-broker\nOrder 1 in trader/orders.json passed trader-risk")


def test_decision_is_logged(lab):
    from gatekeeper import store
    from gatekeeper.db import get_engine, session

    next(w for w in lab.text_input if w.label == "Note").input("coin flip; skipping")
    next(b for b in lab.button if b.label == "Log: Skipped").click().run()
    assert any(s.value == "Logged SKIPPED for TSLA (Go / No-Go was CAUTION)." for s in lab.success)
    with session(get_engine()) as s:
        d = store.decisions(s, "replay")[0]
    assert (d.action, d.symbol, d.overall, d.reason_note, d.followed_rules) == (
        "SKIPPED",
        "TSLA",
        "CAUTION",
        "coin flip; skipping",
        True,
    )
    assert d.plan_id is not None and d.readiness_id is not None


def test_home_day_panel(replay_env):
    home = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=120).run()
    text = markdown(home)
    assert "#### Today: :orange-badge[CAUTION]" in text
    assert "⛔ **Awake window (IST)** · flat-by 15:55 NY is 01:25 IST" in text
    assert "✅ **Breadth** · 18 % of usable charts broke their opening range" in text


def test_external_plan_change_shows_a_banner(lab):
    path = plan_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["target"] = 375.9  # as if Claude chat re-planned it at 2R
    path.write_text(json.dumps(doc), encoding="utf-8")
    lab.run()
    assert any("Plan updated externally" in w.value for w in lab.warning)
    lab.button(key="lab_reload").click().run()
    assert metrics(lab)["Target"] == "$375.90"
    assert not any("Plan updated externally" in w.value for w in lab.warning)
