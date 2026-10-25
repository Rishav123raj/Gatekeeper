"""Editing trader/config.json: validation, the diff, backups, and `paper` that can't change."""

import json

import pytest
from pydantic import ValidationError

from gatekeeper import config_edit, envfile
from gatekeeper.settings import get_settings

EXAMPLE = get_settings().skills_path / "trader-budget" / "config.example.json"


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "trader" / "config.json"
    path.parent.mkdir()
    path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return path, tmp_path / "backups"


def test_the_skills_example_is_valid():
    assert config_edit.validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))["budget"] == 5000


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"budget": -1}, "budget"),
        ({"flat_by": "3:55pm"}, "flat_by"),
        ({"cash_buffer_pct": 120}, "cash_buffer_pct"),
        ({"max_trades_per_day": 0}, "max_trades_per_day"),
    ],
)
def test_validation(cfg, change, field):
    path, _ = cfg
    with pytest.raises(ValidationError) as e:
        config_edit.validate({**config_edit.load(path), **change})
    assert e.value.errors()[0]["loc"] == (field,)


def test_save_backs_up_then_writes(cfg):
    path, backups = cfg
    before = path.read_bytes()
    backup, changes = config_edit.save(
        path, {**config_edit.load(path), "max_loss_per_trade_usd": 40, "blocked": ["gme ", "AMC"]}, backups
    )
    assert backup.read_bytes() == before  # the old file, as it was
    assert dict((k, (a, b)) for k, a, b in changes) == {
        "blocked": ([], ["AMC", "GME"]),
        "max_loss_per_trade_usd": (50, 40.0),
    }
    saved = config_edit.load(path)
    assert (saved["max_loss_per_trade_usd"], saved["blocked"], saved["paper"]) == (40.0, ["AMC", "GME"], True)
    assert saved["sec_user_agent"] == "Your Name you@example.com"  # untouched keys are kept


def test_no_change_writes_nothing(cfg):
    path, backups = cfg
    assert config_edit.save(path, config_edit.load(path), backups) == (None, [])
    assert not backups.exists()


def test_paper_cannot_be_changed(cfg):
    path, backups = cfg
    before = path.read_bytes()
    with pytest.raises(config_edit.PaperChangeRefused):
        config_edit.save(path, {**config_edit.load(path), "paper": False}, backups)
    assert path.read_bytes() == before and not backups.exists()


def test_a_live_account_stays_live_too(cfg):
    path, backups = cfg
    doc = config_edit.load(path)
    doc["paper"] = False  # the user went live by editing the file themselves
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(config_edit.PaperChangeRefused):
        config_edit.save(path, {**doc, "paper": True}, backups)
    assert config_edit.save(path, {**doc, "budget": 6000}, backups)[1] == [("budget", 5000, 6000.0)]


def test_a_new_config_starts_on_paper(tmp_path):
    path = tmp_path / "config.json"
    doc = {**json.loads(EXAMPLE.read_text(encoding="utf-8")), "paper": False}
    backup, _ = config_edit.save(path, doc, tmp_path / "b")
    assert backup is None and config_edit.load(path)["paper"] is True


# --- .env -----------------------------------------------------------------------------------


def test_env_update_keeps_everything_else(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# my settings\nCORE_TICKERS=TSLA\nSEC_USER_AGENT=Ada ada@example.org\nNOTIFY=none\n",
        encoding="utf-8",
    )
    backup = envfile.update(
        env, {"CORE_TICKERS": "TSLA,NVDA", "GATE_BREADTH_WARN_PCT": "15"}, tmp_path / "bk"
    )
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# my settings",
        "CORE_TICKERS=TSLA,NVDA",
        "SEC_USER_AGENT=Ada ada@example.org",
        "NOTIFY=none",
        "GATE_BREADTH_WARN_PCT=15",
    ]
    assert backup.read_text(encoding="utf-8").startswith("# my settings\nCORE_TICKERS=TSLA\n")


def test_env_refuses_secrets(tmp_path):
    with pytest.raises(ValueError):
        envfile.update(tmp_path / ".env", {"TELEGRAM_BOT_TOKEN": "x"})
    with pytest.raises(ValueError):
        envfile.update(tmp_path / ".env", {"ALPACA_API_KEY": "x"})
    assert not (tmp_path / ".env").exists()
