# Claude Work Orchestrator (`cwo`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한 프로젝트에서 수시로 발생하는 작업을 파일 백로그에 등록하고, 영향범위 리스로 충돌을 차단하며, 비충돌·독립 작업만 git worktree로 투입하는 동시작업 오케스트레이션 엔진(v1).

**Architecture:** 계층형 — 백로그 코어(작업 레코드 + 상태 디렉터리) + 리스 충돌 엔진을 안정 계약으로 두고, 그 위에 디스패처/통합 게이트/GC를 얹는다. 모든 모듈은 `scripts/`의 플랫 구조, JSON 저장(stdlib), argparse CLI. csm 컨벤션을 따른다.

**Tech Stack:** Python 3.13 (stdlib only — `json`, `subprocess`, `pathlib`, `argparse`, `datetime`, `re`, `shlex`), pytest, git worktree.

> 커밋 메시지는 conventional commits 형식. author는 repo의 설정된 git config(`greeun <github.com@tlog.net>`)를 사용한다.

---

## File Structure

```
claude-skills/claude-work-orchestrator/
├── SKILL.md                # 프로토콜·트리아지 결정트리·자동투입 정책·command 레퍼런스 (Task 11)
├── scripts/
│   ├── config.py           # 설정 로드 (max_active, stale_minutes, test_command, main_branch, worktree_parent)
│   ├── paths.py            # touches 경로 겹침 판정 primitive (충돌의 최소 단위)
│   ├── backlog.py          # Backlog Store: 작업 레코드 I/O, ID 발급, 상태(디렉터리) 이동
│   ├── lease.py            # Lease Table: LEASES.json, 충돌 판정, acquire/release/heartbeat
│   ├── dispatch.py         # Dispatcher: can_dispatch + dispatch(worktree 생성) + dispatch_auto
│   ├── integrate.py        # Integration Gate: 테스트→머지→리스 반납→done→worktree 제거
│   ├── cwo_gc.py           # GC/Reaper: 고아 리스 회수
│   └── cwo.py              # CLI 엔트리 (argparse) — 위 모듈 묶음
└── tests/
    ├── conftest.py         # 공용 fixture (plain root, git_root)
    ├── test_paths.py
    ├── test_config.py
    ├── test_backlog.py
    ├── test_lease.py
    ├── test_dispatch.py
    ├── test_integrate.py
    ├── test_gc.py
    └── test_cli.py
```

각 모듈은 단일 책임. 의존 방향: `paths`/`config` ← `backlog`/`lease` ← `dispatch`/`integrate`/`cwo_gc` ← `cwo`(CLI). 순환 없음.

---

## Task 1: Scaffolding + test harness

**Files:**
- Create: `scripts/__init__.py` (빈 파일 — 아님, 플랫 import라 불필요. 대신 디렉터리만)
- Create: `tests/conftest.py`

- [ ] **Step 1: 디렉터리 생성**

Run:
```bash
cd claude-skills/claude-work-orchestrator
mkdir -p scripts tests
```

- [ ] **Step 2: conftest.py 작성 (공용 fixture)**

`tests/conftest.py`:
```python
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
```

> 주: fixture는 `backlog` 모듈을 import하지 않고 디렉터리를 직접 만든다 — 테스트 대상 모듈에 대한 결합을 끊어, config 등 backlog와 무관한 모듈의 테스트가 Task 4 이전에도 통과하도록 한다.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: test harness with root and git_root fixtures"
```

---

## Task 2: `paths.py` — touches 겹침 판정 (충돌 primitive)

**Files:**
- Create: `scripts/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

`tests/test_paths.py`:
```python
from paths import normalize, overlaps, any_overlap


def test_normalize_strips_slashes_and_space():
    assert normalize("  payment/ ") == "payment"
    assert normalize("/api/order.ts/") == "api/order.ts"


def test_overlaps_equal():
    assert overlaps("api/order.ts", "api/order.ts") is True


def test_overlaps_dir_is_ancestor_of_file():
    assert overlaps("payment/", "payment/refund.ts") is True
    assert overlaps("payment/refund.ts", "payment") is True


def test_overlaps_sibling_prefix_does_not_overlap():
    # "payment" must NOT be treated as a prefix of "payment2"
    assert overlaps("payment", "payment2") is False


def test_any_overlap_disjoint_false():
    assert any_overlap(["ui/cart.tsx"], ["payment/", "api/order.ts"]) is False


def test_any_overlap_intersecting_true():
    assert any_overlap(["payment/refund.ts"], ["payment/", "api/order.ts"]) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paths'`

- [ ] **Step 3: Write minimal implementation**

