"""'What if' runs on a copy: trader/ stays byte-for-byte the same (task 6.10)."""

import hashlib
from datetime import datetime

import pytest

from gatekeeper.clock import NY
from gatekeeper.replay import prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.sandbox import what_if
from gatekeeper.settings import get_settings
from gatekeeper.skills import budget, entry, exit, risk

S = get_settings()
NOW = datetime(2026, 10, 19, 10, 15, tzinfo=NY)


def tree(d):
    return {
        str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def trader(tmp_path_factory, skills_dir):
    ctx = prepare_workspace(NOW.replace(tzinfo=None), tmp_path_factory.mktemp("wi"), skills_dir)
    r = SkillRunner.from_settings(replay=ctx)
    entry.check("TSLA", write=True, runner=r)
    exit.plan(stop="or-mid", target="1R", runner=r)
    budget.size(runner=r)
    risk.check(runner=r)
    return ctx.workspace / "trader", skills_dir / "tests" / "fixtures"


def run(trader, **kw):
    path, fixtures = trader
    before = tree(path)
    w = what_if(path, S, NOW, "TSLA", replay_fixtures=fixtures, **kw)
    assert tree(path) == before  # the live folder is untouched, whatever the what-if
    return w


def test_unchanged_is_the_documented_pass(trader):
    w = run(trader)
    assert w.size.sizing.qty == 8 and w.risk.results[0].verdict == "PASS"


def test_nine_shares_is_blocked(trader):
    v = run(trader, qty=9).risk.results[0]
    assert (v.verdict, v.max_loss) == ("BLOCK", 52.74)


def test_a_run_up_price_is_blocked_and_refused(trader):
    w = run(trader, price=366.48)
    v = w.risk.results[0]
    assert (v.verdict, v.max_loss, v.reward_risk, v.entry_ref) == ("BLOCK", 65.28, 0.44, 366.48)
    assert w.size.refused and (w.size.sizing.qty, w.size.sizing.reward_risk) == (6, 0.44)


def test_a_lower_price_never_shrinks_the_risk(trader):
    v = run(trader, price=362.00).risk.results[0]
    assert (v.verdict, v.entry_ref, v.max_loss) == ("PASS", 364.18, 46.88)  # measured from the plan's entry


def test_no_lock_file_is_copied(trader, tmp_path):
    path, _ = trader
    (path / ".gatekeeper.lock").write_text("")
    try:
        assert run(trader).risk is not None
    finally:
        (path / ".gatekeeper.lock").unlink()
