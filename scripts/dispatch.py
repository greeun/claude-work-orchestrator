from __future__ import annotations

import subprocess
from pathlib import Path

from backlog import Backlog
from config import Config, load_config
from lease import LeaseTable
from paths import any_overlap


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def can_dispatch(backlog: Backlog, leases: LeaseTable, config: Config,
                 task: dict) -> tuple[bool, str]:
    if task["status"] != "ready":
        return False, f"status is {task['status']}, not ready"
    for dep in task.get("depends_on", []):
        try:
            d = backlog.get(dep)
        except KeyError:
            return False, f"dependency {dep} not found"
        if d["status"] != "done":
            return False, f"dependency {dep} not done ({d['status']})"
    active = leases.active()
    occupied = [t for lease in active for t in lease["touches"]]
    if any_overlap(task["touches"], occupied):
        return False, "touches conflict with active lease"
    if len(active) >= config.max_active:
        return False, f"max_active {config.max_active} reached"
    return True, "ok"
