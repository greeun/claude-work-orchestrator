from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STATUSES = ["inbox", "ready", "active", "integrating", "done"]
DIRS = ["inbox", "ready", "active", "done"]


def dir_for_status(status: str) -> str:
    """integrating은 active/ 디렉터리를 공유한다. 그 외는 동명 디렉터리."""
    return "active" if status == "integrating" else status


class Backlog:
    def __init__(self, root):
        self.root = Path(root)
        self.base = self.root / "backlog"

    def init(self) -> None:
        for d in DIRS:
            (self.base / d).mkdir(parents=True, exist_ok=True)

    def next_id(self) -> str:
        nums = []
        for d in DIRS:
            for f in (self.base / d).glob("T-*.json"):
                m = re.match(r"T-(\d+)\.json$", f.name)
                if m:
                    nums.append(int(m.group(1)))
        n = (max(nums) + 1) if nums else 1
        return f"T-{n:03d}"

    def path_of(self, task_id: str) -> Path:
        for d in DIRS:
            p = self.base / d / f"{task_id}.json"
            if p.exists():
                return p
        raise KeyError(task_id)

    def _write(self, path: Path, task: dict[str, Any]) -> None:
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")

    def add(self, title: str, type: str = "feature",
            source: str = "human", priority: str = "medium") -> str:
        task_id = self.next_id()
        task = {
            "id": task_id, "title": title, "type": type,
            "source": source, "touches": [], "depends_on": [],
            "status": "inbox", "priority": priority,
            "auto": False, "worktree": None,
        }
        self._write(self.base / "inbox" / f"{task_id}.json", task)
        return task_id

    def get(self, task_id: str) -> dict[str, Any]:
        return json.loads(self.path_of(task_id).read_text())

    def save(self, task: dict[str, Any]) -> None:
        self._write(self.path_of(task["id"]), task)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        out = []
        for d in DIRS:
            for f in sorted((self.base / d).glob("T-*.json")):
                t = json.loads(f.read_text())
                if status is None or t["status"] == status:
                    out.append(t)
        return out
