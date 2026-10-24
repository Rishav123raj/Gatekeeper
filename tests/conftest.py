from datetime import datetime

import pytest

from gatekeeper.clock import NY
from gatekeeper.db import get_engine
from gatekeeper.settings import get_settings

T_1015 = datetime(2026, 10, 19, 10, 15, tzinfo=NY)


@pytest.fixture(scope="session")
def skills_dir():
    return get_settings().skills_path


@pytest.fixture(scope="module")
def replay_env(tmp_path_factory):
    """Replay mode, a throwaway database and workspace, already played to 10:15 (one per test module)."""
    from worker.scheduler import sync_replay

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
