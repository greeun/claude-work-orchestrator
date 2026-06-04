from pathlib import Path

from backlog import Backlog
from lease import LeaseTable
from config import load_config
from dispatch import can_dispatch


def _ready_task(bl, title="t", touches=None, depends_on=None):
    tid = bl.add(title)
    bl.classify(tid, touches=touches or [], depends_on=depends_on or [])
    return bl.get(tid)


def test_can_dispatch_ok(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    task = _ready_task(bl, touches=["ui/"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is True
    assert reason == "ok"


def test_not_ready_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    tid = bl.add("t")  # still inbox
    ok, reason = can_dispatch(bl, lt, cfg, bl.get(tid))
    assert ok is False
    assert "ready" in reason


def test_unfinished_dependency_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    dep = bl.add("dep")  # inbox, not done
    task = _ready_task(bl, depends_on=[dep])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert dep in reason


def test_done_dependency_allows(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    dep = bl.add("dep")
    bl.move(dep, "done")
    task = _ready_task(bl, depends_on=[dep])
    ok, _ = can_dispatch(bl, lt, cfg, task)
    assert ok is True


def test_lease_conflict_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    lt.acquire("T-099", ["payment/"], "/tmp/wt")
    task = _ready_task(bl, touches=["payment/refund.ts"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert "conflict" in reason


def test_max_active_ceiling_blocks(root):
    import json
    (root / "backlog" / "config.json").write_text(json.dumps({"max_active": 1}))
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    lt.acquire("T-099", ["other/"], "/tmp/wt")
    task = _ready_task(bl, touches=["ui/"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert "max_active" in reason


import pytest


def _ready(bl, title="t", touches=None, auto=False):
    tid = bl.add(title)
    bl.classify(tid, touches=touches or [], auto=auto)
    return tid


def test_dispatch_creates_worktree_and_lease(git_root):
    from dispatch import dispatch
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    tid = _ready(bl, touches=["ui/"])
    wt = dispatch(git_root, tid)
    assert Path(wt).exists()
    assert bl.get(tid)["status"] == "active"
    assert bl.get(tid)["worktree"] == str(wt)
    assert lt.get(tid)["task"] == tid


def test_dispatch_conflicting_raises(git_root):
    from dispatch import dispatch
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    lt.acquire("T-099", ["payment/"], "/tmp/wt")
    tid = _ready(bl, touches=["payment/refund.ts"])
    with pytest.raises(RuntimeError):
        dispatch(git_root, tid)


def test_dispatch_auto_only_auto_and_nonconflicting(git_root):
    from dispatch import dispatch_auto
    bl = Backlog(git_root)
    a = _ready(bl, "auto-ok", touches=["ui/"], auto=True)
    _ready(bl, "manual", touches=["api/"], auto=False)   # auto=False → skip
    dispatched = dispatch_auto(git_root)
    assert dispatched == [a]
    assert bl.get(a)["status"] == "active"


def test_loop_status_empty(root):
    from dispatch import loop_status
    s = loop_status(root)
    assert s["counts"]["ready"] == 0
    assert s["dispatchable"] == []
    assert s["active"] == []
    assert s["loop_can_progress"] is False


def test_loop_status_buckets_ready_tasks(root):
    from dispatch import loop_status
    bl = Backlog(root)
    a = bl.add("a"); bl.classify(a, touches=["x/"], auto=True)     # dispatchable
    b = bl.add("b"); bl.classify(b, touches=["y/"])                # needs_approval (auto False)
    s = loop_status(root)
    assert a in s["dispatchable"]
    assert b in s["needs_approval"]
    assert s["loop_can_progress"] is True


def test_loop_status_blocked_auto_by_lease(root):
    from dispatch import loop_status
    from lease import LeaseTable
    LeaseTable(root).acquire("T-099", ["x/"], "/tmp/wt")
    bl = Backlog(root)
    a = bl.add("a"); bl.classify(a, touches=["x/sub"], auto=True)   # conflicts with x/
    s = loop_status(root)
    assert a in [x["id"] for x in s["blocked_auto"]]
    assert s["dispatchable"] == []


def test_loop_status_active_makes_progress_true(root):
    from dispatch import loop_status
    bl = Backlog(root)
    a = bl.add("a"); bl.classify(a, touches=["x/"])
    bl.set_fields(a, worktree="/tmp/wt-a"); bl.move(a, "active")
    s = loop_status(root)
    assert s["counts"]["active"] == 1
    assert {"id": a, "worktree": "/tmp/wt-a"} in s["active"]
    assert s["loop_can_progress"] is True
