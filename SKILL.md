---
name: claude-work-orchestrator
version: 1.0.0
description: >
  A concurrent-work orchestrator that runs the requirements, bugs, and issues
  that keep cropping up in a single project in parallel, without conflicts.
  It captures work into a file backlog, blocks conflicts with ownership leases
  over the affected code regions, and dispatches only non-conflicting,
  independent work into git worktrees. Where csm watches sessions, cwo manages
  work. Use when: several tasks/issues pile up in one project at once, you want
  to run work in parallel safely, or for worktree · backlog · work-queue
  management and the `cwo` command.
  Triggers — KO: 동시작업, 병렬 작업, 작업 큐, 백로그, 작업 등록, 충돌 없이,
  워크트리 관리, 작업 디스패치. EN: cwo, work orchestrator, backlog, parallel
  tasks, dispatch, worktree management, work queue, concurrent work.
---

# Claude Work Orchestrator (`cwo`)

A concurrent-work engine that, within a single project, splits work into
**capture** and **dispatch**, and structurally blocks conflicts with an
**ownership lease (lease)** over the affected code region.

## When to use

- When requirements · bugs · issues pile up simultaneously in one project.
- When you want to run several tasks in parallel but avoid file/merge conflicts.
- When the user mentions `cwo` or asks for work-queue / backlog / worktree management.

Observing the sessions themselves (which terminal is alive) is **csm**'s job. cwo deals with *work*.

## Setup note

If the target project is a git repo, be sure to `.gitignore` build/test artifacts (`__pycache__/`, `*.pyc`, `.pytest_cache/`, etc.). Otherwise the artifacts created by the integration gate's `test_command` can break worktree merges. `cwo init` warns when there is no `.gitignore`.

## Core loop

```
capture → classify → dispatch (lease gate) → execute (worktree) → integrate (test · merge) → done
                                       │
                          newly discovered work feeds back into the inbox
```

## Command reference

Script path: `scripts/cwo.py`. `--root` is the project root that holds backlog/ (default `.`).

```bash
python scripts/cwo.py --root <PROJ> init                 # initialize backlog/
python scripts/cwo.py --root <PROJ> add "<title>" --type bug --priority high
python scripts/cwo.py --root <PROJ> classify T-001 --touches payment/ api/order.ts --depends-on T-000 [--auto]
python scripts/cwo.py --root <PROJ> list [--status ready]
python scripts/cwo.py --root <PROJ> leases               # active leases (occupied regions)
python scripts/cwo.py --root <PROJ> check T-001          # dispatchable? (exit 0/1)
python scripts/cwo.py --root <PROJ> dispatch T-001       # create worktree · acquire lease · active
python scripts/cwo.py --root <PROJ> dispatch-auto        # bulk-dispatch auto=true · non-conflicting tasks
python scripts/cwo.py --root <PROJ> integrate T-001      # test → merge → release lease → done
python scripts/cwo.py --root <PROJ> gc                   # reclaim orphan leases
python scripts/cwo.py --root <PROJ> heartbeat T-001       # refresh an active task's lease heartbeat (prevents gc reclaim)
python scripts/cwo.py --root <PROJ> loop-status            # state for the orchestration loop (JSON)
python scripts/cwo.py --root <PROJ> serve --port 8787       # web dashboard (http://127.0.0.1:8787)
python scripts/cwo.py --root <PROJ> watch   # interactive terminal TUI
```

The TUI is a dependency-free curses-based interface that shows state live and runs dispatch/integrate/dispatch-auto/gc via keys.

`serve` is a dashboard that shows backlog · leases · loop state in the browser (local-only, 127.0.0.1). Supports GET + POST:
- **Read**: `/api/state` (GET) — full state JSON. Reads (GET) need no auth.
- **Write (POST, executed under project_lock)** — the `X-CWO-Token` header must match the token printed at server startup (CSRF protection). 403 on mismatch:
  - `/api/add` `{"title", "type"?, "source"?, "priority"?}` → `{"id"}`
  - `/api/classify` `{"id", "touches"?, "depends_on"?, "auto"?}` → `{"ok", "id"}`
  - `/api/dispatch` `{"id"}` → `{"ok", "worktree"}`
  - `/api/dispatch-auto` `{}` → `{"dispatched": [...]}`
  - `/api/integrate` `{"id"}` → integrate result dict
  - `/api/gc` `{}` → `{"reclaimed": [...]}`
