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
python scripts/cwo.py --root <PROJ> heartbeat T-001       # active 작업의 리스 heartbeat 갱신 (gc 회수 방지)
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
- 오래 도는 active 작업은 주기적으로 `heartbeat`를 갱신해 gc의 stale 회수를 피한다.

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
