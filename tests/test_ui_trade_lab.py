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
