"""The pages load in replay at 10:15 on the recorded day and show the recorded numbers."""

from datetime import datetime

import pytest
from streamlit.testing.v1 import AppTest

from gatekeeper import store
from gatekeeper.clock import NY
from gatekeeper.db import get_engine, session
from gatekeeper.settings import ROOT, get_settings
from worker.scheduler import sync_replay

PAGES = ["app/Home.py", "app/pages/1_Scanner.py", "app/pages/2_Watchlist_News.py", "app/pages/3_Trade_Lab.py"]
T_1015 = datetime(2026, 10, 19, 10, 15, tzinfo=NY)
HEADLINES = {
    "Meta and Musk earnings and September pending home sales": ":red-badge[earnings]",
    "Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings": ":violet-badge[deal]",
    "Tech Stock Rebound Nudges US Equity Futures Mostly Higher Pre-Bell": ":gray-badge[macro]",
}


@pytest.fixture(scope="module")
def replay_env(tmp_path_factory):
    """Replay mode, a throwaway database and workspace, already played to 10:15."""
    tmp = tmp_path_factory.mktemp("ui")
    mp = pytest.MonkeyPatch()
    mp.setenv("GATEKEEPER_MODE", "replay")
    mp.setenv("DB_URL", f"sqlite:///{(tmp / 'ui.db').as_posix()}")
    mp.setenv("REPLAY_WORKSPACE", str(tmp / "ws"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    msg = sync_replay(get_settings(), get_engine(), T_1015)
    yield msg
    get_engine().dispose()
    mp.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()


def run(page):
    return AppTest.from_file(str(ROOT / page), default_timeout=120).run()


def test_replay_was_built(replay_env):
    assert replay_env == "replay rebuilt from 07:00 to 10:15"


@pytest.mark.parametrize("page", PAGES)
def test_page_loads(replay_env, page):
    at = run(page)
    assert not at.exception, [e.value for e in at.exception]
    assert any("IST" in m.value and "REPLAY" in m.value for m in at.markdown)  # the clock bar
    assert any("Not financial advice" in c.value for c in at.caption)  # the footer


def test_scanner_shows_41_orb_hits_with_tsla(replay_env):
    at = run("app/pages/1_Scanner.py")
    daily, orb = at.dataframe[0].value, at.dataframe[1].value
    assert len(orb) == 41 and len(daily) == 7
    tsla = orb[orb["Symbol"] == "TSLA"].iloc[0]
    assert (tsla["Range"], tsla["Price"], tsla["% over"]) == ("354.47 – 362.18", 364.18, 0.55)
    assert tsla["Broke out at"] == "10:15 NY · 19:45 IST"
    assert any("**41** of 222 usable charts matched" in m.value for m in at.markdown)


def test_news_shows_the_three_morning_headlines(replay_env):
    at = run("app/pages/2_Watchlist_News.py")
    text = "\n".join(m.value for m in at.markdown)
    for title, chip in HEADLINES.items():
        line = next(m.value for m in at.markdown if title in m.value)
        assert chip in line, title
    assert "Merger Mania" in text and ":red-badge[earnings] :violet-badge[deal]" in text
    pins = at.dataframe[0].value
    assert list(pins["Symbol"]) == ["TSLA"] and pins.iloc[0]["Entry"].startswith("triggered at 364.18")


def test_home_context_in_replay(replay_env):
    at = run("app/Home.py")
    assert [m.value for m in at.metric] == ["n/a"] * 4  # no index charts in the recording
    assert any(":gray-badge[UNKNOWN]" in m.value and "18 %" in m.value for m in at.markdown)


def test_pin_from_the_watchlist(replay_env):
    at = run("app/pages/2_Watchlist_News.py")
    at.text_input[0].input("nvda, amd")
    at.button[0].click().run()  # the form's "Pin" button
    with session(get_engine()) as s:
        assert store.pinned(s, "replay") == ["TSLA", "NVDA", "AMD"]
        store.unpin(s, "NVDA", "replay")
        store.unpin(s, "AMD", "replay")


def test_replay_sync_moves_forward_then_rebuilds(replay_env):
    s, e = get_settings(), get_engine()
    assert sync_replay(s, e, T_1015) == "replay already at 10:15"
    assert sync_replay(s, e, T_1015.replace(minute=20)) == "replay moved on from 10:15 to 10:20"
    assert sync_replay(s, e, T_1015.replace(minute=15)) == "replay rebuilt from 07:00 to 10:15"
    with session(e) as x:
        assert store.pinned(x, "replay") == ["TSLA"]  # pins survive a rebuild