- **CSRF token**: at startup a random token (`secrets.token_hex(16)`) is generated and printed to the console. A fixed token can be set with the `--token` flag. The browser dashboard is same-origin, so the token is injected into the page and the write buttons send the header automatically. A cross-origin attacker cannot read the token, so CSRF is blocked.
- **UI controls**: top toolbar (add-task form, dispatch-auto button, gc button); each task in the ready column has a touches input · auto checkbox · classify button · dispatch button; each task in the active column has an integrate button.
- Local-only (127.0.0.1). Do not expose externally.

## Triage decision tree — where discovered work goes

When you discover a new issue while a task is active, **don't handle it immediately** — classify it first:

```
new issue discovered
 ├─ truly required to finish the current task (Blocking)? → in the current worktree, separate commit
 ├─ same area · small · low-risk?                         → when in doubt, to the backlog ("while I'm at it" is a trap)
 └─ unrelated, different area?                            → always to the backlog (add), never mixed into the current branch
```

When sending it back to the backlog, record where it was found in `source`: `add ... --source "discovered(from: T-038)"`.

## Filling in `touches`/`depends_on` at classify time (Claude's role)

- **`touches`**: the regions this task will touch. **Default granularity is directory/module** (keep it coarse to prevent false parallelism). Draft it by reading the codebase, then get human approval.
- **`depends_on`**: ids of prerequisite tasks. Make sure no cycle is created.

## Auto-dispatch policy (hybrid)

Conditions under which Claude may dispatch **without human approval** (all must hold):
1. `status == ready` (a human approved the classification)
2. `touches` does not overlap any active lease
3. all `depends_on` are `done`
4. `auto == true`

Otherwise `dispatch` only after human approval. For risky work (broad touches, migrations, etc.) do not turn `auto` on. → In the future, raising the `auto` default flips this to fully automatic.

## Number of concurrent tasks

Conflict safety is guaranteed by the leases. The concurrency count is not a "safety limit" but a "point of diminishing returns":
the minimum of modularity · shared chokepoints · merge bandwidth · machine resources · human review. Hybrid is
usually 2–4 (`config.max_active`, default 4). The real lever to raise it is code modularity.

## After integration / cleanup

- When `integrate`'s tests pass, it merges and releases the lease. On test failure or merge conflict it returns the task to `active` and asks for human intervention.
- If a session dies and its worktree disappears, or the heartbeat goes stale, `gc` reclaims the lease and returns the task to `ready`.
- Long-running active tasks should periodically refresh their `heartbeat` to avoid gc's stale reclaim.

## Configuration (`backlog/config.json`, optional)

```json
{
  "max_active": 4,
  "stale_minutes": 30,
  "test_command": "pytest",
  "main_branch": "main",
  "worktree_parent": null,
  "auto_redispatch": false
}
```

## Auto-redispatch (optional)

- **Manual (default)**: after `integrate` / `gc`, non-conflicting · auto tasks simply stay in the `ready` state; you must run `dispatch-auto` manually to dispatch them.
- **Automatic**: set `init --auto-redispatch`, or `"auto_redispatch": true` in `config.json`, and on a successful `integrate` · `gc`, `dispatch_auto` is called automatically so that non-conflicting · `auto=true` tasks are dispatched immediately.
- **Per-command override**: the `--redispatch` / `--no-redispatch` flags override the config setting for an individual command.
  - `integrate T-001 --redispatch` → redispatch regardless of config
  - `integrate T-001 --no-redispatch` → do not redispatch even if config is `true`
  - same for `gc --redispatch` / `gc --no-redispatch`
