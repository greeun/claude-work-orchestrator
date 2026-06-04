from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import any_overlap


class LeaseConflict(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeaseTable:
    def __init__(self, root):
        self.path = Path(root) / "backlog" / "LEASES.json"

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text()).get("leases", [])

    def _save(self, leases: list[dict[str, Any]]) -> None:
        self.path.write_text(
            json.dumps({"leases": leases}, ensure_ascii=False, indent=2) + "\n"
        )

    def active(self) -> list[dict[str, Any]]:
        return self.load()

    def get(self, task_id: str) -> dict[str, Any] | None:
        for lease in self.load():
            if lease["task"] == task_id:
                return lease
        return None

    def conflicts(self, touches) -> list[dict[str, Any]]:
        return [l for l in self.load() if any_overlap(touches, l["touches"])]

    def acquire(self, task_id: str, touches, worktree: str) -> dict[str, Any]:
        leases = self.load()
        for lease in leases:
            if lease["task"] != task_id and any_overlap(touches, lease["touches"]):
                raise LeaseConflict(
                    f"{task_id} touches conflict with {lease['task']}"
                )
        leases = [l for l in leases if l["task"] != task_id]
        lease = {
            "task": task_id, "touches": list(touches),
            "worktree": worktree, "heartbeat": _now(),
        }
        leases.append(lease)
        self._save(leases)
        return lease

    def release(self, task_id: str) -> None:
        self._save([l for l in self.load() if l["task"] != task_id])

    def heartbeat(self, task_id: str) -> None:
        leases = self.load()
        for lease in leases:
            if lease["task"] == task_id:
                lease["heartbeat"] = _now()
        self._save(leases)
