"""SkillRunner: classification, timeouts, locking, isolation and replay injection, on fake scripts."""

import threading
from datetime import datetime
from pathlib import Path

import pytest
from filelock import FileLock

from gatekeeper.replay import ReplayContext
from gatekeeper.runner import LOCK_NAME, SCRIPTS, SkillRunner, error_message, parse_json


@pytest.fixture
def make_runner(tmp_path):
    """A runner over fake skill scripts, in folders whose paths contain spaces."""
    skills = tmp_path / "skills dir"
    work = tmp_path / "work dir"

    def make(tool: str, body: str, **kw) -> SkillRunner:
        folder, name = SCRIPTS[tool]
        script = skills / folder / name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("import json, sys, time, os\n" + body, encoding="utf-8")
        return SkillRunner(skills, work, **kw)

    return make


def test_json_and_exit_0_is_ok(make_runner):
    r = make_runner("scanner", "print(json.dumps({'hits': [1], 'args': sys.argv[1:]}))")
    res = r.run("scanner", ["orb"])
    assert res.status == "ok" and res.ok
    assert res.exit_code == 0
    assert res.data["args"] == ["orb", "--json"]  # --json appended once
    assert res.args == ["orb", "--json"]


def test_json_flag_not_duplicated(make_runner):
    r = make_runner("scanner", "print(json.dumps(sys.argv[1:]))")
    assert r.run("scanner", ["orb", "--json"]).data == ["orb", "--json"]


@pytest.mark.parametrize(
    ("tool", "args", "status"),
    [
        ("scanner", ["orb"], "empty"),  # no hits
        ("entry", ["check", "TSLA"], "empty"),  # not triggered
        ("alerts", ["clock"], "empty"),  # market closed
        ("risk", [], "blocked"),
        ("budget", [], "blocked"),  # sizing refused
        ("analyst", ["AAPL"], "partial"),
    ],
)
def test_json_with_exit_1_is_the_tools_negative_answer(make_runner, tool, args, status):
    r = make_runner(tool, "print(json.dumps({'x': 1})); sys.exit(1)")
    res = r.run(tool, args)
    assert res.status == status
    assert res.ok
    assert res.data == {"x": 1}


def test_error_without_json_keeps_the_message(make_runner):
    r = make_runner(
        "exit", "print('exit.py: the stop 370.00 is not below the entry', file=sys.stderr); sys.exit(1)"
    )
    res = r.run("exit", ["plan"])
    assert res.status == "error" and not res.ok
    assert res.message == "the stop 370.00 is not below the entry"


def test_exit_2_is_an_error(make_runner):
    r = make_runner("news", "print('news: no tickers.', file=sys.stderr); sys.exit(2)")
    res = r.run("news", [])
    assert res.status == "error"
    assert res.message == "no tickers."


def test_non_json_stdout_is_an_error(make_runner):
    r = make_runner("scanner", "print('Opening-range breakout scan ...')")
    res = r.run("scanner", ["orb"])
    assert res.status == "error"
    assert "Opening-range" in res.stdout


def test_text_before_the_json_is_tolerated():
    assert parse_json('progress...\n{\n  "a": 1\n}\n') == {"a": 1}
    assert parse_json("") is None
    assert parse_json("not json") is None


def test_error_message_prefixes():
    assert error_message("alerts.py: no rule x\n") == "no rule x"
    assert error_message("facts: no SEC CIK for ZZZZ\n") == "no SEC CIK for ZZZZ"
    assert error_message("", "Not recorded: only a reply...") == "Not recorded: only a reply..."


def test_text_commands(make_runner):
    ok = make_runner("broker", "print('Recorded your yes'); sys.exit(0)")
    assert ok.run("broker", ["approve"], json_out=False).status == "ok"
    refused = make_runner("broker", "print('Not recorded: ...'); sys.exit(1)")
    assert refused.run("broker", ["approve"], json_out=False).status == "blocked"
    broken = make_runner("broker", "print('ticket.py: no orders', file=sys.stderr); sys.exit(1)")
    assert broken.run("broker", ["show"], json_out=False).status == "error"


