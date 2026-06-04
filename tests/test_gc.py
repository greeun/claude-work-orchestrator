import json

from backlog import Backlog
from lease import LeaseTable
from cwo_gc import gc


def _active_with_lease(root, worktree):
    """active 상태 작업 + 그에 대한 리스를 만든다."""
    bl, lt = Backlog(root), LeaseTable(root)
    tid = bl.add("t")
    bl.classify(tid, touches=["x/"])
    bl.set_fields(tid, worktree=worktree)
    bl.move(tid, "active")
    lt.acquire(tid, ["x/"], worktree)
    return tid


def test_gc_reclaims_missing_worktree(root):
    bl, lt = Backlog(root), LeaseTable(root)
    tid = _active_with_lease(root, "/nonexistent/wt")
    reclaimed = gc(root)
    assert [r["task"] for r in reclaimed] == [tid]
    assert reclaimed[0]["reason"] == "missing-worktree"
    assert lt.get(tid) is None                  # 리스 회수
    assert bl.get(tid)["status"] == "ready"     # 재투입 대기로 되돌림
    assert bl.get(tid)["worktree"] is None


def test_gc_reclaims_stale_heartbeat(root, tmp_path):
    wt = tmp_path / "live-wt"
    wt.mkdir()
    bl, lt = Backlog(root), LeaseTable(root)
    tid = _active_with_lease(root, str(wt))
    # heartbeat를 과거로 강제
    leases = lt.load()
    leases[0]["heartbeat"] = "2000-01-01T00:00:00+00:00"
    lt._save(leases)
    reclaimed = gc(root)
    assert [r["task"] for r in reclaimed] == [tid]
    assert reclaimed[0]["reason"] == "stale"


def test_gc_keeps_fresh_lease(root, tmp_path):
    wt = tmp_path / "live-wt"
    wt.mkdir()
    tid = _active_with_lease(root, str(wt))
    reclaimed = gc(root)
    assert reclaimed == []
    assert LeaseTable(root).get(tid) is not None
