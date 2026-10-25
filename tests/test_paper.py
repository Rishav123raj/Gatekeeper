"""The paper-trading period: evening rules in IST, the checklist, the weekly review (Phase P)."""

import json
from datetime import date, datetime

import pytest

from gatekeeper import config_edit, paper
from gatekeeper.clock import NY
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.journal import Trade
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.tables import Decision, JobHeartbeat, Plan

EXAMPLE = get_settings().skills_path / "trader-budget" / "config.example.json"


def test_the_window_in_ist_moves_with_new_york_summer_time():
    # Mon 26 Oct 2026: New York on EDT (IST = NY + 9:30); Mon 2 Nov: EST (+10:30)
    assert [paper.ny_to_ist(t, date(2026, 10, 26)) for t in ("09:45", "11:00", "12:00")] == [
        "19:15",
        "20:30",
        "21:30",
    ]
    assert [paper.ny_to_ist(t, date(2026, 11, 2)) for t in ("09:45", "11:00", "12:00")] == [
        "20:15",
        "21:30",
        "22:30",
    ]


@pytest.mark.parametrize(
    ("t", "awake", "ok"),
    [
        ("19:15", "18:30-23:30", True),
        ("23:45", "18:30-23:30", False),
        ("01:00", "18:30-01:30", True),
        ("02:00", "18:30-01:30", False),
        ("18:30", "18:30-01:30", True),
    ],
)
def test_in_awake(t, awake, ok):
    assert paper.in_awake(t, awake) is ok


def test_rules_on_a_new_file_start_on_paper(tmp_path):
    path = tmp_path / "trader" / "config.json"
    backup, changes = paper.set_rules(path, EXAMPLE, tmp_path / "b")
    doc = config_edit.load(path)
    assert backup is None and changes  # a new file: nothing to back up
    assert (doc["no_entries_before"], doc["no_entries_after"], doc["flat_by"], doc["paper"]) == (
        "09:45",
        "11:00",
        "12:00",
        True,
    )
    assert doc["budget"] == 5000  # the rest comes from the skills' example
    assert doc["sec_user_agent"] == ""  # never the example's placeholder (the skills read "" as unset)
    assert paper.set_rules(path, EXAMPLE, tmp_path / "b") == (None, [])  # already set: nothing written


def test_rules_take_the_sec_user_agent_from_env_and_drop_the_placeholder(tmp_path):
    path = tmp_path / "config.json"
    paper.set_rules(path, EXAMPLE, tmp_path / "b", sec_user_agent="Ada ada@example.org")
    assert config_edit.load(path)["sec_user_agent"] == "Ada ada@example.org"
    old = tmp_path / "old.json"
    old.write_text(
        EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )  # copied by hand, placeholder and all
    paper.set_rules(old, EXAMPLE, tmp_path / "b")
    assert config_edit.load(old)["sec_user_agent"] == ""


def test_a_weekend_run_does_not_count_as_a_trading_day(db, tmp_path):
    db.add(JobHeartbeat(mode="live", job="clock", last_run_ny="2026-10-24 11:17"))  # Saturday
    db.commit()
    got = items(db, tmp_path, datetime(2026, 10, 26, 10, 0, tzinfo=NY))
    assert got["Worker running every US trading day"].ok is False


def test_rules_on_an_existing_file_back_up_and_leave_paper_alone(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({**json.loads(EXAMPLE.read_text(encoding="utf-8")), "paper": False, "budget": 2000}),
        encoding="utf-8",
    )
    before = path.read_bytes()
    backup, changes = paper.set_rules(path, EXAMPLE, tmp_path / "b")
    assert backup.read_bytes() == before
    # the window, and the example's placeholder agent cleared
    assert sorted(k for k, _, _ in changes) == ["flat_by", "no_entries_after", "sec_user_agent"]
    doc = config_edit.load(path)
    assert (doc["paper"], doc["budget"]) == (False, 2000)  # never switched, never reset


# --- the checklist ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    engine = init_db(make_engine(f"sqlite:///{(tmp_path / 'p.db').as_posix()}"))
    with session(engine) as s:
        yield s


def plan(s, day, symbol="TSLA", stop_rule="or-mid", target_r=2.0):
    p = Plan(
        mode="live",
        symbol=symbol,
        date=day,
        setup="orb",
        entry=100,
        stop=99,
        target=102,
        risk_per_share=1,
        stop_rule=stop_rule,
        target_r=target_r,
    )
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


def items(s, tmp_path, now, **kw):
    settings = get_settings().model_copy(
        update={"awake_ist": "18:30-23:30", "notify": "none", "paper_start": "", **kw}
    )
    return {i.check: i for i in paper.checklist(s, settings, tmp_path / "trader", now)}


def test_checklist_on_an_empty_start(db, tmp_path):
    got = items(db, tmp_path, datetime(2026, 10, 26, 20, 0, tzinfo=NY))
    assert got["trader/config.json for your IST window"].ok is False
    assert got["Alpaca (or IBKR) paper account connected in Claude"].ok is None
    assert got["Worker running every US trading day"].detail == "the live worker hasn't run on a weekday yet"
    assert got["Notifications on"].ok is False
    assert got["One setup only"].ok is None and got["Every plan has a Taken or Skipped decision"].ok is None
    assert got["40+ decisions logged"].detail == "0 of 40"


