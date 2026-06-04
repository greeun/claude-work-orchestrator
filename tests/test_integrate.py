import json
import subprocess
from pathlib import Path

from backlog import Backlog
from lease import LeaseTable
from dispatch import dispatch
from integrate import integrate


def _set_test_command(root, cmd):
    (root / "backlog" / "config.json").write_text(json.dumps({"test_command": cmd}))


def _ready_and_dispatch(git_root, touches):
    bl = Backlog(git_root)
    tid = bl.add("feature")
    bl.classify(tid, touches=touches)
    wt = dispatch(git_root, tid)
    # worktree에 실제 커밋을 만들어 머지할 내용이 있게 함
    (Path(wt) / "feature.txt").write_text("done\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "work"], check=True)
    return tid, wt


def test_integrate_happy_path(git_root):
    _set_test_command(git_root, "true")
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    tid, wt = _ready_and_dispatch(git_root, ["feature/"])
    res = integrate(git_root, tid)
    assert res["ok"] is True
    assert bl.get(tid)["status"] == "done"
    assert lt.get(tid) is None                      # 리스 반납
    assert not Path(wt).exists()                    # worktree 제거
    # main에 머지됐는지
    merged = subprocess.run(
        ["git", "-C", str(git_root), "show", "main:feature.txt"],
        capture_output=True, text=True)
    assert merged.returncode == 0


def test_integrate_failing_tests_keeps_active(git_root):
    _set_test_command(git_root, "false")
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    tid, wt = _ready_and_dispatch(git_root, ["feature/"])
    res = integrate(git_root, tid)
    assert res["ok"] is False
    assert res["reason"] == "tests failed"
    assert bl.get(tid)["status"] == "active"        # 되돌림
    assert lt.get(tid) is not None                  # 리스 유지
    assert Path(wt).exists()


def test_integrate_does_not_hold_lock_during_tests(git_root):
    # test_command tries to acquire project_lock; it can only succeed if integrate
    # is NOT holding the lock while tests run. (If integrate held it, this would
    # LockTimeout -> nonzero -> "tests failed".)
    import json
    from pathlib import Path
    from backlog import Backlog
    from dispatch import dispatch

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    # one-line python that grabs the project lock with a short timeout
    probe = (
        f'python3 -c "import sys; sys.path.insert(0, {scripts!r}); '
        f'from lock import project_lock; \n'
        f'import contextlib\n'
        f'ctx = project_lock({str(git_root)!r}, timeout=2)\n'
        f'ctx.__enter__(); ctx.__exit__(None, None, None)"'
    )
    (git_root / "backlog" / "config.json").write_text(json.dumps({"test_command": probe}))

    bl = Backlog(git_root)
    tid = bl.add("f"); bl.classify(tid, touches=["x/"])
    wt = dispatch(git_root, tid)
    (Path(wt) / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "w"], check=True)

    res = integrate(git_root, tid)   # called WITHOUT any external lock
    assert res["ok"] is True         # would be False if integrate held the lock during tests
    assert bl.get(tid)["status"] == "done"