- Only tasks with `auto=true` are dispatched (the hybrid policy is preserved; tasks that need human approval are left untouched).

## Concurrency

Mutating commands (add/classify/dispatch/integrate/gc, etc.) take the `backlog/.lock` exclusive lock, guaranteeing backlog/lease consistency when multiple processes (daemon · web · sessions) run at the same time. Read commands (list, leases, check, loop-status, serve) and `init` do not take the lock.

`integrate` runs the test-execution span **without the lock**, and self-locks only the critical section of git checkout/merge · lease release · worktree cleanup · transition to done. As a result, other mutating commands such as web · sessions are not blocked during slow tests. The other mutating commands (add/classify/dispatch/gc) take the lock at the call boundary.

## Autonomous execution daemon (cwo run) — high risk

```bash
python scripts/cwo.py --root <PROJ> run --executor '<shell template>' [--max-iters N] [--dry-run] [--max-parallel N]
```

`cwo run` is a headless execution loop that automatically repeats `loop_status → dispatch-auto → executor(worktree) → integrate`.

- **`--max-parallel N`** (default 4): runs up to N of the active tasks' executors concurrently in a single round. Because each task runs in a disjoint worktree, it parallelizes safely. `integrate` must serialize the main-branch checkout/merge, so it runs serially in order after the executors finish.

- **executor**: the actual work performer. e.g. `claude -p "$CWO_PROMPT"` (headless claude). The prompt · context are passed via environment variables — preventing shell injection:
  - `$CWO_PROMPT` — task title (the prompt content)
  - `$CWO_TASK_ID` — task ID
  - `$CWO_WORKTREE` — assigned worktree absolute path
  - `{id}` / `{worktree}` — controlled values that can be substituted directly into the template
- **`--dry-run`**: prints state only, mutates no task. Can run without an executor.
- **`--max-iters N`**: iteration cap (default 50). Prevents infinite loops.

**Safeguards**:
- No executor + non-dry-run → immediate refusal (`ValueError`, exit 2).
- The max-iters cap guarantees loop termination.
- Each task runs only once (`executed` set tracking) — prevents never-ending tasks.
- `integrate`'s real test gate is the final guardian of the merge.
- On executor failure, that task is left `active` for a human to handle; the loop continues (with other tasks).
- Conflicting tasks are handled automatically by serializing them into the next round after the prerequisite task completes.

> **Warning**: `cwo run` generates code unattended and then auto-merges to main. Use only in a trusted environment, with a sufficient test gate (`test_command`). Headless claude auth · cost is the user's responsibility.

## Orchestration loop (automated execution — performed by Claude)

When the user asks something like "roll the tasks automatically," Claude (the orchestrator) runs the loop below to
completion with its own Agent (subagent) tools. cwo handles scheduling; Claude handles execution.
(Don't ask the user at every step — go all the way to the end — but do report needs_approval · integration failures · errors.)

1. Get the current state with `cwo loop-status` (JSON).
2. Use `cwo dispatch-auto` to dispatch non-conflicting · auto · deps-done tasks into worktrees.
3. For each task that has just become active, spawn a **subagent (Agent)** with `cwd=worktree` to implement and commit it.
   - Since their touches don't overlap, they can be spawned in parallel.
   - Give the subagent prompt the worktree absolute path, the task title/description, and "after implementing, commit in that worktree; don't touch anything outside."
4. When a subagent finishes, `cwo integrate <id>` (test → merge → release lease).
   - If `auto_redispatch=true`, integrate auto-dispatches the task that was blocked → the loop picks it up next round.
5. Repeat 2–4 until `loop_can_progress` in `loop-status` becomes false.
6. On exit, report: the completed list, `needs_approval` (awaiting human approval), `blocked_auto`, and integration-failed tasks.

**Safety boundary**: `auto=false` tasks are not auto-dispatched; report them as `needs_approval` (human approval). On integration failure (test/merge conflict) that task returns to `active` and is reported to the human. This loop runs inside a Claude session (a fully unattended daemon is Phase 3).
