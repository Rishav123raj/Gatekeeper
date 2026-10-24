"""Replay mode: run the skills on the recorded day shipped with their test fixtures.

A replay runs in its own working folder (`replay/workspace/`), so the live `trader/`
is never touched, and every call gets the replay clock and the matching saved data:
`--now` (or `--today`) and `--offline`, unless the caller passed them already.

The recorded day is Monday 2026-10-19. Intraday charts exist for TSLA only, so
entry, exit and the Time Machine replay TSLA; the scanner replays its 234-chart wall.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gatekeeper.clock import as_ny

REPLAY_DATE = "2026-10-19"
REPLAY_YEAR = "2026"
CHARTS = "@charts"  # the workspace's charts/ folder of <TICKER>.json files

# (tool, subcommand) -> (clock flag format, offline source, fixed extra args)
#   clock format: "ny" = --now "YYYY-MM-DD HH:MM" New York, "iso" = --now ISO with offset,
#                 "today" = --today YYYY-MM-DD, None = the tool takes no clock
#   offline source: a path under tests/fixtures, "@charts", "@charts/X.json", or None
INJECT: dict[tuple[str, str | None], tuple[str | None, str | None, tuple[str, ...]]] = {
    ("scanner", "universe"): (None, "trader-scanner/symdir", ()),
    ("scanner", "daily"): ("ny", "trader-scanner/daily-spark-2026-10-19.json", ()),
    ("scanner", "orb"): ("ny", "trader-scanner/wall5m-2026-10-19.json.gz", ()),
    ("news", None): ("iso", "trader-news", ()),
    ("entry", "check"): ("ny", CHARTS, ()),
    ("entry", "watch"): ("ny", CHARTS, ()),
    ("entry", "watchlist"): ("ny", CHARTS, ()),
    ("exit", "plan"): ("ny", CHARTS + "/TSLA.json", ()),
    ("exit", "show"): ("ny", None, ()),
    ("timemachine", "run"): ("ny", "trader-timemachine/TSLA-60d5m.json.gz", ()),
    ("timemachine", "chart"): ("ny", "trader-timemachine/TSLA-60d5m.json.gz", ()),
    ("budget", None): ("ny", None, ()),
    ("risk", None): ("ny", None, ()),
    ("alerts", "clock"): ("ny", None, ()),
    ("alerts", "quote"): ("ny", "trader-alerts", ()),
    ("alerts", "check"): ("ny", "trader-alerts", ()),
    ("analyst", None): (None, "trader-analyst", ()),
    ("pelosi", "index"): (None, "trader-pelosi/2026FD.zip", ("--year", REPLAY_YEAR)),
    ("pelosi", "new"): ("today", "trader-pelosi/2026FD.zip", ("--year", REPLAY_YEAR)),
}
for _sub in ("show", "approve", "decline", "result", "fill", "flatten", "log"):
    INJECT[("broker", _sub)] = ("ny", None, ())


@dataclass
class ReplayContext:
    now: datetime
    workspace: Path
    fixtures: Path

    def offline_path(self, source: str) -> Path:
        if source.startswith(CHARTS):
            return self.workspace / "charts" / source[len(CHARTS):].lstrip("/")
        return self.fixtures / source

    def inject(self, tool: str, sub: str | None, args: list[str]) -> list[str]:
        spec = INJECT.get((tool, sub))
        if spec is None:
            return list(args)
        clock, offline, extra = spec
        out = list(args)
        ny = as_ny(self.now)
        if clock == "ny" and "--now" not in out:
            out += ["--now", f"{ny:%Y-%m-%d %H:%M}"]
        elif clock == "iso" and "--now" not in out:
            out += ["--now", ny.isoformat()]
        elif clock == "today" and "--today" not in out:
            out += ["--today", f"{ny:%Y-%m-%d}"]
        if offline and "--offline" not in out:
            out += ["--offline", str(self.offline_path(offline))]
        for i in range(0, len(extra), 2):
            if extra[i] not in out:
                out += [extra[i], extra[i + 1]]
        return out

    def at(self, now: datetime) -> ReplayContext:
        """The same workspace at another moment of the replay day."""
        return ReplayContext(now, self.workspace, self.fixtures)


def default_paths() -> tuple[Path, Path]:
    from gatekeeper.settings import ROOT, get_settings

    return ROOT / "replay" / "workspace", get_settings().skills_path


def prepare_workspace(
    replay_now: datetime, workspace: Path | None = None, skills_dir: Path | None = None
) -> ReplayContext:
    """A fresh replay workspace: empty trader/ with the example config, and the charts.

    The example config is the skills' own: $5,000 budget, $50 max loss, paper true.
    """
    dws, dskills = default_paths() if workspace is None or skills_dir is None else (None, None)
    workspace = Path(workspace or dws)
    skills_dir = Path(skills_dir or dskills)
    fixtures = skills_dir / "tests" / "fixtures"

    for sub in ("trader", "charts"):
        shutil.rmtree(workspace / sub, ignore_errors=True)
    (workspace / "trader").mkdir(parents=True)
    (workspace / "charts").mkdir()

    config = json.loads((skills_dir / "trader-budget" / "config.example.json").read_text(encoding="utf-8"))
    config["paper"] = True
    (workspace / "trader" / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(fixtures / "trader-entry" / "TSLA-2026-10-19-5m.json", workspace / "charts" / "TSLA.json")
    return ReplayContext(replay_now, workspace, fixtures)
