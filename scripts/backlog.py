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

    def set_fields(self, task_id: str, **fields) -> dict[str, Any]:
        task = self.get(task_id)
        task.update(fields)
        self.save(task)
        return task

    def move(self, task_id: str, to_status: str) -> dict[str, Any]:
        if to_status not in STATUSES:
            raise ValueError(f"bad status: {to_status}")
        src = self.path_of(task_id)
        task = json.loads(src.read_text())
        task["status"] = to_status
        dst = self.base / dir_for_status(to_status) / src.name
        self._write(dst, task)
        if dst != src:
            src.unlink()
        return task

    def _reachable_deps(self, deps: list[str]) -> set[str]:
        """deps에서 depends_on 간선을 따라 도달 가능한 모든 작업 id 집합.

        존재하지 않는 작업(KeyError)은 나가는 간선이 없는 잎으로 취급한다.
        """
        seen: set[str] = set()
        stack = list(deps)
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            try:
                task = self.get(cur)
            except KeyError:
                continue
            stack.extend(task.get("depends_on", []))
        return seen

    def classify(self, task_id: str, touches, depends_on=None,
                 auto: bool = False) -> dict[str, Any]:
        deps = list(depends_on or [])
        if task_id in self._reachable_deps(deps):
            raise ValueError(
                f"dependency cycle: {task_id} is reachable from its own depends_on {deps}"
            )
        self.set_fields(task_id, touches=list(touches),
                        depends_on=deps, auto=auto)
        return self.move(task_id, "ready")