`scripts/paths.py`:
```python
from __future__ import annotations

from typing import Iterable


def normalize(p: str) -> str:
    """경로를 비교 가능한 형태로 정규화: 양끝 공백·슬래시 제거."""
    return p.strip().strip("/")


def overlaps(a: str, b: str) -> bool:
    """두 경로가 같은 영역을 가리키면 True.

    겹침 = 동일하거나, 한쪽이 다른 쪽의 디렉터리 조상.
    'payment'와 'payment2'처럼 단순 문자열 접두는 겹치지 않는다.
    """
    a, b = normalize(a), normalize(b)
    if a == b:
        return True
    return b.startswith(a + "/") or a.startswith(b + "/")


def any_overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    """두 touches 집합이 하나라도 겹치면 True."""
    bs = [normalize(x) for x in b]
    return any(overlaps(x, y) for x in a for y in bs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_paths.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/paths.py tests/test_paths.py
git commit -m "feat: path overlap primitive for touches conflict detection"
```

---

## Task 3: `config.py` — 설정 로드

**Files:**
- Create: `scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import json

from config import load_config


def test_defaults_when_no_file(root):
    cfg = load_config(root)
    assert cfg.max_active == 4
    assert cfg.stale_minutes == 30
    assert cfg.test_command == "pytest"
    assert cfg.main_branch == "main"
    assert cfg.worktree_parent is None


def test_config_json_overrides_defaults(root):
    (root / "backlog" / "config.json").write_text(
        json.dumps({"max_active": 8, "test_command": "true"})
    )
    cfg = load_config(root)
    assert cfg.max_active == 8
    assert cfg.test_command == "true"
    # 지정 안 한 값은 기본 유지
    assert cfg.main_branch == "main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write minimal implementation**

`scripts/config.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "max_active": 4,
    "stale_minutes": 30,
    "test_command": "pytest",
    "main_branch": "main",
    "worktree_parent": None,  # None → root.parent 사용
}


@dataclass
class Config:
    max_active: int = 4
    stale_minutes: int = 30
    test_command: str = "pytest"
    main_branch: str = "main"
    worktree_parent: str | None = None


def load_config(root) -> Config:
    path = Path(root) / "backlog" / "config.json"
    data = dict(DEFAULTS)
    if path.exists():
        data.update(json.loads(path.read_text()))
    return Config(**{k: data[k] for k in DEFAULTS})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/config.py tests/test_config.py
git commit -m "feat: config loader with defaults and config.json override"
```

---

## Task 4: `backlog.py` — 작업 레코드 생성·조회·목록

**Files:**
- Create: `scripts/backlog.py`
- Test: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

`tests/test_backlog.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backlog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backlog'`

- [ ] **Step 3: Write minimal implementation**

`scripts/backlog.py`:
```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STATUSES = ["inbox", "ready", "active", "integrating", "done"]
DIRS = ["inbox", "ready", "active", "done"]


def dir_for_status(status: str) -> str:
    """integrating은 active/ 디렉터리를 공유한다. 그 외는 동명 디렉터리."""
    return "active" if status == "integrating" else status


class Backlog:
    def __init__(self, root):
        self.root = Path(root)
        self.base = self.root / "backlog"

    def init(self) -> None:
        for d in DIRS:
            (self.base / d).mkdir(parents=True, exist_ok=True)

    def next_id(self) -> str:
        nums = []
        for d in DIRS:
            for f in (self.base / d).glob("T-*.json"):
                m = re.match(r"T-(\d+)\.json$", f.name)
                if m:
                    nums.append(int(m.group(1)))
        n = (max(nums) + 1) if nums else 1
        return f"T-{n:03d}"

    def path_of(self, task_id: str) -> Path:
        for d in DIRS:
            p = self.base / d / f"{task_id}.json"
            if p.exists():
                return p
        raise KeyError(task_id)

    def _write(self, path: Path, task: dict[str, Any]) -> None:
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")

    def add(self, title: str, type: str = "feature",
            source: str = "human", priority: str = "medium") -> str:
        task_id = self.next_id()
        task = {
            "id": task_id, "title": title, "type": type,
            "source": source, "touches": [], "depends_on": [],
            "status": "inbox", "priority": priority,
            "auto": False, "worktree": None,
        }
        self._write(self.base / "inbox" / f"{task_id}.json", task)
        return task_id

    def get(self, task_id: str) -> dict[str, Any]:
        return json.loads(self.path_of(task_id).read_text())

    def save(self, task: dict[str, Any]) -> None:
        self._write(self.path_of(task["id"]), task)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        out = []
        for d in DIRS:
            for f in sorted((self.base / d).glob("T-*.json")):
                t = json.loads(f.read_text())
                if status is None or t["status"] == status:
                    out.append(t)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backlog.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog store - add, get, list, id generation"
```

---

## Task 5: `backlog.py` — 상태 전이 (`set_fields`, `move`, `classify`)

**Files:**
- Modify: `scripts/backlog.py` (add methods to `Backlog`)
- Test: `tests/test_backlog.py` (append)

