import json
import subprocess
from pathlib import Path

from tui import build_state, selectable_tasks, render, handle_key
from backlog import Backlog


def test_selectable_tasks_orders_inbox_before_ready(root):
    bl = Backlog(root)
    a = bl.add("a")                                   # inbox
    b = bl.add("b"); bl.classify(b, touches=["x/"])   # ready
    ids = [t["id"] for t in selectable_tasks(build_state(root))]
    assert ids == [a, b]


def test_render_shows_summary_selection_and_footer(root):
    Backlog(root).add("hello world")
    lines = render(build_state(root), 0)
    text = "\n".join(lines)
    assert "cwo watch" in text
    assert "T-001" in text and "hello world" in text
    assert any(l.startswith(">") for l in lines)   # selected marker
    assert "quit" in text.lower()


def test_handle_key_navigation_clamps(root):
    bl = Backlog(root); bl.add("a"); bl.add("b")
    state = build_state(root)
    assert handle_key(root, "down", state, 0)["selection"] == 1
    assert handle_key(root, "down", state, 1)["selection"] == 1   # clamp top
    assert handle_key(root, "up", state, 1)["selection"] == 0
    assert handle_key(root, "up", state, 0)["selection"] == 0     # clamp bottom


def test_handle_key_quit(root):
    assert handle_key(root, "q", build_state(root), 0)["quit"] is True


def test_handle_key_dispatch_auto(git_root):
    bl = Backlog(git_root); a = bl.add("a"); bl.classify(a, touches=["m/"], auto=True)
    r = handle_key(git_root, "a", build_state(git_root), 0)
    assert "dispatched" in r["message"]
    assert Backlog(git_root).get(a)["status"] == "active"


def test_handle_key_dispatch_selected(git_root):
    bl = Backlog(git_root); a = bl.add("a"); bl.classify(a, touches=["m/"])
    r = handle_key(git_root, "d", build_state(git_root), 0)
    assert Backlog(git_root).get(a)["status"] == "active"


def test_handle_key_integrate_selected(git_root):
    from dispatch import dispatch
    (git_root / "backlog" / "config.json").write_text(json.dumps({"test_command": "true"}))
    bl = Backlog(git_root); a = bl.add("a"); bl.classify(a, touches=["m/"])
    wt = dispatch(git_root, a)
    (Path(wt) / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "w"], check=True)
    state = build_state(git_root)
    idx = next(i for i, t in enumerate(selectable_tasks(state)) if t["id"] == a)
    handle_key(git_root, "i", state, idx)
    assert Backlog(git_root).get(a)["status"] == "done"


def test_handle_key_dispatch_conflict_captures_error(git_root):
    from lease import LeaseTable
    LeaseTable(git_root).acquire("T-099", ["m/"], "/tmp/wt")
    bl = Backlog(git_root); a = bl.add("a"); bl.classify(a, touches=["m/x"])  # conflicts
    r = handle_key(git_root, "d", build_state(git_root), 0)
    assert "error" in r["message"].lower()
    assert Backlog(git_root).get(a)["status"] == "ready"   # not dispatched
