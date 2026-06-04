from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path


class LockTimeout(Exception):
    pass


@contextmanager
def project_lock(root, timeout: float = 10.0, poll: float = 0.05):
    """backlog/.lock에 대한 배타적 flock. timeout 초과 시 LockTimeout."""
    lock_path = Path(root) / "backlog" / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"could not acquire lock within {timeout}s")
                time.sleep(poll)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