- [ ] **Step 1: Write the failing test (append to test_backlog.py)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backlog.py -k "set_fields or move or integrating or classify" -v`
Expected: FAIL with `AttributeError: 'Backlog' object has no attribute 'set_fields'`

- [ ] **Step 3: Write minimal implementation (append methods to `Backlog`)**

```python
    def set_fields(self, task_id: str, **fields) -> dict[str, Any]:
        task = self.get(task_id)
        task.update(fields)
        self.save(task)
        return task

    def move(self, task_id: str, to_status: str) -> dict[str, Any]:
        if to_status not in STATUSES:
            raise ValueError(f"bad status: {to_status}")
        src = self.path_of(task_id)
        task = json.loads(src.read_text())
        task["status"] = to_status
        dst = self.base / dir_for_status(to_status) / src.name
        self._write(dst, task)
        if dst != src:
            src.unlink()
        return task

    def classify(self, task_id: str, touches, depends_on=None,
                 auto: bool = False) -> dict[str, Any]:
        self.set_fields(task_id, touches=list(touches),
                        depends_on=list(depends_on or []), auto=auto)
        return self.move(task_id, "ready")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backlog.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog state transitions - set_fields, move, classify"
```

---

## Task 6: `lease.py` — 리스 테이블 + 충돌 게이트

**Files:**
- Create: `scripts/lease.py`
- Test: `tests/test_lease.py`

- [ ] **Step 1: Write the failing test**

`tests/test_lease.py`:
```python
import pytest

from lease import LeaseTable, LeaseConflict


