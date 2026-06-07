# Claude Work Orchestrator (`cwo`)

Run many tasks in **one project, in parallel, without conflicts.**

`cwo` is a file-backed work orchestrator. You register requirements/bugs/issues into a backlog; it isolates each task in its own git worktree and uses **ownership leases** so two tasks never touch the same code region at once. Independent work runs in parallel; work that would collide is automatically serialized.

> Sibling tool: **csm** (claude-session-manager) tracks running *sessions*. `cwo` manages *work*.

[한국어 README](./README.ko.md)

---

## Why

- Feeding requirements one-by-one into an LLM CLI is serial and inefficient.
- Opening several terminals on the *same* working directory causes file / git-index / build / merge conflicts.

`cwo` solves this with two ideas:

1. **Capture vs. dispatch separation** — drop work into the backlog any time, friction-free; entry into execution happens only through a controlled gate.
2. **Ownership lease** — an active task holds a write-lease over its code region (`touches`). A new task is dispatched only if its region doesn't overlap any active lease. Conflicts are prevented *structurally*, before any code is written.

---

## Requirements

- **Python 3.13+** — standard library only, **no dependencies**.
- **git** — required for `dispatch` / `integrate` (worktrees + merges).
- The **target project** must be a git repository with a `main` branch, and should `.gitignore` build/test artifacts (e.g. `__pycache__/`, `*.pyc`). `cwo init` warns if there's no `.gitignore`.

---

## Install

```bash
./install.sh
```

The (idempotent) installer links the skill into `~/.claude/skills/` (so Claude Code discovers it) and symlinks a **`cwo` command** into a PATH directory (prefers `~/.local/bin`). It checks Python (3.9+) and verifies the command runs. Remove everything with `./install.sh --uninstall`.

Manual alternative:

```bash
ln -s "$(pwd)" ~/.claude/skills/claude-work-orchestrator                     # skill discovery
alias cwo='python3 /absolute/path/to/claude-work-orchestrator/scripts/cwo.py'  # CLI
```

The examples below assume `cwo` is on your PATH (otherwise run `python3 scripts/cwo.py`).

---

## Quick start

```bash
# In your target git project:
cwo --root ~/myapp init                          # create backlog/

# 1) Register work any time (frictionless)
cwo --root ~/myapp add "refund negative-amount bug" --type bug --priority high   # -> T-001
cwo --root ~/myapp add "cart UI revamp"                                          # -> T-002

# 2) Classify: declare the area each task touches (+ allow auto-dispatch)
cwo --root ~/myapp classify T-001 --touches payment/ --auto
cwo --root ~/myapp classify T-002 --touches ui/ --auto

# 3) Dispatch non-conflicting, independent tasks into isolated worktrees
cwo --root ~/myapp dispatch-auto                 # T-001, T-002 dispatched in parallel

# 4) Do the work in each worktree (e.g. ~/myapp-T-001), then integrate
cwo --root ~/myapp integrate T-001               # test -> merge -> release lease -> done
```

---

## How conflicts are prevented

A lease records `{task, touches, worktree, heartbeat}`. `touches` overlap is **path-hierarchical**:

- `payment/` overlaps `payment/refund.py` (directory is an ancestor).
- `payment` does **not** overlap `payment2` (path-boundary aware).

When a task's `touches` overlap an active lease, it is **not dispatched** — it waits in `ready`. When the lease holder integrates (or is reclaimed by `gc`), the region frees and the waiting task can be dispatched, now branching off the *updated* `main` (so it builds on top of the prior change — no merge conflict).

Because the full `touches` set is acquired atomically at dispatch (no hold-and-wait), the lease scheme is **deadlock-free**.

---

## Command reference

`--root <PROJ>` selects the target project (default `.`).

| Command | Purpose |
|---|---|
| `init [--auto-redispatch]` | Create `backlog/`. `--auto-redispatch` enables auto mode. |
| `add "<title>" [--type] [--source] [--priority]` | Register a task (lands in `inbox`). |
| `classify <id> [--touches ...] [--depends-on ...] [--auto]` | Set touches/deps, move to `ready`. |
| `list [--status <s>]` | List tasks (optionally by status). |
| `leases` | Show active leases (occupied regions). |
| `check <id>` | Can this task be dispatched now? (exit 0/1) |
| `dispatch <id>` | Create worktree + acquire lease + go `active`. |
| `dispatch-auto` | Dispatch all `auto`, non-conflicting, deps-done tasks. |
| `integrate <id>` | Run test gate → merge → release lease → `done` (exit 0/1). |
| `gc` | Reclaim orphan leases (dead session / stale heartbeat). |
| `heartbeat <id>` | Refresh an active task's lease heartbeat. |
| `loop-status` | JSON state for the orchestration loop. |
| `run [--executor CMD] [--max-iters N] [--max-parallel N] [--dry-run]` | Headless autonomous loop. |
| `serve [--host] [--port] [--token]` | Read/write web dashboard. |
| `watch` | Interactive terminal UI (curses) — live view + keybindings. |

