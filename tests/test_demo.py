"""The public demo: replay only, one private copy per visitor, old copies removed."""

import os
import time

import pytest
from sqlmodel import select
from streamlit.testing.v1 import AppTest

from app.components import demo
from gatekeeper.db import get_engine, init_db, make_engine, session
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.tables import ScanRun

HOME = str(ROOT / "app" / "Home.py")
SCANNER = str(ROOT / "app" / "pages" / "1_Scanner.py")
SETTINGS = str(ROOT / "app" / "pages" / "8_Settings.py")


@pytest.fixture(scope="module")
def public(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("demo")
    mp = pytest.MonkeyPatch()
    mp.setenv("PUBLIC_DEMO", "true")
    mp.setenv("GATEKEEPER_MODE", "live")  # the demo must still be replay
    mp.setenv("DEMO_ROOT", str(tmp / "visitors"))
    mp.setenv("DB_URL", f"sqlite:///{(tmp / 'main.db').as_posix()}")
    mp.setenv("REPLAY_WORKSPACE", str(tmp / "main-ws"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield tmp
    get_engine().dispose()
    mp.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_visitor_settings_point_at_their_folder(tmp_path):
    s = demo.visitor_settings(get_settings(), tmp_path)
    assert (s.mode, s.notify) == ("replay", "none")
    assert s.db_url.endswith("/demo.db") and s.replay_workspace == tmp_path / "ws"
    assert (s.env_path, s.backups_dir) == (tmp_path / "demo.env", tmp_path / "backups")


def test_cleanup_removes_only_old_folders(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    hours_ago = time.time() - 7 * 3600
    os.utime(old, (hours_ago, hours_ago))
    assert demo.cleanup(tmp_path, 6) == [old]
    assert not old.exists() and new.exists()
    assert demo.cleanup(tmp_path / "missing", 6) == []


def test_two_visitors_get_their_own_replay(public):
    a = AppTest.from_file(HOME, default_timeout=240).run()
    b = AppTest.from_file(SCANNER, default_timeout=240).run()
    for at in (a, b):
        assert not at.exception, [e.value for e in at.exception]
        assert any(i.value.startswith("**Public demo.**") for i in at.sidebar.info)
        assert not at.sidebar.get("segmented_control")  # no LIVE switch
        assert any("Mode: **REPLAY**" in m.value for m in at.markdown)
    folders = sorted(p.name for p in (public / "visitors").iterdir())
    assert len(folders) == 2 and folders[0] != folders[1]
    # each visitor's copy has the recorded 10:15 scan; the app's own database has nothing
    for name in folders:
        eng = init_db(make_engine(f"sqlite:///{(public / 'visitors' / name / 'demo.db').as_posix()}"))
        with session(eng) as s:
            assert s.exec(select(ScanRun).where(ScanRun.mode == "replay")).first() is not None
        eng.dispose()
    with session(get_engine()) as s:
        assert s.exec(select(ScanRun)).first() is None
    assert not (public / "main-ws").exists()


def test_settings_edits_stay_in_the_visitors_copy(public):
    at = AppTest.from_file(SETTINGS, default_timeout=240).run()
    assert not at.exception, [e.value for e in at.exception]
    mine = at.session_state["demo_settings"]
    next(n for n in at.number_input if n.label == "Budget ($)").set_value(7000.0)
    at.button[0].click().run()
    at.button(key="cfg_save").click().run()
    assert any(x.value.startswith("Saved 1 change(s).") for x in at.success)
    cfg = mine.resolve(mine.replay_workspace) / "trader" / "config.json"
    assert '"budget": 7000.0' in cfg.read_text(encoding="utf-8")
    assert str(public / "visitors") in str(cfg)
    assert not any(b.label == "Run the contract self-test" for b in at.button)
