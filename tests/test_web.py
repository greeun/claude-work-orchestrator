import json as _json

from web import build_state, handle_path
from backlog import Backlog


def test_build_state_keys_and_content(root):
    bl = Backlog(root)
    a = bl.add("a")
    bl.classify(a, touches=["x/"], auto=True)
    s = build_state(root)
    assert set(s.keys()) == {"tasks", "leases", "loop"}
    assert any(t["id"] == a for t in s["tasks"])
    assert "loop_can_progress" in s["loop"]
    assert s["leases"] == []


def test_handle_path_index(root):
    status, ctype, body = handle_path(root, "/")
    assert status == 200
    assert "text/html" in ctype
    assert b"cwo dashboard" in body


def test_handle_path_api_state(root):
    Backlog(root).add("a")
    status, ctype, body = handle_path(root, "/api/state")
    assert status == 200
    assert "application/json" in ctype
    data = _json.loads(body)
    assert "tasks" in data and "leases" in data and "loop" in data


def test_handle_path_strips_query_and_404(root):
    st, _c, _b = handle_path(root, "/api/state?x=1")
    assert st == 200
    st2, _c2, body2 = handle_path(root, "/nope")
    assert st2 == 404
