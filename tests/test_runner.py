import json
import subprocess
from pathlib import Path

import pytest

from runner import run_loop
from backlog import Backlog


def _stub_executor(task, worktree):
    """진짜 claude 대신: worktree에 파일 만들고 커밋. 항상 성공."""
    f = Path(worktree) / f"{task['id']}.txt"
    f.write_text(task["title"] + "\n")
    subprocess.run(["git", "-C", str(worktree), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(worktree), "commit", "-q", "-m", f"do {task['id']}"], check=True)
    return True


def _set_pass_gate(root):
    (root / "backlog" / "config.json").write_text(json.dumps({"test_command": "true"}))


def test_run_loop_drains_independent_and_conflicting(git_root):
    _set_pass_gate(git_root)
    bl = Backlog(git_root)
    a = bl.add("A"); bl.classify(a, touches=["a/"], auto=True)       # independent
    b = bl.add("B"); bl.classify(b, touches=["b/"], auto=True)       # independent
    c = bl.add("C"); bl.classify(c, touches=["a/x"], auto=True)      # conflicts with A -> serialized
    summary = run_loop(git_root, _stub_executor, max_iters=20)
    assert set(summary["done"]) == {a, b, c}
    assert summary["failed"] == []
    # all merged to main
    assert Backlog(git_root).get(c)["status"] == "done"


def test_run_loop_requires_executor_unless_dry_run(git_root):
    with pytest.raises(ValueError):
        run_loop(git_root, None, dry_run=False)


def test_run_loop_dry_run_does_not_mutate(git_root):
    bl = Backlog(git_root)
    a = bl.add("A"); bl.classify(a, touches=["a/"], auto=True)
    summary = run_loop(git_root, None, dry_run=True)
    assert summary.get("dry_run") is True
    assert a in summary["status"]["dispatchable"]
    # still ready, nothing dispatched
    assert Backlog(git_root).get(a)["status"] == "ready"


def test_run_loop_executor_failure_leaves_active_and_terminates(git_root):
    _set_pass_gate(git_root)
    bl = Backlog(git_root)
    a = bl.add("A"); bl.classify(a, touches=["a/"], auto=True)

    def failing(task, worktree):
        return False

    summary = run_loop(git_root, failing, max_iters=20)
    assert a in summary["failed"]
    assert a not in summary["done"]
    assert Backlog(git_root).get(a)["status"] == "active"  # left for human
