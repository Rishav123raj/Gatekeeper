"""The Trade Lab's logic: the preview, the skill arguments, and the plan comparison."""

from datetime import datetime

import pytest

from gatekeeper import lab
from gatekeeper.replay import prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.skills import entry, exit

OR = (362.18, 354.47)


@pytest.mark.parametrize(
    ("stop_rule", "stop_value", "target_rule", "expected"),
    [
        ("or-mid", None, "1R", (358.32, 370.04, 5.86, 1.0)),  # the documented plan
        ("or-mid", None, "2R", (358.32, 375.90, 5.86, 2.0)),
        ("or-low", None, "1R", (354.47, 373.89, 9.71, 1.0)),
        ("pct", 1, "2R", (360.53, 371.48, 3.65, 2.0)),  # 364.18 x 0.99 = 360.5382, rounded down
    ],
)
def test_preview_matches_exit_py(stop_rule, stop_value, target_rule, expected):
    pv = lab.preview(364.18, *OR, stop_rule, stop_value, target_rule)
    assert (pv.stop, pv.target, round(pv.risk, 2), pv.reward_risk) == expected


def test_preview_refusals():
    assert lab.preview(364.18, *OR, "price", 370).note == "the stop is at or above the entry"
    assert "exit.py" in lab.preview(364.18, *OR, "atr", 1.5).note
    assert lab.preview(364.18, None, None, "or-mid").note == "not enough data for a preview"
    pv = lab.preview(364.18, *OR, "or-mid", target_rule="price", target_value=380)
    assert (pv.target, pv.reward_risk) == (380.0, 2.7)


def test_skill_arguments():
    assert lab.stop_arg("or-mid") == "or-mid"
    assert lab.stop_arg("atr", 1.5) == "atr:1.5"
    assert lab.stop_arg("price", 358.0) == "price:358"
    assert lab.target_arg("2R") == "2R" and lab.target_arg("price", 380.5) == "price:380.5"
    for bad in (lambda: lab.stop_arg("pct"), lambda: lab.stop_arg("nope"), lambda: lab.target_arg("price")):
        with pytest.raises(ValueError):
            bad()


def test_file_hash(tmp_path):
    f = tmp_path / "plan.json"
    assert lab.file_hash(f) is None
    f.write_text("{}")
    a = lab.file_hash(f)
    f.write_text('{"x": 1}')
    assert a and lab.file_hash(f) != a


@pytest.fixture(scope="module")
def triggered(tmp_path_factory, skills_dir):
    ctx = prepare_workspace(datetime(2026, 10, 19, 10, 15), tmp_path_factory.mktemp("lab"), skills_dir)
    r = SkillRunner.from_settings(replay=ctx)
    entry.check("TSLA", write=True, runner=r)
    return ctx, r


def test_compare_never_touches_plan_json(triggered):
    ctx, r = triggered
    plan_file = ctx.workspace / "trader" / "plan.json"
    exit.plan(stop="or-mid", target="1R", runner=r)  # the user's plan
    before = plan_file.read_bytes()
    variants = [
        lab.Variant("or-mid", "1R"),
        lab.Variant("or-mid", "2R"),
        lab.Variant("or-low", "1R"),
        lab.Variant("price", "1R", stop_value=370.0),
    ]
    rows = [v.row() for v in lab.compare(variants, r)]
    assert plan_file.read_bytes() == before
    assert (rows[0]["Stop"], rows[0]["Target"], rows[0]["Target first %"], rows[0]["Stop first %"]) == (
        358.32,
        370.04,
        29.4,
        25.5,
    )
    assert rows[0]["History"] == "33 fired: 13 target / 15 stop"
    assert (rows[1]["Target"], rows[1]["R:R"]) == (375.9, 2.0)
    assert (rows[2]["Stop"], rows[2]["Target"]) == (354.47, 373.89)
    assert "at or above the entry" in rows[3]["Result"]  # exit.py's refusal, as it said it


def test_compare_ends_at_flat_by(triggered):
    _, r = triggered
    (res,) = lab.compare([lab.Variant("or-mid", "1R")], r, until="15:55")
    assert res.tm.mc.until == "15:55" and res.tm.mc.p_target == 0.2917
