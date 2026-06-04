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