def test_timeout(make_runner):
    r = make_runner("scanner", "time.sleep(10)")
    res = r.run("scanner", ["orb"], timeout=0.5)
    assert res.status == "error"
    assert "timed out" in res.message
    assert res.duration_s < 5


def test_lock_held_elsewhere(make_runner):
    r = make_runner("budget", "print('{}')", lock_timeout=0.3)
    r.trader_dir.mkdir(parents=True)
    with FileLock(r.trader_dir / LOCK_NAME):
        res = r.run("budget", [], writes_state=True)
    assert res.status == "error"
    assert "lock" in res.message
    assert r.run("budget", [], writes_state=True).status == "ok"  # free again


def test_state_writers_never_overlap(make_runner, tmp_path):
    log = tmp_path / "spans.txt"
    body = (
        f"t0 = time.time(); time.sleep(0.3)\n"
        f"open({str(log)!r}, 'a').write(f'{{t0}} {{time.time()}}\\n')\n"
        "print('{}')\n"
    )
    r = make_runner("risk", body)
    kw = {"writes_state": True}
    threads = [threading.Thread(target=r.run, args=("risk", []), kwargs=kw) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    spans = sorted(tuple(map(float, line.split())) for line in log.read_text().splitlines())
    assert len(spans) == 3
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert start >= end


def test_isolated_mode_ignores_modules_in_the_working_folder(make_runner):
    r = make_runner("scanner", "print(json.dumps({'ok': True}))")
    r.cwd.mkdir(parents=True)
    (r.cwd / "json.py").write_text("raise SystemExit('shadowed!')", encoding="utf-8")
    assert r.run("scanner", ["orb"]).data == {"ok": True}


def test_utf8_output(make_runner):
    r = make_runner("news", "print(json.dumps({'t': 'Apple’s run · ₹'}, ensure_ascii=False))")
    assert r.run("news", []).data == {"t": "Apple’s run · ₹"}


def test_on_result_callback(make_runner):
    seen = []
    r = make_runner("scanner", "print('{}')", on_result=seen.append)
    r.run("scanner", ["daily"])
    assert [x.tool for x in seen] == ["scanner"]


def test_unknown_tool(make_runner):
    r = make_runner("scanner", "")
    with pytest.raises(ValueError):
        r.run("nope", [])


def test_sec_user_agent_is_passed(make_runner):
    r = make_runner(
        "analyst",
        "print(json.dumps(os.environ.get('SEC_USER_AGENT')))",
        env={"SEC_USER_AGENT": "Ada ada@example.org"},
    )
    assert r.run("analyst", ["AAPL"]).data == "Ada ada@example.org"


# --- replay injection ------------------------------------------------------------------------

CTX = ReplayContext(datetime(2026, 10, 19, 10, 15), Path("/ws"), Path("/fx"))


def test_replay_adds_clock_and_offline():
    out = CTX.inject("scanner", "orb", ["orb"])
    assert out[:3] == ["orb", "--now", "2026-10-19 10:15"]
    assert out[3] == "--offline" and Path(out[4]) == Path("/fx/trader-scanner/wall5m-2026-10-19.json.gz")


def test_replay_entry_reads_the_workspace_charts():
    out = CTX.inject("entry", "check", ["check", "TSLA"])
    assert Path(out[out.index("--offline") + 1]) == Path("/ws/charts")


def test_replay_news_uses_iso_time():
    out = CTX.inject("news", None, [])
    assert out[out.index("--now") + 1] == "2026-10-19T10:15:00-04:00"


def test_replay_pelosi_fixes_the_year_and_today():
    out = CTX.inject("pelosi", "new", ["new"])
    assert out[out.index("--today") + 1] == "2026-10-19"
    assert out[out.index("--year") + 1] == "2026"


def test_replay_explicit_arguments_win():
    out = CTX.inject("alerts", "clock", ["clock", "--now", "2026-11-26 12:00"])
    assert out == ["clock", "--now", "2026-11-26 12:00"]


def test_replay_leaves_tools_without_a_clock_alone():
    assert CTX.inject("alerts", "add", ["add", "--from-plan"]) == ["add", "--from-plan"]
    assert "--now" not in CTX.inject("analyst", None, ["AAPL"])