def test_checklist_with_a_week_of_use(db, tmp_path):
    paper.set_rules(tmp_path / "trader" / "config.json", EXAMPLE, tmp_path / "b")
    db.add(JobHeartbeat(mode="live", job="quotes", last_run_ny="2026-10-23 15:58"))
    a = plan(db, "2026-10-21")
    plan(db, "2026-10-22", "NVDA")
    plan(db, "2026-10-26", "AMD")  # today: may still be decided before the close
    db.add(Decision(mode="live", plan_id=a.id, action="SKIPPED"))
    db.commit()
    # Monday 26 Oct, 10:30 NY: the last weekday before today is Friday 23 Oct
    got = items(db, tmp_path, datetime(2026, 10, 26, 10, 30, tzinfo=NY), notify="toast")
    assert got["trader/config.json for your IST window"].ok is True
    assert (
        "(19:15–20:30 IST), flat by 12:00 NY (21:30 IST), paper=True"
        in got["trader/config.json for your IST window"].detail
    )
    assert got["Worker running every US trading day"].ok is True
    assert got["Notifications on"].ok is True
    assert got["One setup only"].ok is True and got["One setup only"].detail == "orb · or-mid stop · 2.0R"
    d = got["Every plan has a Taken or Skipped decision"]
    assert (d.ok, d.detail) == (False, "1 of 2 decided; missing: NVDA 2026-10-22")
    assert got["40+ decisions logged"].detail == "1 of 40 since 2026-10-21"
    # after the close, today's plan counts too
    after = items(db, tmp_path, datetime(2026, 10, 26, 16, 5, tzinfo=NY))
    assert after["Every plan has a Taken or Skipped decision"].detail.startswith("1 of 3 decided")


def test_checklist_flags_a_second_setup_and_a_late_flat_by(db, tmp_path):
    path = tmp_path / "trader" / "config.json"
    paper.set_rules(
        path,
        EXAMPLE,
        tmp_path / "b",
        {"no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55"},
    )
    plan(db, "2026-10-21")
    plan(db, "2026-10-22", stop_rule="or-low", target_r=1.0)
    got = items(db, tmp_path, datetime(2026, 10, 26, 10, 0, tzinfo=NY), paper_start="2026-10-20")
    cfg = got["trader/config.json for your IST window"]
    assert cfg.ok is False and cfg.detail.endswith("outside AWAKE_IST 18:30-23:30: no_entries_after, flat_by")
    assert got["One setup only"].ok is False
    assert got["40+ decisions logged"].detail == "0 of 40 since 2026-10-20"


def test_last_weekday():
    assert paper.last_weekday(date(2026, 10, 26)) == date(2026, 10, 23)  # Monday → Friday
    assert paper.last_weekday(date(2026, 10, 25)) == date(2026, 10, 23)  # Sunday → Friday
    assert paper.last_weekday(date(2026, 10, 28)) == date(2026, 10, 27)


# --- the weekly review -----------------------------------------------------------------------


def t(day, r, taken, simulated, followed=True):
    return Trade(day=day, symbol="TSLA", r=r, simulated=simulated, taken=taken, followed_rules=followed)


TRADES = [
    t("2026-10-26", 2.0, True, False),
    t("2026-10-27", -1.0, True, False, followed=False),
    t("2026-10-28", 1.0, False, True),  # skipped, simulated
    t("2026-10-29", -1.0, False, True, followed=None),  # never decided, simulated
    t("2026-11-03", -1.0, True, False),  # week 2
    t("2026-10-25", 5.0, True, False),  # before the period: ignored
]


def test_weekly_review_by_hand():
    rows = paper.weekly_review(TRADES, date(2026, 10, 26), weeks=3)
    w1, w2, w3 = rows
    # week 1: 4 plans; taken 2 (+2, -1 → +0.5R); all 4: +1R / 4 = +0.25R; rules kept 2 of 3 decided
    assert (w1["plans"], w1["taken"], w1["skipped"]) == (4, 2, 1)
    assert (w1["expectancy_taken"], w1["expectancy_all"], w1["adherence"]) == (0.5, 0.25, 0.667)
    assert (w2["plans"], w2["expectancy_taken"], w2["from"]) == (1, -1.0, "2026-11-02")
    assert w3["plans"] == 0
    assert paper.review_line(w1) == "| 1 | 4 | 2 | 1 | +0.50R | +0.25R | 67% | from 2026-10-26 |"
    assert paper.review_line(w3) == "| 3 | | | | | | | |"


def test_update_guide_fills_only_the_phase_p_weeks():
    text = (ROOT / "IMPLEMENTATION_GUIDE.md").read_text(encoding="utf-8")
    rows = [r for r in paper.weekly_review(TRADES, date(2026, 10, 26)) if r["plans"]]
    new = paper.update_guide(text, rows)
    assert "| 1 | 4 | 2 | 1 | +0.50R | +0.25R | 67% | from 2026-10-26 |" in new
    assert "| 2 | 1 | 1 | 0 | -1.00R | -1.00R | 100% | from 2026-11-02 |" in new
    changed = [(a, b) for a, b in zip(text.splitlines(), new.splitlines(), strict=True) if a != b]
    assert len(changed) == 2  # the two weeks, nothing else
