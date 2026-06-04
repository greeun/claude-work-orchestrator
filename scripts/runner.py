from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backlog import Backlog
from dispatch import dispatch_auto, loop_status
from integrate import integrate
from lock import project_lock


def run_loop(root, executor=None, *, max_iters: int = 50,
             dry_run: bool = False, log=lambda m: None) -> dict:
    """자율 실행 루프. executor(task: dict, worktree: str) -> bool.

    안전장치: executor 미지정+비 dry_run이면 거부. max_iters 상한.
    각 active 작업은 한 번만 실행(종료 보장). dry_run은 미변경 미리보기.
    """
    root = Path(root)
    if not dry_run and executor is None:
        raise ValueError("executor required (or use dry_run=True)")

    if dry_run:
        status = loop_status(root)
        log(f"[dry-run] dispatchable={status['dispatchable']} "
            f"active={[a['id'] for a in status['active']]} "
            f"blocked={[b['id'] for b in status['blocked_auto']]} "
            f"needs_approval={status['needs_approval']}")
        return {"dry_run": True, "status": status}

    done: list[str] = []
    failed: list[str] = []
    executed: set[str] = set()
    iters = 0

    while iters < max_iters:
        status = loop_status(root)
        if not status["loop_can_progress"]:
            break
        with project_lock(root):
            newly = dispatch_auto(root)
        for tid in newly:
            log(f"dispatched {tid}")
        active = [a for a in loop_status(root)["active"]
                  if a["id"] not in executed and a["worktree"]]
        if not newly and not active:
            log("no progress possible; stopping")
            break
        iters += 1
        for a in active:
            tid, wt = a["id"], a["worktree"]
            executed.add(tid)
            task = Backlog(root).get(tid)
            log(f"executing {tid} in {wt}")
            try:
                ok = bool(executor(task, wt))
            except Exception as e:  # executor blew up
                ok = False
                log(f"executor raised for {tid}: {e}")
            if not ok:
                failed.append(tid)
                log(f"executor failed for {tid}; leaving active")
                continue
            res = integrate(root, tid)
            if res.get("ok"):
                done.append(tid)
                log(f"integrated {tid}")
            else:
                failed.append(tid)
                log(f"integrate failed for {tid}: {res.get('reason')}")

    final = loop_status(root)
    return {
        "iterations": iters,
        "done": done,
        "failed": failed,
        "needs_approval": final["needs_approval"],
        "blocked": [b["id"] for b in final["blocked_auto"]],
    }


def command_executor(template: str):
    """셸 명령 템플릿으로 executor 생성.

    프롬프트(사용자 콘텐츠)는 셸에 보간하지 않고 환경변수로 전달(인젝션 방지):
      $CWO_PROMPT, $CWO_TASK_ID, $CWO_WORKTREE
    {id}/{worktree}만 템플릿에 치환(통제된 값). 예: 'claude -p "$CWO_PROMPT"'
    """
    def _exec(task, worktree) -> bool:
        cmd = template.format(id=task["id"], worktree=worktree)
        env = {**os.environ,
               "CWO_PROMPT": task.get("title", ""),
               "CWO_TASK_ID": task["id"],
               "CWO_WORKTREE": str(worktree)}
        r = subprocess.run(cmd, shell=True, cwd=worktree, env=env)
        return r.returncode == 0
    return _exec
