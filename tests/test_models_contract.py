"""The committed contracts parse into the models, and a fresh run still has the same structure."""

import json

import pytest

from gatekeeper.contracts import MODELS, generate, shape
from gatekeeper.settings import ROOT

CONTRACTS = ROOT / "tests" / "contracts"


def load(name):
    return json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))


def parsed(name):
    model, many = MODELS[name]
    data = load(name)
    return [model.model_validate(x) for x in data] if many else model.model_validate(data)


def test_every_contract_has_a_model_and_a_file():
    assert {p.stem for p in CONTRACTS.glob("*.json")} == set(MODELS)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_contract_parses(name):
    assert parsed(name)


def test_key_fields():
    assert parsed("alerts_clock").trading_day
    assert parsed("scanner_universe").count > 0
    daily = parsed("scanner_daily")
    assert daily.mode == "daily" and daily.hits[0].rsi is not None
    orb = parsed("scanner_orb_1015")
    assert orb.mode == "orb" and orb.counts.scanned == 222 and not orb.partial
    news = parsed("news_tsla")
    assert news.items and news.moves[0].ticker == "TSLA"
    assert parsed("entry_tsla_1015").trigger.bar_index == 8
    assert parsed("entry_tsla_1012").trigger is None
    assert parsed("exit_plan_or_mid_1r").stop_rule == "or_mid"
    tm = parsed("timemachine_run")
    assert len(tm.mc.bands) == len(tm.mc.band_times) and len(tm.mc.bands[0]) == 5
    assert len(tm.mc.hist.bins) == 24 and tm.history.trades
    assert tm.mc.sample_paths == []  # printed JSON leaves them out; the wrapper reads the file
    size = parsed("budget_size")
    assert size.orders[0].order_class == "bracket" and size.sizing.limits
    assert parsed("risk_check_pass").results[0].fingerprint
    assert parsed("risk_check_block_9").block == 1
    assert parsed("broker_show")[0].tool_input["symbol"] == "TSLA"
    assert parsed("alerts_quote").quotes["TSLA"].price > 0
    assert parsed("alerts_check_1556").rings[0].id == "tsla-flat-by"
    assert parsed("analyst_aapl")[0].result.rows[0].revenue > 0
    assert parsed("pelosi_index")[0].name == "Hon. Nancy Pelosi"
    assert parsed("pelosi_new").new


@pytest.fixture(scope="module")
def fresh(tmp_path_factory, skills_dir):
    return generate(tmp_path_factory.mktemp("contracts"), skills_dir)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_structure_has_not_drifted(fresh, name):
    """Fails when the pinned skills change their JSON: re-run scripts/snapshot_contracts.py and review."""
    assert shape(fresh[name]) == shape(load(name))


def test_contracts_are_reproducible(fresh):
    for name in MODELS:
        assert fresh[name] == load(name), name
