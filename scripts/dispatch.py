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


def worktree_path(root, config: Config, task_id: str) -> Path:
    root = Path(root)
    parent = Path(config.worktree_parent) if config.worktree_parent else root.parent
    return parent / f"{root.name}-{task_id}"


def dispatch(root, task_id: str) -> Path:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    task = backlog.get(task_id)
    ok, reason = can_dispatch(backlog, leases, config, task)
    if not ok:
        raise RuntimeError(f"cannot dispatch {task_id}: {reason}")
    wt = worktree_path(root, config, task_id)
    branch = f"cwo/{task_id}"
    r = _git(root, "worktree", "add", str(wt), "-b", branch, config.main_branch)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {r.stderr.strip()}")
    leases.acquire(task_id, task["touches"], str(wt))
    backlog.set_fields(task_id, worktree=str(wt))
    backlog.move(task_id, "active")
    return wt


def dispatch_auto(root) -> list[str]:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    dispatched = []
    for task in backlog.list("ready"):
        if not task.get("auto"):
            continue
        ok, _ = can_dispatch(backlog, leases, config, task)
        if ok:
            dispatch(root, task["id"])
            dispatched.append(task["id"])
    return dispatched
