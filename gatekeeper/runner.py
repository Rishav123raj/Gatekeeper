"""The one way Gatekeeper runs a skill script.

Every call goes through `SkillRunner.run`: a subprocess of the pinned script, in the
working folder whose `trader/` it should read and write, with its JSON parsed.

How a result is classified (verified against the scripts' source, Phase 1):

- The scripts print JSON for every normal result, including the "negative" ones
  (no hits, not triggered, market closed, blocked), and signal those with exit 1.
- On an error they print `<script>.py: <message>` to stderr, print no JSON, and
  exit 1 (or 2 for news, analyst and pelosi; 2 is also argparse's usage error).

So: JSON came out -> `ok` on exit 0, else the tool's negative status (`empty` by
default, `blocked` for risk / budget / broker approve, `partial` for analyst).
No JSON -> `error`, with the stderr line as the message.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from filelock import FileLock, Timeout

if TYPE_CHECKING:
    from gatekeeper.replay import ReplayContext
    from gatekeeper.settings import Settings

Status = Literal["ok", "empty", "blocked", "partial", "error"]

SCRIPTS: dict[str, tuple[str, str]] = {
    "scanner": ("trader-scanner", "scan.py"),
    "news": ("trader-news", "news.py"),
    "entry": ("trader-entry", "entry.py"),
    "exit": ("trader-exit", "exit.py"),
    "timemachine": ("trader-timemachine", "timemachine.py"),
    "budget": ("trader-budget", "size.py"),
    "risk": ("trader-risk", "check.py"),
    "broker": ("trader-broker", "ticket.py"),
    "alerts": ("trader-alerts", "alerts.py"),
    "analyst": ("trader-analyst", "facts.py"),
    "pelosi": ("trader-pelosi", "ptr.py"),
}

# Tools whose first argument is a subcommand.
HAS_SUBCOMMAND = {"scanner", "entry", "exit", "timemachine", "broker", "alerts", "pelosi"}

# Status for a valid result with a non-zero exit code; anything else is "empty".
NEGATIVE: dict[tuple[str, str | None], Status] = {
    ("risk", None): "blocked",
    ("budget", None): "blocked",
    ("broker", "approve"): "blocked",
    ("analyst", None): "partial",
}

LOCK_NAME = ".gatekeeper.lock"


class LockBusy(RuntimeError):
    """Another run is writing trader/ and did not finish within the lock timeout."""


@dataclass
class RunResult:
    tool: str
    args: list[str]
    status: Status
    exit_code: int | None
    data: Any = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        """The tool ran and gave an answer (which may be a negative one)."""
        return self.status != "error"


def subcommand(tool: str, args: list[str]) -> str | None:
    return args[0] if tool in HAS_SUBCOMMAND and args else None


def parse_json(text: str) -> Any:
    """The script's JSON document, or None. Tolerates text printed before it."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for i, line in enumerate(text.splitlines()):
        if line[:1] in "{[":
            try:
                return json.loads("\n".join(text.splitlines()[i:]))
            except ValueError:
                return None
    return None


def error_message(stderr: str, stdout: str = "") -> str:
    """The last meaningful line the script printed, without its `script.py: ` prefix."""
    for text in (stderr, stdout):
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        if lines:
            line = lines[-1]
            head, sep, rest = line.partition(": ")
            if sep and (head.endswith(".py") or head in {"facts", "ptr", "news"}):
                return rest
            return line
    return ""


def classify(tool: str, sub: str | None, exit_code: int, data: Any, json_out: bool, stderr: str) -> Status:
    if json_out:
        if data is None:
            return "error"
        return "ok" if exit_code == 0 else NEGATIVE.get((tool, sub), "empty")
    if exit_code == 0:
        return "ok"
    if exit_code == 1 and not error_message(stderr):
        return NEGATIVE.get((tool, sub), "empty")
    return "error"


class SkillRunner:
    def __init__(
        self,
        skills_dir: Path,
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
        replay: ReplayContext | None = None,
        lock_timeout: float = 60,
        on_result: Callable[[RunResult], None] | None = None,
    ):
        self.skills_dir = Path(skills_dir)
        self.cwd = Path(cwd)
        self.env = env or {}
        self.replay = replay
        self.lock_timeout = lock_timeout
        self.on_result = on_result

    @classmethod
    def from_settings(cls, settings: Settings | None = None, replay: ReplayContext | None = None, **kw):
        from gatekeeper.settings import get_settings

        s = settings or get_settings()
        env = {"SEC_USER_AGENT": s.sec_user_agent} if s.sec_user_agent else {}
        cwd = replay.workspace if replay else s.root_path
        return cls(s.skills_path, cwd, env=env, replay=replay, **kw)

    @property
    def trader_dir(self) -> Path:
        return self.cwd / "trader"

    def script(self, tool: str) -> Path:
        if tool not in SCRIPTS:
            raise ValueError(f"unknown skill tool {tool!r}")
        folder, name = SCRIPTS[tool]
        return self.skills_dir / folder / name

    def command(self, tool: str, args: list[str], json_out: bool) -> list[str]:
        args = [str(a) for a in args]
        if self.replay is not None:
            args = self.replay.inject(tool, subcommand(tool, args), args)
        if json_out and "--json" not in args:
            args.append("--json")
        # -I: isolated mode, so nothing in the working folder can shadow a module.
        # -X utf8: UTF-8 output on Windows (-I ignores PYTHONIOENCODING).
        return [sys.executable, "-I", "-X", "utf8", str(self.script(tool)), *args]

    def run(
        self,
        tool: str,
        args: list[str] | tuple[str, ...] = (),
        *,
        json_out: bool = True,
        timeout: float = 300,
        writes_state: bool = False,
    ) -> RunResult:
        args = [str(a) for a in args]
        cmd = self.command(tool, args, json_out)
        sent = cmd[5:]  # the arguments after the script, as actually sent
        sub = subcommand(tool, args)
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        env = {**os.environ, **self.env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            if writes_state:
                self.trader_dir.mkdir(parents=True, exist_ok=True)
                with FileLock(self.trader_dir / LOCK_NAME, timeout=self.lock_timeout):
                    proc = self._exec(cmd, env, timeout)
            else:
                proc = self._exec(cmd, env, timeout)
        except subprocess.TimeoutExpired as e:
            res = RunResult(tool, sent, "error", None, stdout=_text(e.stdout), stderr=_text(e.stderr),
                            message=f"timed out after {timeout:g} s", started_at=started)
        except Timeout:
            res = RunResult(tool, sent, "error", None, started_at=started,
                            message=f"another run held the trader/ lock for over {self.lock_timeout:g} s")
        else:
            data = parse_json(proc.stdout) if json_out else None
            status = classify(tool, sub, proc.returncode, data, json_out, proc.stderr)
            message = error_message(proc.stderr, proc.stdout) if status == "error" else ""
            res = RunResult(tool, sent, status, proc.returncode, data, proc.stdout, proc.stderr,
                            message, started)
        res.duration_s = round(time.perf_counter() - t0, 3)
        if self.on_result is not None:
            self.on_result(res)
        return res

    def _exec(self, cmd: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.cwd.mkdir(parents=True, exist_ok=True)
        return subprocess.run(cmd, cwd=self.cwd, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def _text(b: bytes | str | None) -> str:
    if b is None:
        return ""
    return b if isinstance(b, str) else b.decode("utf-8", "replace")