### Task record (`backlog/<status>/T-NNN.json`)

```json
{
  "id": "T-042", "title": "...", "type": "bug",
  "source": "human", "touches": ["payment/refund.py"], "depends_on": [],
  "status": "inbox", "priority": "high", "auto": false, "worktree": null
}
```

Status: `inbox → ready → active → (integrating) → done`. `integrating` shares the `active/` directory.

---

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

- `max_active` — concurrency ceiling.
- `test_command` — the integration gate; the merge only happens if this passes (run in the worktree).
- `auto_redispatch` — when `true`, `integrate`/`gc` automatically pull in newly-unblocked tasks.

---

## Concurrency model

Conflict *safety* is guaranteed by the lease (active leases are pairwise non-overlapping). The realistic *number* of parallel tasks is the minimum of: independent code regions (modularity), shared chokepoints, merge bandwidth, machine resources, and — in hybrid mode — human review. Hybrid: typically **2–4** (`max_active`). The real lever for more parallelism is **code modularity**, not the tool.

Mutating commands take an exclusive `flock` (`backlog/.lock`) so multiple processes (daemon / web / sessions) stay consistent. `integrate` runs its (slow) test command *without* the lock, holding it only around the merge/release critical section.

---

## Web dashboard (`cwo serve`)

```bash
cwo --root ~/myapp serve --port 8787
# open http://127.0.0.1:8787   (token printed at startup)
```

- Read-only view of tasks (by status), active leases, and loop status; live-polling.
- Write actions (add / classify / dispatch / dispatch-auto / integrate / gc) via buttons.
- Localhost-only. Write endpoints require an `X-CWO-Token` header matching the startup token (CSRF protection); the page is served with the token injected so legitimate writes work. Use `--token` to set a fixed token.

## TUI (`cwo watch`)

```bash
cwo --root ~/myapp watch
```

`cwo --root <PROJ> watch` launches an interactive terminal UI (stdlib curses, no deps) — live view + keybindings (d dispatch, i integrate, a dispatch-auto, g gc, q quit).

---

## Headless daemon (`cwo run`) — high risk

Autonomously drives the loop: `loop-status → dispatch-auto → executor(worktree) → integrate`, repeating until no progress remains.

```bash
cwo --root ~/myapp run --executor 'claude -p "$CWO_PROMPT"' --dry-run   # preview first!
cwo --root ~/myapp run --executor 'claude -p "$CWO_PROMPT"' --max-parallel 4
```

- The **executor** does the actual coding in each worktree. The prompt is passed via env (`$CWO_PROMPT`, `$CWO_TASK_ID`, `$CWO_WORKTREE`) — never interpolated into the shell string (injection-safe).
- Executors run **in parallel** (`--max-parallel`, default 4); `integrate` runs serially (main-branch merges can't be concurrent).
- **Safety**: refuses to run without an executor (or `--dry-run`); `--max-iters` cap; each task executed at most once (guaranteed termination); the real test gate guards every merge; failed tasks are left `active` for human follow-up.
- ⚠️ This autonomously generates code and auto-merges to `main`. Use only in a trusted environment, with a real test gate. Headless `claude` auth/cost is your responsibility.

---

## Triage: discovered work

When you find a new issue while a task is active, **don't fix it inline** — triage first:

- **Blocking** the current task → do it in the current worktree (separate commit).
- **Unrelated** → register to the backlog (`add ... --source "discovered(from: T-038)"`), never mixed into the current branch.

The backlog is the single source of truth; worktrees feed discovered work *back* into it.

---

## Architecture

```
scripts/
  paths.py     # touches overlap primitive (conflict detection)
  config.py    # settings loader
  backlog.py   # task records + state-directory transitions
  lease.py     # ownership leases + conflict gate
  lock.py      # flock-based project lock
  dispatch.py  # can_dispatch + dispatch (worktree) + dispatch_auto + loop_status
  integrate.py # integration gate (test -> merge -> release)
  cwo_gc.py    # orphan-lease reaper
  runner.py    # headless run loop (parallel executors)
  web.py       # dashboard (http.server, read + write + token)
  tui.py       # interactive terminal UI (curses)
  cwo.py       # CLI entry
tests/         # pytest (stdlib), 92 tests
SKILL.md       # protocol for the Claude orchestrator
design.md      # design spec    plan.md  # implementation plan
```

The backlog (files) is a stable contract; intake adapters (CLI, web) and the dispatch policy (hybrid / auto) sit on top and are swappable — the engine doesn't change.

---

## Status

- **Phase 1 — engine**: file backlog · ownership leases · hybrid dispatch · integration gate · gc.
- **Phase 2 — automation**: auto-redispatch · dependency-cycle check · heartbeat · loop-status · orchestration loop (Claude subagents execute in worktrees).
- **Phase 3 — operations**: concurrency lock · web dashboard (read + write + token auth) · headless daemon (parallel, guard-railed).

stdlib-only, 92 passing tests.
