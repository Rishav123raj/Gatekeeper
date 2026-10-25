"""The Journal, Research and Settings pages in replay: the TSLA plan skipped, the day played to 16:10."""

import json
from datetime import datetime, time

import pytest
from streamlit.testing.v1 import AppTest

from gatekeeper import store
from gatekeeper.clock import NY
from gatekeeper.db import get_engine, session
from gatekeeper.replay import ReplayContext
from gatekeeper.runner import SkillRunner
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.skills import entry, exit
from worker.scheduler import sync_replay

JOURNAL = str(ROOT / "app" / "pages" / "6_Journal.py")
RESEARCH = str(ROOT / "app" / "pages" / "7_Research.py")
SETTINGS = str(ROOT / "app" / "pages" / "8_Settings.py")


@pytest.fixture(scope="module")
def evening(replay_env, tmp_path_factory):
    """The 10:15 plan for TSLA, skipped, then the replay played to 16:10; .env and backups in tmp."""
    tmp = tmp_path_factory.mktemp("settings")
    mp = pytest.MonkeyPatch()
    env = tmp / ".env"
    env.write_text("# mine\nSEC_USER_AGENT=Ada ada@example.org\nCORE_TICKERS=TSLA\n", encoding="utf-8")
    mp.setenv("GATEKEEPER_ENV_FILE", str(env))
    mp.setenv("BACKUPS_DIR", str(tmp / "backups"))
    get_settings.cache_clear()
    s = get_settings()
    ctx = ReplayContext(
        datetime(2026, 10, 19, 10, 15), s.resolve(s.replay_workspace), s.skills_path / "tests" / "fixtures"
    )
    r = SkillRunner.from_settings(s, replay=ctx)
    entry.check("TSLA", write=True, runner=r)
    plan, _ = exit.plan(stop="or-mid", target="1R", runner=r)
    with session(get_engine()) as db:
        pid = store.save_plan(db, plan, "replay").id
        store.save_decision(db, "replay", "SKIPPED", plan_id=pid, symbol="TSLA", note="coin flip")
    sync_replay(s, get_engine(), datetime(2026, 10, 19, 16, 10, tzinfo=NY))
    yield env, tmp / "backups"
    mp.undo()
    get_settings.cache_clear()


def run(page):
    """The page with the slider at 16:10 (the default 10:15 would rebuild the day from the morning)."""
    at = AppTest.from_file(page, default_timeout=180)
    at.session_state["replay_time"] = time(16, 10)
    return at.run()


def test_journal_has_the_simulated_row(evening):
    at = run(JOURNAL)
    assert not at.exception, [e.value for e in at.exception]
    log = at.dataframe[0].value if at.dataframe else None
    assert log is not None and "TSLA" in log.to_string()
    assert any(i.value.startswith("Not enough trades yet: 1 of the 40 needed") for i in at.info)
    assert at.get("download_button")  # the CSV export


def test_journal_row_is_the_simulated_skip(evening):
    at = run(JOURNAL)
    assert not at.exception
    with session(get_engine()) as db:
        (t,) = store.journal_trades(db, "replay")
    assert (t.simulated, t.taken, t.r) == (True, False, 0.427)


def test_research_earnings_and_congress(evening):
    at = run(RESEARCH)
    assert not at.exception, [e.value for e in at.exception]
    assert "$109.42B" in [m.value for m in at.metric]
    assert any("45 days" in i.value for i in at.info)
    assert len(at.dataframe) >= 1


def test_settings_paper_is_read_only(evening):
    at = run(SETTINGS)
    assert not at.exception, [e.value for e in at.exception]
    assert at.toggle(key="cfg_paper").disabled and at.toggle(key="cfg_paper").value is True


def test_settings_budget_change_is_backed_up_then_saved(evening):
    _, backups = evening
    s = get_settings()
    cfg = s.resolve(s.replay_workspace) / "trader" / "config.json"
    before = cfg.read_bytes()
    at = run(SETTINGS)
    next(n for n in at.number_input if n.label == "Budget ($)").set_value(6000.0)
    at.button[0].click().run()  # Preview changes (the form's submit button)
    assert not at.error, [e.value for e in at.error]
    at.button(key="cfg_save").click().run()
    assert any(x.value.startswith("Saved 1 change(s).") for x in at.success)
    (backup,) = backups.glob("config-*.json")
    assert backup.read_bytes() == before
    assert json.loads(cfg.read_text(encoding="utf-8"))["budget"] == 6000.0


def test_settings_env_save_keeps_other_lines(evening):
    env, backups = evening
    at = run(SETTINGS)
    next(t for t in at.text_input if t.label == "Core tickers").set_value("TSLA,NVDA")
    next(b for b in at.button if b.label == "Save to .env").click().run()
    assert not at.error, [e.value for e in at.error]
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["# mine", "SEC_USER_AGENT=Ada ada@example.org", "CORE_TICKERS=TSLA,NVDA"]
    assert list(backups.glob("env-*.bak"))
