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


def test_post_add_then_classify(root):
    import json as _j
    from web import handle_post, build_state
    st, _c, body = handle_post(root, "/api/add", _j.dumps({"title": "x", "type": "bug"}).encode())
    assert st == 200
    tid = _j.loads(body)["id"]
    st2, _c2, _b2 = handle_post(root, "/api/classify",
                                _j.dumps({"id": tid, "touches": ["a/"], "auto": True}).encode())
    assert st2 == 200
    t = [x for x in build_state(root)["tasks"] if x["id"] == tid][0]
    assert t["status"] == "ready" and t["auto"] is True and t["touches"] == ["a/"]


def test_post_invalid_json_returns_400(root):
    from web import handle_post
    st, _c, _b = handle_post(root, "/api/add", b"not json")
    assert st == 400


def test_post_unknown_endpoint_404(root):
    from web import handle_post
    st, _c, _b = handle_post(root, "/api/nope", b"{}")
    assert st == 404


def test_post_classify_cycle_returns_400(root):
    import json as _j
    from web import handle_post
    from backlog import Backlog
    bl = Backlog(root)
    a = bl.add("a"); b = bl.add("b")
    handle_post(root, "/api/classify", _j.dumps({"id": b, "depends_on": [a]}).encode())
    st, _c, _b = handle_post(root, "/api/classify", _j.dumps({"id": a, "depends_on": [b]}).encode())
    assert st == 400  # cycle rejected (ValueError -> 400)


def test_post_dispatch_auto_and_gc(git_root):
    import json as _j
    from web import handle_post
    from backlog import Backlog
    bl = Backlog(git_root)
    a = bl.add("a"); bl.classify(a, touches=["m/"], auto=True)
    st, _c, body = handle_post(git_root, "/api/dispatch-auto", b"{}")
    assert st == 200 and a in _j.loads(body)["dispatched"]
    st2, _c2, body2 = handle_post(git_root, "/api/gc", b"{}")
    assert st2 == 200 and "reclaimed" in _j.loads(body2)


def test_handle_post_rejects_wrong_token(root):
    from web import handle_post
    st, _c, _b = handle_post(root, "/api/dispatch-auto", b"{}",
                             provided_token="wrong", expected_token="secret")
    assert st == 403


def test_handle_post_accepts_matching_token(git_root):
    import json as _j
    from web import handle_post
    st, _c, body = handle_post(git_root, "/api/dispatch-auto", b"{}",
                               provided_token="secret", expected_token="secret")
    assert st == 200
    assert "dispatched" in _j.loads(body)


def test_handle_post_no_auth_when_expected_token_none(root):
    import json as _j
    from web import handle_post
    st, _c, body = handle_post(root, "/api/add", b'{"title":"x"}', expected_token=None)
    assert st == 200
    assert "id" in _j.loads(body)


def test_handle_path_injects_token_into_page(root):
    from web import handle_path
    st, ctype, body = handle_path(root, "/", token="tok-xyz")
    assert st == 200
    assert b"tok-xyz" in body
