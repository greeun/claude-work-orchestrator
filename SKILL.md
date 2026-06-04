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

## 셋업 주의

대상 프로젝트가 git repo면 빌드/테스트 아티팩트(`__pycache__/`, `*.pyc`, `.pytest_cache/` 등)를 반드시 `.gitignore`하라. 안 그러면 통합 게이트의 `test_command`가 만든 아티팩트가 worktree 머지를 깨뜨릴 수 있다. `cwo init`이 `.gitignore` 없으면 경고한다.

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
python scripts/cwo.py --root <PROJ> heartbeat T-001       # active 작업의 리스 heartbeat 갱신 (gc 회수 방지)
python scripts/cwo.py --root <PROJ> loop-status            # 오케스트레이션 루프용 상태(JSON)
python scripts/cwo.py --root <PROJ> serve --port 8787       # 웹 대시보드 (http://127.0.0.1:8787)
```

`serve`는 백로그·리스·loop 상태를 브라우저로 보여주는 대시보드(로컬 전용, 127.0.0.1). GET + POST 지원:
- **읽기**: `/api/state` (GET) — 전체 상태 JSON
- **쓰기 (POST, project_lock 하에 실행)**:
  - `/api/add` `{"title", "type"?, "source"?, "priority"?}` → `{"id"}`
  - `/api/classify` `{"id", "touches"?, "depends_on"?, "auto"?}` → `{"ok", "id"}`
  - `/api/dispatch` `{"id"}` → `{"ok", "worktree"}`
  - `/api/dispatch-auto` `{}` → `{"dispatched": [...]}`
  - `/api/integrate` `{"id"}` → integrate 결과 dict
  - `/api/gc` `{}` → `{"reclaimed": [...]}`
- **UI 컨트롤**: 상단 툴바(add-task 폼, dispatch-auto 버튼, gc 버튼), ready 컬럼 각 태스크에 touches 입력·auto 체크박스·classify 버튼·dispatch 버튼, active 컬럼 각 태스크에 integrate 버튼.
- 인증/CSRF 없음 — 로컬 개발 전용(127.0.0.1). 외부 노출 금지.

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
- 오래 도는 active 작업은 주기적으로 `heartbeat`를 갱신해 gc의 stale 회수를 피한다.

## 설정 (`backlog/config.json`, 선택)

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

## 자동 재투입 (선택)

- **수동(기본)**: `integrate` / `gc` 후 비충돌·auto 작업은 그대로 `ready` 상태로 남아, 수동으로 `dispatch-auto`를 실행해야 투입된다.
- **자동**: `init --auto-redispatch` 또는 `config.json`에 `"auto_redispatch": true`를 설정하면, `integrate`·`gc` 성공 시 자동으로 `dispatch_auto`가 호출되어 비충돌·`auto=true` 작업이 즉시 투입된다.
- **per-command 오버라이드**: `--redispatch` / `--no-redispatch` 플래그로 config 설정을 개별 명령에서 덮어쓸 수 있다.
  - `integrate T-001 --redispatch` → config 무관하게 재투입
  - `integrate T-001 --no-redispatch` → config가 `true`여도 재투입 안 함
  - `gc --redispatch` / `gc --no-redispatch` 동일
- `auto=true`인 작업만 투입한다 (하이브리드 정책 유지, 사람 승인이 필요한 작업은 건드리지 않음).

## 동시성

변경 명령(add/classify/dispatch/integrate/gc 등)은 `backlog/.lock` 배타 락을 잡아 다중 프로세스(데몬·웹·세션) 동시 실행 시 백로그/리스 일관성을 보장한다. 읽기 명령(list, leases, check, loop-status, serve)과 `init`은 락을 잡지 않는다. (트레이드오프: integrate가 테스트 실행 동안 락을 보유 — v1은 명령 경계 락, 세밀화는 추후.)

## 오케스트레이션 루프 (자동 실행 — Claude가 수행)

사용자가 "작업들 자동으로 굴려줘" 류로 요청하면, Claude(오케스트레이터)는 아래 루프를
자기 Agent(서브에이전트) 도구로 끝까지 실행한다. cwo는 스케줄링을, Claude는 실행을 맡는다.
(중간에 사용자에게 일일이 묻지 말고 끝까지 진행하되, needs_approval·통합 실패·오류는 보고)

1. `cwo loop-status` 로 현황 파악 (JSON).
2. `cwo dispatch-auto` 로 비충돌·auto·의존완료 작업을 worktree로 투입.
3. 새로 active가 된 작업마다 **서브에이전트(Agent)** 를 `cwd=worktree`로 띄워 구현·커밋시킨다.
   - 서로 touches가 안 겹치므로 병렬 spawn 가능.
   - 서브에이전트 프롬프트엔 worktree 절대경로, 작업 title/설명, "구현 후 그 worktree에서 커밋, 외부는 건드리지 말 것"을 준다.
4. 서브에이전트가 끝나면 `cwo integrate <id>` (테스트→머지→리스 반납).
   - `auto_redispatch=true`면 integrate가 막혔던 작업을 자동 투입 → 루프가 다음 라운드에 집는다.
5. `loop-status`의 `loop_can_progress`가 false가 될 때까지 2~4를 반복.
6. 종료 시 보고: 완료 목록, `needs_approval`(사람 승인 대기), `blocked_auto`, 통합 실패 작업.

**안전 경계**: `auto=false` 작업은 자동 투입하지 않고 `needs_approval`로 보고(사람 승인). 통합 실패(테스트/머지 충돌)면 그 작업은 `active`로 되돌아오며 사람에게 보고한다. 이 루프는 Claude 세션 안에서 돈다(완전 무인 데몬은 Phase 3).
