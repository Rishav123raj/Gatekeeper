from gatekeeper.settings import ROOT, Settings


def test_defaults_resolve_against_project_root(monkeypatch):
    monkeypatch.delenv("SKILLS_DIR", raising=False)
    s = Settings(_env_file=None)
    assert s.mode == "live"
    assert s.skills_path == (ROOT / "vendor/day-trader-skill").resolve()
    assert s.trader_path == ROOT / "trader"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GATEKEEPER_MODE", "replay")
    monkeypatch.setenv("CORE_TICKERS", "tsla, nvda ,AMD")
    s = Settings(_env_file=None)
    assert s.mode == "replay"
    assert s.core_tickers == ["TSLA", "NVDA", "AMD"]


def test_pinned_skills_are_present():
    assert (ROOT / "vendor/day-trader-skill/trader-scanner/scan.py").is_file()
