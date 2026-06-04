from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def _age_minutes(iso: str) -> float:
    t = datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 60.0


def gc(root) -> list[dict]:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    reclaimed = []
    for lease in list(leases.active()):
        wt = lease.get("worktree")
        missing = not (wt and Path(wt).exists())
        stale = _age_minutes(lease["heartbeat"]) > config.stale_minutes
        if not (missing or stale):
            continue
        leases.release(lease["task"])
        branch = f"cwo/{lease['task']}"
        if wt:
            _git(root, "worktree", "remove", str(wt), "--force")
        _git(root, "worktree", "prune")
        _git(root, "branch", "-D", branch)
        try:
            task = backlog.get(lease["task"])
            if task["status"] in ("active", "integrating"):
                backlog.set_fields(lease["task"], worktree=None)
                backlog.move(lease["task"], "ready")
        except KeyError:
            pass
        reclaimed.append({
            "task": lease["task"],
            "reason": "missing-worktree" if missing else "stale",
        })
    return reclaimed