def test_acquire_and_active(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    active = lt.active()
    assert len(active) == 1
    assert active[0]["task"] == "T-001"
    assert active[0]["worktree"] == "/tmp/wt-1"
    assert "heartbeat" in active[0]


def test_acquire_conflicting_touches_raises(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    with pytest.raises(LeaseConflict):
        lt.acquire("T-002", ["payment/refund.ts"], "/tmp/wt-2")


def test_disjoint_touches_coexist(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    lt.acquire("T-002", ["ui/cart.tsx"], "/tmp/wt-2")
    assert len(lt.active()) == 2


def test_conflicts_lists_overlapping(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    hits = lt.conflicts(["payment/refund.ts"])
    assert [h["task"] for h in hits] == ["T-001"]
    assert lt.conflicts(["ui/cart.tsx"]) == []


def test_release_removes_lease(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    lt.release("T-001")
    assert lt.active() == []


def test_heartbeat_updates_timestamp(root):
    lt = LeaseTable(root)
    lt.acquire("T-001", ["payment/"], "/tmp/wt-1")
    before = lt.get("T-001")["heartbeat"]
    # 타임스탬프를 과거로 강제 후 heartbeat가 갱신하는지 확인
    leases = lt.load()
    leases[0]["heartbeat"] = "2000-01-01T00:00:00+00:00"
    lt._save(leases)
    lt.heartbeat("T-001")
    after = lt.get("T-001")["heartbeat"]
    assert after != "2000-01-01T00:00:00+00:00"
    assert after >= before[:4]  # 단순 sanity (현재연도 ISO)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lease.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lease'`

- [ ] **Step 3: Write minimal implementation**

`scripts/lease.py`:
```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import any_overlap


class LeaseConflict(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeaseTable:
    def __init__(self, root):
        self.path = Path(root) / "backlog" / "LEASES.json"

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text()).get("leases", [])

    def _save(self, leases: list[dict[str, Any]]) -> None:
        self.path.write_text(
            json.dumps({"leases": leases}, ensure_ascii=False, indent=2) + "\n"
        )

    def active(self) -> list[dict[str, Any]]:
        return self.load()

    def get(self, task_id: str) -> dict[str, Any] | None:
        for lease in self.load():
            if lease["task"] == task_id:
                return lease
        return None

    def conflicts(self, touches) -> list[dict[str, Any]]:
        return [l for l in self.load() if any_overlap(touches, l["touches"])]

    def acquire(self, task_id: str, touches, worktree: str) -> dict[str, Any]:
        leases = self.load()
        for lease in leases:
            if lease["task"] != task_id and any_overlap(touches, lease["touches"]):
                raise LeaseConflict(
                    f"{task_id} touches conflict with {lease['task']}"
                )
        leases = [l for l in leases if l["task"] != task_id]
        lease = {
            "task": task_id, "touches": list(touches),
            "worktree": worktree, "heartbeat": _now(),
        }
        leases.append(lease)
        self._save(leases)
        return lease

    def release(self, task_id: str) -> None:
        self._save([l for l in self.load() if l["task"] != task_id])

    def heartbeat(self, task_id: str) -> None:
        leases = self.load()
        for lease in leases:
            if lease["task"] == task_id:
                lease["heartbeat"] = _now()
        self._save(leases)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_lease.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/lease.py tests/test_lease.py
git commit -m "feat: lease table with touches-based conflict gate"
```

---

## Task 7: `dispatch.py` — `can_dispatch` (순수 투입 판정)

**Files:**
- Create: `scripts/dispatch.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

`tests/test_dispatch.py`:
```python
from backlog import Backlog
from lease import LeaseTable
from config import load_config
from dispatch import can_dispatch


def _ready_task(bl, title="t", touches=None, depends_on=None):
    tid = bl.add(title)
    bl.classify(tid, touches=touches or [], depends_on=depends_on or [])
    return bl.get(tid)


def test_can_dispatch_ok(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    task = _ready_task(bl, touches=["ui/"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is True
    assert reason == "ok"


def test_not_ready_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    tid = bl.add("t")  # still inbox
    ok, reason = can_dispatch(bl, lt, cfg, bl.get(tid))
    assert ok is False
    assert "ready" in reason


def test_unfinished_dependency_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    dep = bl.add("dep")  # inbox, not done
    task = _ready_task(bl, depends_on=[dep])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert dep in reason


def test_done_dependency_allows(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    dep = bl.add("dep")
    bl.move(dep, "done")
    task = _ready_task(bl, depends_on=[dep])
    ok, _ = can_dispatch(bl, lt, cfg, task)
    assert ok is True


def test_lease_conflict_blocks(root):
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    lt.acquire("T-099", ["payment/"], "/tmp/wt")
    task = _ready_task(bl, touches=["payment/refund.ts"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert "conflict" in reason


def test_max_active_ceiling_blocks(root):
    import json
    (root / "backlog" / "config.json").write_text(json.dumps({"max_active": 1}))
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    lt.acquire("T-099", ["other/"], "/tmp/wt")
    task = _ready_task(bl, touches=["ui/"])
    ok, reason = can_dispatch(bl, lt, cfg, task)
    assert ok is False
    assert "max_active" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dispatch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dispatch'`

- [ ] **Step 3: Write minimal implementation**

`scripts/dispatch.py`:
```python
from __future__ import annotations

import subprocess
from pathlib import Path

from backlog import Backlog
from config import Config, load_config
from lease import LeaseTable
from paths import any_overlap


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def can_dispatch(backlog: Backlog, leases: LeaseTable, config: Config,
                 task: dict) -> tuple[bool, str]:
    if task["status"] != "ready":
        return False, f"status is {task['status']}, not ready"
    for dep in task.get("depends_on", []):
        try:
            d = backlog.get(dep)
        except KeyError:
            return False, f"dependency {dep} not found"
        if d["status"] != "done":
            return False, f"dependency {dep} not done ({d['status']})"
    active = leases.active()
    occupied = [t for lease in active for t in lease["touches"]]
    if any_overlap(task["touches"], occupied):
        return False, "touches conflict with active lease"
    if len(active) >= config.max_active:
        return False, f"max_active {config.max_active} reached"
    return True, "ok"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dispatch.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/dispatch.py tests/test_dispatch.py
git commit -m "feat: can_dispatch gate - status, deps, lease conflict, ceiling"
```

---

## Task 8: `dispatch.py` — `dispatch` + `dispatch_auto` (worktree 생성)

**Files:**
- Modify: `scripts/dispatch.py` (add `worktree_path`, `dispatch`, `dispatch_auto`)
- Test: `tests/test_dispatch.py` (append)

- [ ] **Step 1: Write the failing test (append to test_dispatch.py)**

```python
import pytest


def _ready(bl, title="t", touches=None, auto=False):
    tid = bl.add(title)
    bl.classify(tid, touches=touches or [], auto=auto)
    return tid


def test_dispatch_creates_worktree_and_lease(git_root):
    from dispatch import dispatch
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    tid = _ready(bl, touches=["ui/"])
    wt = dispatch(git_root, tid)
    assert Path(wt).exists()
    assert bl.get(tid)["status"] == "active"
    assert bl.get(tid)["worktree"] == str(wt)
    assert lt.get(tid)["task"] == tid


def test_dispatch_conflicting_raises(git_root):
    from dispatch import dispatch
    bl, lt = Backlog(git_root), LeaseTable(git_root)
    lt.acquire("T-099", ["payment/"], "/tmp/wt")
    tid = _ready(bl, touches=["payment/refund.ts"])
    with pytest.raises(RuntimeError):
        dispatch(git_root, tid)


def test_dispatch_auto_only_auto_and_nonconflicting(git_root):
    from dispatch import dispatch_auto
    bl = Backlog(git_root)
    a = _ready(bl, "auto-ok", touches=["ui/"], auto=True)
    _ready(bl, "manual", touches=["api/"], auto=False)   # auto=False → skip
    dispatched = dispatch_auto(git_root)
    assert dispatched == [a]
    assert bl.get(a)["status"] == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dispatch.py -k "worktree or conflicting_raises or dispatch_auto" -v`
Expected: FAIL with `ImportError: cannot import name 'dispatch' from 'dispatch'`

- [ ] **Step 3: Write minimal implementation (append to `dispatch.py`)**

```python
def worktree_path(root, config: Config, task_id: str) -> Path:
    root = Path(root)
    parent = Path(config.worktree_parent) if config.worktree_parent else root.parent
    return parent / f"{root.name}-{task_id}"


def dispatch(root, task_id: str) -> Path:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    task = backlog.get(task_id)
    ok, reason = can_dispatch(backlog, leases, config, task)
    if not ok:
        raise RuntimeError(f"cannot dispatch {task_id}: {reason}")
    wt = worktree_path(root, config, task_id)
    branch = f"cwo/{task_id}"
    r = _git(root, "worktree", "add", str(wt), "-b", branch, config.main_branch)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {r.stderr.strip()}")
    leases.acquire(task_id, task["touches"], str(wt))
    backlog.set_fields(task_id, worktree=str(wt))
    backlog.move(task_id, "active")
    return wt


def dispatch_auto(root) -> list[str]:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    dispatched = []
    for task in backlog.list("ready"):
        if not task.get("auto"):
            continue
        ok, _ = can_dispatch(backlog, leases, config, task)
        if ok:
            dispatch(root, task["id"])
            dispatched.append(task["id"])
    return dispatched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dispatch.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/dispatch.py tests/test_dispatch.py
git commit -m "feat: dispatch with git worktree + auto-dispatch of independent tasks"
```

---

## Task 9: `integrate.py` — 통합 게이트 (테스트→머지→리스 반납→done)

**Files:**
- Create: `scripts/integrate.py`
- Test: `tests/test_integrate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_integrate.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_integrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrate'`

- [ ] **Step 3: Write minimal implementation**

`scripts/integrate.py`:
```python
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def integrate(root, task_id: str) -> dict:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    task = backlog.get(task_id)
    if task["status"] not in ("active", "integrating"):
        return {"ok": False, "reason": f"status {task['status']} not active"}
    wt = task.get("worktree")
    if not wt or not Path(wt).exists():
        return {"ok": False, "reason": "worktree missing"}

    backlog.move(task_id, "integrating")

    # 1. 테스트
    test = subprocess.run(
        shlex.split(config.test_command), cwd=wt, capture_output=True, text=True
    )
    if test.returncode != 0:
        backlog.move(task_id, "active")
        return {"ok": False, "reason": "tests failed",
                "output": test.stdout + test.stderr}

    # 2. 머지
    branch = f"cwo/{task_id}"
    _git(root, "checkout", config.main_branch)
    m = _git(root, "merge", "--no-ff", branch, "-m",
             f"merge {task_id}: {task['title']}")
    if m.returncode != 0:
        _git(root, "merge", "--abort")
        backlog.move(task_id, "active")
        return {"ok": False, "reason": "merge conflict",
                "output": m.stdout + m.stderr}

    # 3. 리스 반납 + done + 정리
    leases.release(task_id)
    _git(root, "worktree", "remove", str(wt), "--force")
    _git(root, "branch", "-d", branch)
    backlog.set_fields(task_id, worktree=None)
    backlog.move(task_id, "done")
    return {"ok": True, "task": task_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_integrate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/integrate.py tests/test_integrate.py
git commit -m "feat: integration gate - test, merge, release lease, mark done"
```

---

## Task 10: `cwo_gc.py` — 고아 리스 회수

**Files:**
- Create: `scripts/cwo_gc.py`
- Test: `tests/test_gc.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gc.py`:
```python
import json

from backlog import Backlog
from lease import LeaseTable
from cwo_gc import gc


def _active_with_lease(root, worktree):
    """active 상태 작업 + 그에 대한 리스를 만든다."""
    bl, lt = Backlog(root), LeaseTable(root)
    tid = bl.add("t")
    bl.classify(tid, touches=["x/"])
    bl.set_fields(tid, worktree=worktree)
    bl.move(tid, "active")
    lt.acquire(tid, ["x/"], worktree)
    return tid


def test_gc_reclaims_missing_worktree(root):
    bl, lt = Backlog(root), LeaseTable(root)
    tid = _active_with_lease(root, "/nonexistent/wt")
    reclaimed = gc(root)
    assert [r["task"] for r in reclaimed] == [tid]
    assert reclaimed[0]["reason"] == "missing-worktree"
    assert lt.get(tid) is None                  # 리스 회수
    assert bl.get(tid)["status"] == "ready"     # 재투입 대기로 되돌림
    assert bl.get(tid)["worktree"] is None


def test_gc_reclaims_stale_heartbeat(root, tmp_path):
    wt = tmp_path / "live-wt"
    wt.mkdir()
    bl, lt = Backlog(root), LeaseTable(root)
    tid = _active_with_lease(root, str(wt))
    # heartbeat를 과거로 강제
    leases = lt.load()
    leases[0]["heartbeat"] = "2000-01-01T00:00:00+00:00"
    lt._save(leases)
    reclaimed = gc(root)
    assert [r["task"] for r in reclaimed] == [tid]
    assert reclaimed[0]["reason"] == "stale"


def test_gc_keeps_fresh_lease(root, tmp_path):
    wt = tmp_path / "live-wt"
    wt.mkdir()
    tid = _active_with_lease(root, str(wt))
    reclaimed = gc(root)
    assert reclaimed == []
    assert LeaseTable(root).get(tid) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cwo_gc'`

- [ ] **Step 3: Write minimal implementation**

`scripts/cwo_gc.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _age_minutes(iso: str) -> float:
    t = datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 60.0


def gc(root) -> list[dict]:
    root = Path(root)
    backlog, leases, config = Backlog(root), LeaseTable(root), load_config(root)
    reclaimed = []
    for lease in list(leases.active()):
        wt = lease.get("worktree")
        missing = not (wt and Path(wt).exists())
        stale = _age_minutes(lease["heartbeat"]) > config.stale_minutes
        if not (missing or stale):
            continue
        leases.release(lease["task"])
        try:
            task = backlog.get(lease["task"])
            if task["status"] in ("active", "integrating"):
                backlog.set_fields(lease["task"], worktree=None)
                backlog.move(lease["task"], "ready")
        except KeyError:
            pass
        reclaimed.append({
            "task": lease["task"],
            "reason": "missing-worktree" if missing else "stale",
        })
    return reclaimed
```

> 주의: `missing`을 `stale`보다 먼저 판정해 reason을 정한다 (worktree가 없으면 heartbeat 무관하게 missing-worktree).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gc.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/cwo_gc.py tests/test_gc.py
git commit -m "feat: gc reclaims orphan leases (missing worktree / stale heartbeat)"
```

---

## Task 11: `cwo.py` — CLI 엔트리

**Files:**
- Create: `scripts/cwo.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cwo'`

- [ ] **Step 3: Write minimal implementation**

`scripts/cwo.py`:
```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cwo_gc as gc_mod
import dispatch as dispatch_mod
import integrate as integrate_mod
from backlog import Backlog
from config import load_config
from lease import LeaseTable


def _root(args) -> Path:
    return Path(args.root).resolve()


def cmd_init(args):
    Backlog(_root(args)).init()
    print(f"initialized backlog at {_root(args) / 'backlog'}")


def cmd_add(args):
    tid = Backlog(_root(args)).add(
        args.title, type=args.type, source=args.source, priority=args.priority
    )
    print(tid)


def cmd_classify(args):
    Backlog(_root(args)).classify(
        args.id, touches=args.touches or [],
        depends_on=args.depends_on or [], auto=args.auto,
    )
    print(f"{args.id} -> ready")


def cmd_list(args):
    for t in Backlog(_root(args)).list(args.status):
        dep = f" deps={t['depends_on']}" if t["depends_on"] else ""
        print(f"{t['id']} [{t['status']}] {t['title']} touches={t['touches']}{dep}")


def cmd_leases(args):
    for l in LeaseTable(_root(args)).active():
        print(f"{l['task']} touches={l['touches']} wt={l['worktree']}")


def cmd_check(args):
    root = _root(args)
    bl, lt, cfg = Backlog(root), LeaseTable(root), load_config(root)
    ok, reason = dispatch_mod.can_dispatch(bl, lt, cfg, bl.get(args.id))
    print(f"{'OK' if ok else 'NO'}: {reason}")
    sys.exit(0 if ok else 1)


def cmd_dispatch(args):
    wt = dispatch_mod.dispatch(_root(args), args.id)
    print(f"{args.id} -> active @ {wt}")


def cmd_dispatch_auto(args):
    ids = dispatch_mod.dispatch_auto(_root(args))
    print("dispatched: " + (", ".join(ids) if ids else "(none)"))


def cmd_integrate(args):
    res = integrate_mod.integrate(_root(args), args.id)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)


def cmd_gc(args):
    rec = gc_mod.gc(_root(args))
    print("reclaimed: " + (", ".join(r["task"] for r in rec) if rec else "(none)"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cwo", description="Claude Work Orchestrator")
    p.add_argument("--root", default=".", help="project root containing backlog/")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--type", default="feature")
    a.add_argument("--source", default="human")
    a.add_argument("--priority", default="medium")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("classify")
    c.add_argument("id")
    c.add_argument("--touches", nargs="*")
    c.add_argument("--depends-on", dest="depends_on", nargs="*")
    c.add_argument("--auto", action="store_true")
    c.set_defaults(func=cmd_classify)

    ls = sub.add_parser("list")
    ls.add_argument("--status")
    ls.set_defaults(func=cmd_list)

    sub.add_parser("leases").set_defaults(func=cmd_leases)

    ch = sub.add_parser("check")
    ch.add_argument("id")
    ch.set_defaults(func=cmd_check)

    d = sub.add_parser("dispatch")
    d.add_argument("id")
    d.set_defaults(func=cmd_dispatch)

    sub.add_parser("dispatch-auto").set_defaults(func=cmd_dispatch_auto)

    i = sub.add_parser("integrate")
    i.add_argument("id")
    i.set_defaults(func=cmd_integrate)

    sub.add_parser("gc").set_defaults(func=cmd_gc)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: ALL PASS (paths 6, config 2, backlog 9, lease 6, dispatch 9, integrate 2, gc 3, cli 3)

- [ ] **Step 6: Commit**

```bash
git add scripts/cwo.py tests/test_cli.py
git commit -m "feat: cwo CLI - init, add, classify, list, leases, check, dispatch, integrate, gc"
```

---

## Task 12: `SKILL.md` — 프로토콜 문서

**Files:**
- Create: `SKILL.md`

이 문서가 Claude에게 "언제·어떻게 cwo를 쓰는가"를 알려준다. 코드(결정론)는 scripts가, 판단(트리아지·자동투입 정책)은 이 문서가 담당한다. 본문 500줄 이내.

- [ ] **Step 1: Write `SKILL.md`**

`SKILL.md`:
````markdown
---
name: claude-work-orchestrator
description: >
  한 프로젝트에서 수시로 발생하는 요구사항·버그·이슈를 충돌 없이 병렬 처리하는
  동시작업 오케스트레이터. 파일 백로그에 등록하고, 영향범위 리스로 충돌을 막고,
  비충돌·독립 작업만 git worktree로 투입한다. csm이 세션을 보면 cwo는 작업을
  관리한다. Use when: 한 프로젝트에 동시에 여러 작업/이슈가 쌓일 때, 작업을
  병렬로 안전하게 돌리고 싶을 때, worktree·백로그·작업 큐 관리, `cwo` 명령.
  Triggers — KO: 동시작업, 병렬 작업, 작업 큐, 백로그, 작업 등록, 충돌 없이,
  워크트리 관리, 작업 디스패치. EN: cwo, work orchestrator, backlog, parallel
  tasks, dispatch, worktree management, work queue, concurrent work.
---

# Claude Work Orchestrator (`cwo`)

한 프로젝트에서 작업을 **등록(capture)** 과 **투입(dispatch)** 으로 분리하고,
**영향범위 리스(lease)** 로 충돌을 구조적으로 차단하는 동시작업 엔진.

## When to use

- 한 프로젝트에 요구사항·버그·이슈가 동시다발로 쌓일 때.
- 여러 작업을 병렬로 돌리되 파일/머지 충돌은 피하고 싶을 때.
- 사용자가 `cwo`를 언급하거나 작업 큐/백로그/worktree 관리를 요청할 때.

세션 자체의 관측(어떤 터미널이 살아있나)은 **csm**의 역할. cwo는 *작업*을 다룬다.

## Core loop

```
등록 → 분류 → 투입(리스 게이트) → 실행(worktree) → 통합(테스트·머지) → done
                                       │
                          발견된 새 작업은 inbox로 되먹임
```

## Command reference

스크립트 경로: `scripts/cwo.py`. `--root`는 backlog/가 있는 프로젝트 루트(기본 `.`).

```bash
python scripts/cwo.py --root <PROJ> init                 # backlog/ 초기화
python scripts/cwo.py --root <PROJ> add "<제목>" --type bug --priority high
python scripts/cwo.py --root <PROJ> classify T-001 --touches payment/ api/order.ts --depends-on T-000 [--auto]
python scripts/cwo.py --root <PROJ> list [--status ready]
python scripts/cwo.py --root <PROJ> leases               # 활성 리스(점유 현황)
python scripts/cwo.py --root <PROJ> check T-001          # 투입 가능 판정 (exit 0/1)
python scripts/cwo.py --root <PROJ> dispatch T-001       # worktree 생성·리스 획득·active
python scripts/cwo.py --root <PROJ> dispatch-auto        # auto=true·비충돌 작업 일괄 투입
python scripts/cwo.py --root <PROJ> integrate T-001      # 테스트→머지→리스 반납→done
python scripts/cwo.py --root <PROJ> gc                   # 고아 리스 회수
```

## 분류(triage) 결정 트리 — 발견된 작업을 어디로

active 작업 중 새 이슈를 발견하면, **즉시 처리하지 말고** 먼저 분류한다:

```
새 이슈 발견
 ├─ 지금 작업 완료에 꼭 필요(Blocking)? → 현재 worktree에서, 별도 커밋
 ├─ 같은 영역·작고·저위험?              → 애매하면 백로그로 ("하는 김에"는 함정)
 └─ 관련 없는 다른 영역?                → 무조건 백로그(add), 현재 브랜치에 안 섞음
```

백로그로 회수할 때 `source`에 발견 위치를 남긴다: `add ... --source "discovered(from: T-038)"`.

## 분류 시 `touches`/`depends_on` 채우기 (Claude의 역할)

- **`touches`**: 이 작업이 건드릴 영역. **기본 입도는 디렉터리/모듈** (거칠게 잡아 거짓 병렬 방지). 코드베이스를 보고 초안을 만들고, 사람 승인을 받는다.
- **`depends_on`**: 선행 작업 id. 순환이 생기지 않게 한다.

## 자동 투입 정책 (하이브리드)

Claude가 **사람 승인 없이** 투입해도 되는 조건 (모두 충족 시):
1. `status == ready` (사람이 분류 승인)
2. `touches`가 모든 활성 리스와 비겹침
3. `depends_on` 전부 `done`
4. `auto == true`

이 외에는 사람 승인 후 `dispatch`. 위험한 작업(광범위 touches, 마이그레이션 등)은 `auto`를 켜지 않는다. → 미래에 `auto` 기본값을 올리면 완전자동으로 전환.

## 동시 작업 수

충돌 안전성은 리스가 보장한다. 동시 수는 "안전 한계"가 아니라 "수익 체감 지점":
모듈성·공유 초크포인트·머지 대역폭·머신 자원·사람 검토의 최솟값. 하이브리드는
보통 2~4(`config.max_active`, 기본 4). 늘리는 진짜 레버는 코드 모듈성.

## 통합 후 / 정리

- `integrate`가 테스트 통과 시 머지하고 리스를 반납한다. 테스트 실패·머지 충돌이면 작업을 `active`로 되돌리고 사람 개입을 요청한다.
- 세션이 죽어 worktree가 사라지거나 heartbeat가 오래되면 `gc`가 리스를 회수하고 작업을 `ready`로 되돌린다.

## 설정 (`backlog/config.json`, 선택)

```json
{
  "max_active": 4,
  "stale_minutes": 30,
  "test_command": "pytest",
  "main_branch": "main",
  "worktree_parent": null
}
```
````

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "docs: SKILL.md protocol - triage tree, auto-dispatch policy, command reference"
```

---

## Self-Review (작성 후 점검 결과)

**1. Spec coverage** — design.md 각 절을 task에 매핑:
- 등록/투입 분리 → backlog(Task 4·5) + dispatch(Task 7·8) ✅
- 영향범위 리스 → paths(Task 2) + lease(Task 6) ✅
- 상태 머신(integrating=active 공유) → Task 5 `move`/`dir_for_status` ✅
- 하이브리드 디스패치 + 자동투입 조건 → Task 8 `dispatch_auto` + SKILL.md 정책 ✅
- 통합 게이트(테스트·머지·반납) → Task 9 ✅
- GC/고아 리스 → Task 10 ✅
- 동시성 천장(max_active) → Task 7 ✅
- Classifier(touches/deps 초안) → SKILL.md(판단) + Task 5 `classify`(저장) ✅
- 되먹임 루프(발견작업 inbox) → SKILL.md 트리아지 트리 + `add --source` ✅
- full-test-orchestrator 연계 → `config.test_command`로 임의 테스트 명령 주입 가능(기본 pytest) ✅
- 인터페이스 분리(미래 웹UI/자동) → backlog 파일계약 + can_dispatch 정책 분리 ✅

**2. Placeholder scan** — "TBD/TODO/적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함. ✅

**3. Type consistency** — 함수 시그니처 교차 확인:
- `Backlog`: init/next_id/path_of/add/get/save/list/set_fields/move/classify — Task 4·5에서 정의, Task 7~11에서 동일 사용 ✅
- `LeaseTable`: load/_save/active/get/conflicts/acquire/release/heartbeat — Task 6 정의, 이후 동일 ✅
- `can_dispatch(backlog, leases, config, task)` — Task 7 정의, Task 8·11 동일 호출 ✅
- `dispatch(root, task_id)` / `dispatch_auto(root)` — Task 8 정의, Task 11 동일 ✅
- `integrate(root, task_id)` → dict{ok,...} — Task 9 정의, Task 11 동일 ✅
- `gc(root)` → list[dict{task,reason}] — Task 10 정의, Task 11 동일 ✅
- `load_config(root)` → Config — Task 3 정의, 이후 동일 ✅

불일치 없음.
