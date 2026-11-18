"""Small JSON state the kit keeps in `.kit/state.json` between commands."""

from __future__ import annotations

import json
from typing import Any

from kit import config


def _path():
    return config.state_dir() / "state.json"


def load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update(**values: Any) -> dict[str, Any]:
    """Merge values into the state file and write it back atomically."""
    data = load()
    data.update(values)
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return data
