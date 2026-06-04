from backlog import Backlog


def test_init_creates_state_dirs(tmp_path):
    bl = Backlog(tmp_path)
    bl.init()
    for d in ("inbox", "ready", "active", "done"):
        assert (tmp_path / "backlog" / d).is_dir()


def test_add_creates_inbox_record(root):
    bl = Backlog(root)
    tid = bl.add("fix refund bug", type="bug", priority="high")
    assert tid == "T-001"
    task = bl.get(tid)
    assert task["status"] == "inbox"
    assert task["type"] == "bug"
    assert task["priority"] == "high"
    assert task["touches"] == []
    assert task["auto"] is False
    assert (root / "backlog" / "inbox" / "T-001.json").exists()


def test_next_id_increments(root):
    bl = Backlog(root)
    assert bl.add("a") == "T-001"
    assert bl.add("b") == "T-002"


def test_list_all_and_by_status(root):
    bl = Backlog(root)
    bl.add("a")
    bl.add("b")
    assert len(bl.list()) == 2
    assert len(bl.list("inbox")) == 2
    assert bl.list("ready") == []


def test_set_fields_persists(root):
    bl = Backlog(root)
    tid = bl.add("a")
    bl.set_fields(tid, priority="low", auto=True)
    task = bl.get(tid)
    assert task["priority"] == "low"
    assert task["auto"] is True


def test_move_relocates_file_and_updates_status(root):
    bl = Backlog(root)
    tid = bl.add("a")
    bl.move(tid, "ready")
    assert not (root / "backlog" / "inbox" / f"{tid}.json").exists()
    assert (root / "backlog" / "ready" / f"{tid}.json").exists()
    assert bl.get(tid)["status"] == "ready"


def test_integrating_stays_in_active_dir(root):
    bl = Backlog(root)
    tid = bl.add("a")
    bl.move(tid, "active")
    bl.move(tid, "integrating")
    assert (root / "backlog" / "active" / f"{tid}.json").exists()
    assert bl.get(tid)["status"] == "integrating"


def test_classify_sets_fields_and_moves_to_ready(root):
    bl = Backlog(root)
    tid = bl.add("a")
    bl.classify(tid, touches=["payment/"], depends_on=["T-000"], auto=True)
    task = bl.get(tid)
    assert task["status"] == "ready"
    assert task["touches"] == ["payment/"]
    assert task["depends_on"] == ["T-000"]
    assert task["auto"] is True


def test_move_rejects_bad_status(root):
    import pytest
    bl = Backlog(root)
    tid = bl.add("a")
    with pytest.raises(ValueError):
        bl.move(tid, "nope")
