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
