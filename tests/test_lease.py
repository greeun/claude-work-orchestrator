import pytest

from lease import LeaseTable, LeaseConflict


def test_acquire_and_active(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    active = lt.active()
    assert len(active) == 1
    assert active[0]["task"] == "T-001"
    assert active[0]["worktree"] == "/tmp/wt-1"
    assert "heartbeat" in active[0]


def test_acquire_conflicting_touches_raises(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    with pytest.raises(LeaseConflict):
        lt.acquire("T-002", ["payment/refund.ts"], "/tmp/wt-2")


def test_disjoint_touches_coexist(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    lt.acquire("T-002", ["ui/cart.tsx"], "/tmp/wt-2")
    assert len(lt.active()) == 2


def test_conflicts_lists_overlapping(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    hits = lt.conflicts(["payment/refund.ts"])
    assert [h["task"] for h in hits] == ["T-001"]
    assert lt.conflicts(["ui/cart.tsx"]) == []


def test_release_removes_lease(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    lt.release("T-001")
    assert lt.active() == []


def test_heartbeat_updates_timestamp(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    before = lt.get("T-001")["heartbeat"]
    # 타임스탬프를 과거로 강제 후 heartbeat가 갱신하는지 확인
    leases = lt.load()
    leases[0]["heartbeat"] = "2000-01-01T00:00:00+00:00"
    lt._save(leases)
    lt.heartbeat("T-001")
    after = lt.get("T-001")["heartbeat"]
    assert after != "2000-01-01T00:00:00+00:00"
    assert after >= before[:4]  # 단순 sanity (현재연도 ISO)
