"""Shared helpers for the skill wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from gatekeeper.runner import RunResult, SkillRunner


def runner_or_default(runner: SkillRunner | None) -> SkillRunner:
    return runner if runner is not None else SkillRunner.from_settings()


def opt(args: list[str], flag: str, value: Any) -> list[str]:
    """Append `flag value` when value is not None (and `flag` alone when value is True)."""
    if value is True:
        args.append(flag)
    elif value is not None and value is not False:
        args += [flag, str(value)]
    return args


def _invalid(res: RunResult, model: type[BaseModel], e: ValidationError) -> None:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    res.status = "error"
    res.message = f"unexpected {res.tool} output for {model.__name__} at {where or 'top'}: {first['msg']}"


def parse[M: BaseModel](model: type[M], res: RunResult, data: Any = None) -> M | None:
    data = res.data if data is None else data
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        _invalid(res, model, e)
        return None


def parse_list[M: BaseModel](model: type[M], res: RunResult, data: Any = None) -> list[M] | None:
    data = res.data if data is None else data
    if data is None:
        return None
    if not isinstance(data, list):
        res.status, res.message = "error", f"unexpected {res.tool} output: expected a list"
        return None
    try:
        return [model.model_validate(x) for x in data]
    except ValidationError as e:
        _invalid(res, model, e)
        return None


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
