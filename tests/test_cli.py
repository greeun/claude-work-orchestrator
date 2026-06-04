import subprocess
from pathlib import Path

from cwo import main


def test_add_and_list(root, capsys):
    main(["--root", str(root), "add", "fix bug", "--type", "bug"])
    tid = capsys.readouterr().out.strip()
    assert tid == "T-001"
    main(["--root", str(root), "list"])
    out = capsys.readouterr().out
    assert "T-001" in out and "fix bug" in out and "[inbox]" in out


def test_check_reports_not_ready(root, capsys):
    import pytest
    main(["--root", str(root), "add", "t"])
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        main(["--root", str(root), "check", "T-001"])
    assert e.value.code == 1
    assert "NO" in capsys.readouterr().out


def test_full_loop_via_cli(git_root, capsys):
    # config: 테스트 통과하도록 true
    (git_root / "backlog" / "config.json").write_text('{"test_command": "true"}')
    r = str(git_root)
    main(["--root", r, "add", "feature"]); capsys.readouterr()
    main(["--root", r, "classify", "T-001", "--touches", "feat/"]); capsys.readouterr()
    main(["--root", r, "dispatch", "T-001"])
    wt = capsys.readouterr().out.split("@")[-1].strip()
    # worktree에 커밋 생성
    (Path(wt) / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wt, "commit", "-q", "-m", "w"], check=True)
    with __import__("pytest").raises(SystemExit) as e:
        main(["--root", r, "integrate", "T-001"])
    assert e.value.code == 0
    main(["--root", r, "list", "--status", "done"])
    assert "T-001" in capsys.readouterr().out


def test_heartbeat_command_updates_lease(root, capsys):
    from lease import LeaseTable
    lt = LeaseTable(root)
    lt.acquire("T-001", ["x/"], "/tmp/wt")
    # heartbeat를 과거로 강제
    leases = lt.load()
    leases[0]["heartbeat"] = "2000-01-01T00:00:00+00:00"
    lt._save(leases)
    main(["--root", str(root), "heartbeat", "T-001"])
    out = capsys.readouterr().out
    assert "T-001" in out
    assert lt.get("T-001")["heartbeat"] != "2000-01-01T00:00:00+00:00"


def _commit_in_worktree(wt):
    import subprocess
    from pathlib import Path
    (Path(wt) / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wt, "commit", "-q", "-m", "w"], check=True)


def _setup_blocked_pair(git_root, capsys, auto_redispatch):
    """T-001 active(holds mod/), T-002 ready+auto blocked by overlap (mod/sub)."""
    import json
    cfg = {"test_command": "true"}
    if auto_redispatch:
        cfg["auto_redispatch"] = True
    (git_root / "backlog" / "config.json").write_text(json.dumps(cfg))
    r = str(git_root)
    main(["--root", r, "add", "A"]); capsys.readouterr()
    main(["--root", r, "add", "B"]); capsys.readouterr()
    main(["--root", r, "classify", "T-001", "--touches", "mod/", "--auto"]); capsys.readouterr()
    main(["--root", r, "classify", "T-002", "--touches", "mod/sub", "--auto"]); capsys.readouterr()
    main(["--root", r, "dispatch", "T-001"])
    wt = capsys.readouterr().out.split("@")[-1].strip()
    _commit_in_worktree(wt)
    return r


def test_integrate_auto_redispatch_picks_up_blocked_task(git_root, capsys):
    import pytest
    r = _setup_blocked_pair(git_root, capsys, auto_redispatch=True)
    with pytest.raises(SystemExit) as e:
        main(["--root", r, "integrate", "T-001"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "redispatched" in out and "T-002" in out
    main(["--root", r, "list", "--status", "active"])
    assert "T-002" in capsys.readouterr().out


def test_integrate_manual_mode_does_not_redispatch(git_root, capsys):
    import pytest
    r = _setup_blocked_pair(git_root, capsys, auto_redispatch=False)
    with pytest.raises(SystemExit) as e:
        main(["--root", r, "integrate", "T-001"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "redispatched" not in out
    main(["--root", r, "list", "--status", "ready"])
    assert "T-002" in capsys.readouterr().out  # stays ready (pull-based)


def test_integrate_no_redispatch_flag_overrides_auto(git_root, capsys):
    import pytest
    r = _setup_blocked_pair(git_root, capsys, auto_redispatch=True)
    with pytest.raises(SystemExit):
        main(["--root", r, "integrate", "T-001", "--no-redispatch"])
    out = capsys.readouterr().out
    assert "redispatched" not in out
    main(["--root", r, "list", "--status", "ready"])
    assert "T-002" in capsys.readouterr().out


def test_init_auto_redispatch_flag_writes_config(tmp_path, capsys):
    from config import load_config
    main(["--root", str(tmp_path), "init", "--auto-redispatch"])
    capsys.readouterr()
    assert load_config(tmp_path).auto_redispatch is True


def test_loop_status_cli_outputs_json(root, capsys):
    import json as _json
    from backlog import Backlog
    bl = Backlog(root)
    a = bl.add("a"); bl.classify(a, touches=["x/"], auto=True)
    main(["--root", str(root), "loop-status"])
    data = _json.loads(capsys.readouterr().out)
    assert a in data["dispatchable"]
    assert data["loop_can_progress"] is True


def test_gc_auto_redispatch_does_not_crash(git_root, capsys):
    import json
    import shutil
    from pathlib import Path
    from backlog import Backlog
    r = str(git_root)
    (git_root / "backlog" / "config.json").write_text(
        json.dumps({"auto_redispatch": True})
    )
    main(["--root", r, "add", "A"]); capsys.readouterr()
    main(["--root", r, "classify", "T-001", "--touches", "mod/", "--auto"]); capsys.readouterr()
    main(["--root", r, "dispatch", "T-001"])
    wt = capsys.readouterr().out.split("@")[-1].strip()
    shutil.rmtree(wt)                     # kill the session → missing worktree
    main(["--root", r, "gc"])             # must NOT raise; reclaim then auto-redispatch
    out = capsys.readouterr().out
    assert "reclaimed: T-001" in out
    assert "redispatched: T-001" in out
    assert Backlog(git_root).get("T-001")["status"] == "active"


def test_init_warns_git_repo_without_gitignore(git_root, capsys):
    # git_root is a git repo with a README but no .gitignore
    main(["--root", str(git_root), "init"])
    out = capsys.readouterr().out.lower()
    # distinctive warning sentence — never appears in a tmp path
    assert "no .gitignore in this git repo" in out


def test_init_no_warning_when_gitignore_present(git_root, capsys):
    (git_root / ".gitignore").write_text("__pycache__/\n")
    main(["--root", str(git_root), "init"])
    out = capsys.readouterr().out.lower()
    # distinctive warning sentence — never appears in a tmp path
    assert "no .gitignore in this git repo" not in out


def test_init_no_warning_when_not_git_repo(root, capsys):
    # `root` fixture is NOT a git repo
    main(["--root", str(root), "init"])
    out = capsys.readouterr().out.lower()
    # distinctive warning sentence — never appears in a tmp path
    assert "no .gitignore in this git repo" not in out
