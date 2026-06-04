from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def integrate(root, task_id: str) -> dict:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    task = backlog.get(task_id)
    if task["status"] not in ("active", "integrating"):
        return {"ok": False, "reason": f"status {task['status']} not active"}
    wt = task.get("worktree")
    if not wt or not Path(wt).exists():
        return {"ok": False, "reason": "worktree missing"}

    backlog.move(task_id, "integrating")

    # 1. 테스트
    test = subprocess.run(
        shlex.split(config.test_command), cwd=wt, capture_output=True, text=True
    )
    if test.returncode != 0:
        backlog.move(task_id, "active")
        return {"ok": False, "reason": "tests failed",
                "output": test.stdout + test.stderr}

    # 2. 머지
    branch = f"cwo/{task_id}"
    _git(root, "checkout", config.main_branch)
    m = _git(root, "merge", "--no-ff", branch, "-m",
             f"merge {task_id}: {task['title']}")
    if m.returncode != 0:
        _git(root, "merge", "--abort")
        backlog.move(task_id, "active")
        return {"ok": False, "reason": "merge conflict",
                "output": m.stdout + m.stderr}

    # 3. 리스 반납 + done + 정리
    leases.release(task_id)
    _git(root, "worktree", "remove", str(wt), "--force")
    _git(root, "branch", "-d", branch)
    backlog.set_fields(task_id, worktree=None)
    backlog.move(task_id, "done")
    return {"ok": True, "task": task_id}
