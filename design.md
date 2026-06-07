# Claude Work Orchestrator (`cwo`) — Design Spec

**Date**: 2026-06-04
**Status**: Draft (awaiting user review)

## Problem

When working on a single project with an LLM CLI (Claude Code):

1. Feeding requirements · bugs · issues into the CLI as they come to mind is irrational, because they are processed serially.
2. When a person opens several terminals and runs them concurrently in the same working directory, files · the git index · build artifacts · the dev server collide.
3. Work arises **constantly and unpredictably** (new human requests + bugs/follow-ups discovered while working).

→ We need "a concurrent-work operating protocol for handling compound requirements in a single project **in parallel, without conflicts**, plus a tool that removes that friction."

There are two core inventions:
- **Separation of capture and dispatch** — keeps the system from breaking even as work arises constantly.
- **Ownership lease** — a write-lock over a code region that *structurally* guarantees conflict-free parallelism.

## Goals / Non-goals (v1)

**Goals (v1 = engine)**
- File-backed backlog: register work friction-free, at any time (append). Git-versioned · transparent.
- Task state machine: express `inbox → ready → active → done` as a directory location.
- Affected-region lease-based conflict gate: dispatch only when `touches` are non-overlapping ∧ `depends_on` are complete.
- Hybrid dispatch: a human registers · approves classification, the tool checks leases · creates/cleans up worktrees, and Claude auto-dispatches low-risk · non-conflicting · independent work.
- Integration gate: test → merge (rebase) → release lease → done. (reuses `full-test-orchestrator`)
- Feedback loop for discovered work: issues found during an active task are auto-registered into the inbox (with traceability).
- **Interface separation for future extension**: the intake adapter and the approval policy are detached from the core, so that a web UI · full automation can be layered on *without replacing the engine*.

