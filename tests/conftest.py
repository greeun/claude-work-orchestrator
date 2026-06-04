from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def root(tmp_path):
    """백로그가 초기화된 임시 프로젝트 루트 (git 아님). paths/backlog/lease/gc용."""
    import backlog  # scripts/backlog.py
    proj = tmp_path / "proj"
    proj.mkdir()
    backlog.Backlog(proj).init()
    return proj


@pytest.fixture
def git_root(tmp_path):
    """백로그 + git repo(main 브랜치, 초기 커밋)인 임시 프로젝트 루트. dispatch/integrate용."""
    import backlog
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.name", "t"], check=True)
    (proj / "README").write_text("seed\n")
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "init"], check=True)
    backlog.Backlog(proj).init()
    return proj
