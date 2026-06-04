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