**Non-goals (excluded in v1 — YAGNI)**
- Web UI intake adapter (added in Phase 3; v1 only prepares the interface).
- Fully-automatic orchestrator daemon (Phase 2~3).
- Auto-spawning separate terminal sessions (because it's hybrid, a human opens them or uses a background agent).
- Distributed/multi-machine, real-time dashboard TUI, ML-based auto-prioritization.

## Relationship to existing assets (avoiding duplication)

| Asset | Scope | Relationship to cwo |
|---|---|---|
| **csm** (claude-session-manager) | Observing running **sessions** (which window is alive, focus/resume) | cwo manages **work**. csm's Non-goals (web UI · dependency graph) are cwo's Goals. Session live/idle detection is leveraged by cwo's lease GC |
| **full-test-orchestrator** | Spec-based test generation · triage · fixing | Called as the test step of cwo's integration gate |

**Scope separation**: cwo = *work item*, csm = *running session*. Which session/worktree an active task lives in is linked via the worktree path in the lease record.

## Core concepts

### 1. Capture / dispatch separation

```
[capture] any time · instant · friction-free      [dispatch] careful · after conflict check
  toss it into the backlog as it occurs     →     the scheduler decides "is it safe now"
  OK to defer the decision on what to do          if safe, assign a worktree; otherwise wait
```

New work merely accumulates safely in the inbox, and entry into execution happens only when it passes a controlled gate (the lease gate). **Prediction becomes unnecessary.**

### 2. Ownership lease

- A worktree in progress holds a **write-lease** over its own `touches`.
- Dispatch rule: `touches ∩ (all active leases) == ∅` ∧ `all depends_on done`.
- If they overlap, it is not dispatched and waits in `ready` → released when that worktree merges and returns its lease.

```
active lease:  worktree-A → touches: {payment/, api/order.ts}
new task X:  touches: {ui/cart.tsx}        → no overlap   ✅ dispatch in parallel immediately
new task Y:  touches: {payment/refund.ts}  → payment/ overlap ❌ wait → after A merges
```

### 3. State machine

```
inbox ─classify─▶ ready ─dispatch(acquire lease)─▶ active ─work done─▶ integrating ─merge(release lease)─▶ done
  ▲                                      │
  └──────── (newly discovered work) ─────┘
```

## Architecture (layered — the core is stable, both ends are swappable)

```
            intake adapter (swappable)
   ┌──────────┬──────────┬──────────┐
   │ CLI/file │  web UI  │ (others) │   v1: file,  Phase3: add web UI
   └────┬─────┴────┬─────┴────┬─────┘
        └──────────┼──────────┘
                   ▼
        ┌─────────────────────┐
        │  backlog core (stable) │   files/structured data = the "contract" that never changes
        │  + lease conflict engine │
        └──────────┬──────────┘
                   ▼
        ┌─────────────────────┐
        │  dispatch policy (swappable)│   v1: hybrid (human approval)
        │                     │   Phase2~3: auto (remove the approval gate)
        └──────────┬──────────┘
                   ▼
          execute (worktree) → integration gate → done
```

Three decisions that make evolution *free*:
1. **The backlog is files/structured data** → a web UI is just a frontend that reads and writes the same backlog; the engine is unchanged.
2. **Human approval is separated out as "policy"** → full automation isn't a rebuild but removing the approval gate (an `auto: true` switch).
3. **Dispatch is a loop** → in v1 a human triggers it; in the future a backlog-watching daemon triggers it. The loop body is identical.

## Data model

> **Storage format = JSON (stdlib · dependency-free)**. Since csm uses `json` for runtime storage, cwo also uses JSON for consistency · dependency-freeness. The default path is registering/editing via the `cwo` CLI rather than humans editing files directly.

### Backlog directory (state = location)

```
backlog/
  inbox/          # just registered · unclassified (the landing spot for constant intake)
    T-042.json
  ready/          # classified (touches/depends_on filled in) · awaiting dispatch
  active/         # in-progress · holding a lease (integrating lives here too — no separate directory)
    T-038.json
  done/           # completed archive
  LEASES.json     # active leases = touches occupancy (the conflict-decision table)
```

There are 4 directories (`inbox/ready/active/done`). `integrating` is **not a separate directory** but a *transition stage* in which the integration gate runs while the task stays in active/ (holding its lease). The lease is released at the moment of the active→done move.

### Task record (`T-NNN.json`)

```json
{
  "id": "T-042",
  "title": "validate negative amount on payment refund",
  "type": "bug",
  "source": "discovered(from: T-038)",
  "touches": ["payment/refund.ts"],
  "depends_on": [],
  "status": "inbox",
  "priority": "high",
  "auto": false,
  "worktree": null
}
```

Field meanings:
- `type`: `feature` | `bug` | `refactor`
- `source`: `human` | `discovered(from: <id>)` — traceability
- `touches`: **the key for conflict decisions** (default granularity: directory/module)
- `depends_on`: list of prerequisite task ids
- `status`: `inbox`|`ready`|`active`|`integrating`|`done` (active/integrating share the active/ directory)
- `auto`: if `true`, allow auto-dispatch without human approval
- `worktree`: filled in (a path) at dispatch; `null` before that

### Lease table (`LEASES.json`)

```json
{
  "leases": [
    {
      "task": "T-038",
      "touches": ["payment/", "api/order.ts"],
      "worktree": "../proj-T-038",
      "heartbeat": "2026-06-04T10:21:00+00:00"
    }
  ]
}
```

`heartbeat` (ISO8601) is used to decide GC of dead sessions. The worktree path is also used for csm session matching.

## Components (each with a single responsibility)

| Component | What it does | Depends on |
|---|---|---|
| **Backlog Store** | Task-record CRUD, state (directory) moves | filesystem · git |
| **Lease Table** | Records/queries active-lease occupancy, decides conflicts | Backlog Store |
| **Classifier** | Drafts an inbox item's `touches` · `depends_on` (codebase analysis) → human approval | codebase |
| **Dispatcher** | Selects non-conflicting · deps-done tasks from the ready queue → creates worktree · acquires lease · moves to active | Lease Table, git worktree |
| **Integration Gate** | test → merge (rebase) → release lease → done | full-test-orchestrator, git |
| **GC/Reaper** | Reclaims orphan leases of worktrees with no heartbeat; on reclaim it also best-effort deletes that task's git branch (`cwo/<id>`) · worktree registration so a clean recreate is possible on re-dispatch | csm live/idle detection |

## Hybrid dispatch boundary

- **Human**: register (any time) · approve classification · approve dispatch of *risky* work · final merge approval
- **Tool (script)**: lease conflict check · worktree create/cleanup · lease acquire/release · state moves
- **Claude (coordinator)**: classification draft · auto-register discovered work into inbox · auto-dispatch low-risk work · run the integration gate

**Auto-dispatch conditions** (Claude dispatches without human approval):
`status==ready` ∧ `touches ∩ all active leases == ∅` ∧ `all depends_on done` ∧ `auto==true`.
Otherwise human approval is required. → Separating these conditions out as policy means that in Phase 2~3 you only raise the `auto` default to switch to full automation.

## Concurrency model

The conflict-free number of concurrent tasks is not a fixed value but **the minimum of 5 bottlenecks**:

1. **Number of independent regions** — the theoretical upper bound set by code modularity
2. **Shared chokepoints** — hidden serialization: lockfiles, shared types, DB migrations, config, etc.
3. **Merge bandwidth** — K in parallel → merging triggers rebases of the rest (≈O(K²))
4. **Machine resources** — per-worktree working copy · dev server · tests (CPU/RAM/ports)
5. **Human review bandwidth** — (hybrid only)

**Because the leases guarantee safety**, the number above is not a "safety limit" but a "point of diminishing returns".
- Hybrid (v1): ⑤ is the bottleneck → **2~4**
- Full auto (future): ③ · ④ are the bottleneck → typically **4~8** (more if the modules are truly independent)

**Design implication**: instead of a fixed cap, use (a) leases that naturally self-limit + (b) only a per-mode ceiling as a setting (`max_active`, hybrid default 4). It's documented that the real lever to raise concurrency is not the tool but **code modularity**.

## `touches` accuracy & 3-layer safety net

- **Default granularity**: directory/module level (kept coarse to prevent false parallelism). File level is an option.
- **Author**: the Classifier (Claude) drafts → human approval.
- **3-layer net against mis-declaration**:
  1. If a file outside the declaration is touched during work → **lease-expansion request** → if it overlaps, pause · re-serialize
  2. The integration gate's **tests** are the final block against regressions
  3. The **git merge** is the last detection point for physical conflicts

## Edge cases

- **Orphan lease** (session death): GC reclaims by heartbeat · worktree path (with csm linkage); on reclaim it best-effort deletes the `cwo/<id>` branch and the worktree registration → a clean restart with no branch-name collision is possible on re-dispatch
- **Dependency cycle/deadlock**: check `depends_on` for cycles at classify time
- **Merge conflict**: rebase in integration; on conflict, human intervention
- **active overflow**: limited by the `max_active` ceiling
- **touches-expansion conflict during work**: pause that worktree, then re-serialize
- **Concurrent multi-process access**: a `backlog/.lock` file lock (`fcntl.flock` exclusive lock) serializes the boundaries of mutating commands. Even if a daemon · web UI · multiple sessions mutate the backlog/LEASES.json at the same time, consistency is guaranteed. The earlier "single orchestrator, serial assumption" is removed, limited to CLI-level concurrency (v1 scope). Read commands do not take the lock.

## Evolution path

- **Phase 1 (v1, now)**: file backlog + lease engine + hybrid dispatch. Intake = CLI/file.
- **Phase 2**: automate the approval gate for low-risk work → "mostly automatic." *(First Phase-2 increment implemented: the `auto_redispatch` config policy — automating the scheduling loop that auto-dispatches non-conflicting · auto tasks after `integrate` · `gc`. Daemonizing the execution loop is separate.)* *(Second Phase-2 increment implemented: the orchestration-loop protocol — the `loop-status` command (a read-only JSON snapshot: counts · active · dispatchable · blocked_auto · needs_approval · loop_can_progress) and documentation of the SKILL loop procedure. The executor = a Claude subagent; cwo's role is separated as scheduling + state provision.)*
- **Phase 3 (forward-looking)**: web UI intake adapter + a backlog-watching orchestrator daemon → "register, take your hands off, and it handles the rest." *(First Phase-3 increment implemented: the headless daemon `cwo run` — an autonomous repeat loop of loop_status→dispatch-auto→executor→integrate, with guardrails (refuse if no executor · max-iters cap · run-once guarantee · keep failed tasks active) and stub tests. Wiring real headless claude is the user's environment. The web UI adapter · backlog-watching daemon are unimplemented.)*

## Testing strategy

- **Script unit tests**: lease conflict decisions, state transitions, GC, cycle checks.
- **Scenario tests**: the full loop of capture→classify→dispatch→conflict-wait→merge→lease-release. Non-conflicting/conflicting cases for many concurrent tasks.

## Packaging

- A new skill **`claude-work-orchestrator` (`cwo`)** — the partner to csm.
- For consistency with csm, structured as a **Python script + `SKILL.md` + slash command**.
- Directory: `claude-skills/claude-work-orchestrator/`.

## Open questions / deferred decisions

- Backlog location: `backlog/` at the target project root vs a separate directory (central registry) — v1 assumes project-local.
- Finalizing the `cwo` name (room to consider alternatives).
- Worktree naming convention (assumed `../proj-T-NNN`).
