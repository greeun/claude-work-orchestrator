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


def test_classify_rejects_direct_cycle(root):
    import pytest
    bl = Backlog(root)
    a = bl.add("a")  # T-001
    b = bl.add("b")  # T-002
    bl.classify(b, touches=[], depends_on=[a])     # T-002 -> T-001
    with pytest.raises(ValueError):                # T-001 -> T-002 closes the cycle
        bl.classify(a, touches=[], depends_on=[b])


def test_classify_rejects_self_dependency(root):
    import pytest
    bl = Backlog(root)
    a = bl.add("a")
    with pytest.raises(ValueError):
        bl.classify(a, touches=[], depends_on=[a])


def test_classify_rejects_transitive_cycle(root):
    import pytest
    bl = Backlog(root)
    a = bl.add("a")  # T-001
    b = bl.add("b")  # T-002
    c = bl.add("c")  # T-003
    bl.classify(b, touches=[], depends_on=[a])     # T-002 -> T-001
    bl.classify(c, touches=[], depends_on=[b])     # T-003 -> T-002 -> T-001
    with pytest.raises(ValueError):                # T-001 -> T-003 closes a 3-cycle
        bl.classify(a, touches=[], depends_on=[c])


def test_classify_allows_nonexistent_dependency(root):
    # 아직 없는 작업에 대한 의존은 순환이 아니므로 허용 (기존 동작 유지)
    bl = Backlog(root)
    a = bl.add("a")
    bl.classify(a, touches=[], depends_on=["T-999"])  # must NOT raise
    assert bl.get(a)["depends_on"] == ["T-999"]


def test_classify_allows_dag(root):
    # 비순환 다중 의존은 허용
    bl = Backlog(root)
    a = bl.add("a"); b = bl.add("b"); c = bl.add("c")
    bl.classify(a, touches=[])
    bl.classify(b, touches=[])
    bl.classify(c, touches=[], depends_on=[a, b])  # diamond top, no cycle
    assert bl.get(c)["depends_on"] == [a, b]
