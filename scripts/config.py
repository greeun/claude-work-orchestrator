from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "max_active": 4,
    "stale_minutes": 30,
    "test_command": "pytest",
    "main_branch": "main",
    "worktree_parent": None,  # None → root.parent 사용
}


@dataclass
class Config:
    max_active: int = 4
    stale_minutes: int = 30
    test_command: str = "pytest"
    main_branch: str = "main"
    worktree_parent: str | None = None


def load_config(root) -> Config:
    path = Path(root) / "backlog" / "config.json"
    data = dict(DEFAULTS)
    if path.exists():
        data.update(json.loads(path.read_text()))
    return Config(**{k: data[k] for k in DEFAULTS})
