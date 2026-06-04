from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _init_backlog_dirs(proj: Path) -> None:
    """backlog/ 상태 디렉터리를 직접 생성한다.

    테스트 대상 모듈(backlog)에 의존하지 않도록 fixture에서 직접 만든다.
    backlog.Backlog.init() 자체의 동작은 Task 4의 단위 테스트가 검증한다.
    """
    for d in ("inbox", "ready", "active", "done"):
        (proj / "backlog" / d).mkdir(parents=True)


@pytest.fixture
def root(tmp_path):
    """백로그가 초기화된 임시 프로젝트 루트 (git 아님). paths/backlog/lease/gc용."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _init_backlog_dirs(proj)
    return proj


@pytest.fixture
def git_root(tmp_path):
    """백로그 + git repo(main 브랜치, 초기 커밋)인 임시 프로젝트 루트. dispatch/integrate용."""
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(proj), "config", "user.name", "t"], check=True)
    (proj / "README").write_text("seed\n")
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "init"], check=True)
    _init_backlog_dirs(proj)
    return proj
