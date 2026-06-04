import fcntl

import pytest

from lock import project_lock, LockTimeout


def test_acquire_when_free(root):
    with project_lock(root, timeout=1):
        pass  # must not raise


def test_times_out_when_already_held(root):
    lp = root / "backlog" / ".lock"
    lp.parent.mkdir(parents=True, exist_ok=True)
    holder = open(lp, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(LockTimeout):
            with project_lock(root, timeout=0.2):
                pass
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_lock_released_after_block(root):
    # after the with-block exits, the lock is free to take again
    with project_lock(root, timeout=1):
        pass
    with project_lock(root, timeout=1):
        pass
