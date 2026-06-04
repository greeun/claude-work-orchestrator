# Claude Work Orchestrator (`cwo`) — Design Spec

**Date**: 2026-06-04
**Status**: Draft (awaiting user review)

## Problem

LLM CLI(Claude Code)로 한 프로젝트를 진행할 때:

1. 요구사항·버그·이슈를 CLI에 떠오르는 대로 입력하면 순차 처리라 비합리적이다.
2. 사람이 터미널을 여러 개 열어 같은 작업 디렉터리에서 동시에 돌리면, 파일·git index·빌드 산출물·dev 서버가 충돌한다.
3. 작업은 **수시로, 예측 불가능하게** 발생한다(사람의 새 요구 + 작업 중 발견된 버그/후속작업).

→ "한 프로젝트에서 복합 요구사항을 **충돌 없이 병렬 처리**하기 위한 동시작업 운영 프로토콜과, 그 마찰을 없애는 도구"가 필요하다.

핵심 발명은 두 가지:
- **등록(capture)과 투입(dispatch)의 분리** — 작업이 수시로 생겨도 시스템이 깨지지 않게 한다.
- **영향범위 리스(ownership lease)** — 코드 영역에 대한 쓰기 잠금으로 충돌 없는 병렬성을 *구조적으로* 보장한다.

## Goals / Non-goals (v1)

**Goals (v1 = 엔진)**
- 파일 기반 백로그: 작업을 언제든 무마찰로 등록(append). git 버전관리·투명.
- 작업 상태 머신: `inbox → ready → active → done`을 디렉터리 위치로 표현.
- 영향범위 리스 기반 충돌 게이트: `touches` 비겹침 ∧ `depends_on` 완료일 때만 투입.
- 하이브리드 디스패치: 사람이 등록·분류 승인, 도구가 리스 검사·worktree 생성/정리, Claude가 저위험·비충돌·독립 작업을 자동 투입.
- 통합 게이트: 테스트 → 머지(rebase) → 리스 반납 → done. (`full-test-orchestrator` 재사용)
- 발견된 작업의 되먹임 루프: active 작업 중 발견한 이슈를 inbox로 자동 등록(추적성 포함).
- **미래 확장을 위한 인터페이스 분리**: 입력 어댑터(intake)와 승인 정책(policy)을 코어에서 떼어내, 웹UI·완전자동이 *엔진 교체 없이* 얹히도록.

**Non-goals (v1에서 제외 — YAGNI)**
- 웹 UI 입력 어댑터 (Phase 3에서 추가. v1은 인터페이스만 준비).
- 완전자동 오케스트레이터 데몬 (Phase 2~3).
- 별도 터미널 세션 자동 스폰 (하이브리드라 사람이 열거나 백그라운드 에이전트 사용).
- 분산/멀티머신, 실시간 대시보드 TUI, ML 기반 자동 우선순위.

## Relationship to existing assets (중복 회피)

| 자산 | 스코프 | cwo와의 관계 |
|---|---|---|
| **csm** (claude-session-manager) | 실행 중인 **세션** 관측 (어떤 창이 살아있나, focus/resume) | cwo는 **작업**을 관리. csm의 Non-goals(웹UI·의존성 그래프)가 cwo의 Goals. 세션 live/idle 감지는 cwo의 리스 GC에 활용 |
| **full-test-orchestrator** | 스펙 기반 테스트 생성·트리아지·수정 | cwo 통합 게이트의 테스트 단계로 호출 |

**스코프 분리**: cwo = *작업(work item)*, csm = *세션(running session)*. 한 active 작업이 어느 세션/worktree에 있는지는 리스 레코드의 worktree 경로로 연결.

## Core concepts

### 1. 등록 / 투입 분리

```
[등록] 언제든·즉시·무마찰              [투입] 신중·충돌검사 후
  떠오르면 백로그에 던진다       →     스케줄러가 "지금 안전한가" 판정
  무엇을 할지 결정 보류 OK             안전하면 worktree 배정, 아니면 대기
```

새 작업은 안전하게 inbox에 쌓일 뿐이고, 실행 진입은 통제된 관문(리스 게이트)을 통과할 때만. **예측이 불필요**해진다.

### 2. 영향범위 리스 (ownership lease)

- 진행 중 worktree는 자기 `touches`에 대해 **쓰기 리스**를 쥔다.
- 투입 규칙: `touches ∩ (모든 활성 리스) == ∅` ∧ `depends_on 전부 done`.
- 겹치면 투입하지 않고 `ready`에서 대기 → 해당 worktree 머지·리스 반납 시 풀림.

```
활성 리스:  worktree-A → touches: {payment/, api/order.ts}
새 작업 X:  touches: {ui/cart.tsx}        → 겹침 없음  ✅ 즉시 병렬 투입
새 작업 Y:  touches: {payment/refund.ts}  → payment/ 겹침 ❌ 대기 → A 머지 후
```

### 3. 상태 머신

```
inbox ─분류─▶ ready ─투입(리스획득)─▶ active ─작업완료─▶ integrating ─머지(리스반납)─▶ done
  ▲                                      │
  └──────── (발견된 새 작업) ─────────────┘
```

## Architecture (계층형 — 코어는 안정, 양 끝은 교체 가능)

```
            입력 어댑터 (교체 가능)
   ┌──────────┬──────────┬──────────┐
   │ CLI/파일 │  웹 UI   │  (기타)  │   v1: 파일,  Phase3: 웹UI 추가
   └────┬─────┴────┬─────┴────┬─────┘
        └──────────┼──────────┘
                   ▼
        ┌─────────────────────┐
        │  백로그 코어 (안정)  │   파일/구조화 데이터 = 절대 안 바뀌는 "계약"
        │  + 리스 충돌 엔진    │
        └──────────┬──────────┘
                   ▼
        ┌─────────────────────┐
        │  디스패치 정책 (교체)│   v1: 하이브리드(사람 승인)
        │                     │   Phase2~3: auto(승인 게이트 제거)
        └──────────┬──────────┘
                   ▼
          실행(worktree) → 통합게이트 → done
```

진화를 *공짜로* 만드는 세 결정:
1. **백로그가 파일/구조화 데이터** → 웹UI는 같은 백로그를 읽고 쓰는 프론트엔드일 뿐, 엔진 불변.
2. **사람 승인이 "정책"으로 분리** → 완전자동 = 새로 짓는 게 아니라 승인 게이트 제거(`auto: true` 스위치).
3. **디스패치가 루프** → v1은 사람이 트리거, 미래엔 백로그 감시 데몬이 트리거. 루프 본체 동일.

## Data model

> **저장 포맷 = JSON (stdlib·무의존성)**. csm이 런타임 저장에 `json`을 쓰므로 일관성·무의존성을 위해 cwo도 JSON. 사람이 직접 편집하기보다 `cwo` CLI로 등록/수정하는 것을 기본 경로로 본다.

### 백로그 디렉터리 (상태 = 위치)

```
backlog/
  inbox/          # 막 등록됨·미분류 (수시 인입의 착지점)
    T-042.json
  ready/          # 분류 완료(touches/depends_on 채움)·투입 대기
  active/         # in-progress·리스 보유 (integrating도 여기 — 별도 디렉터리 없음)
    T-038.json
  done/           # 완료 아카이브
  LEASES.json     # 활성 리스 = touches 점유 현황 (충돌 판정 테이블)
```

디렉터리는 4개(`inbox/ready/active/done`). `integrating`은 **별도 디렉터리가 아니라** active/에 머문 채(리스 보유) 통합 게이트가 도는 *전이 단계*다. 리스는 active→done 이동 시점에 반납한다.

### 작업 레코드 (`T-NNN.json`)

```json
{
  "id": "T-042",
  "title": "결제 환불 시 음수 금액 검증",
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

필드 의미:
- `type`: `feature` | `bug` | `refactor`
- `source`: `human` | `discovered(from: <id>)` — 추적성
- `touches`: **충돌 판정의 핵심 키** (기본 입도: 디렉터리/모듈)
- `depends_on`: 선행 작업 id 목록
- `status`: `inbox`|`ready`|`active`|`integrating`|`done` (active/integrating은 active/ 디렉터리 공유)
- `auto`: `true`면 사람 승인 없이 자동 투입 허용
- `worktree`: 투입 시 채워짐(경로), 그 전엔 `null`

### 리스 테이블 (`LEASES.json`)

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

`heartbeat`(ISO8601)는 죽은 세션 GC 판정용. worktree 경로는 csm 세션 매칭에도 사용.

## Components (각각 단일 책임)

| 컴포넌트 | 하는 일 | 의존 |
|---|---|---|
| **Backlog Store** | 작업 레코드 CRUD, 상태(디렉터리) 이동 | 파일시스템·git |
| **Lease Table** | 활성 리스 점유 기록/조회, 충돌 판정 | Backlog Store |
| **Classifier** | inbox 항목의 `touches`·`depends_on` 초안 작성(코드베이스 분석) → 사람 승인 | 코드베이스 |
| **Dispatcher** | ready 큐에서 비충돌·의존완료 작업 선별 → worktree 생성·리스 획득·active 이동 | Lease Table, git worktree |
| **Integration Gate** | 테스트 → 머지(rebase) → 리스 반납 → done | full-test-orchestrator, git |
| **GC/Reaper** | heartbeat 없는 worktree의 고아 리스 회수; 회수 시 해당 작업의 git branch(`cwo/<id>`)·worktree 등록도 best-effort 삭제하여 재투입 시 클린 재생성 가능 | csm live/idle 감지 |

## Hybrid dispatch boundary

- **사람**: 등록(아무 때나) · 분류 승인 · *위험* 작업 투입 승인 · 머지 최종 승인
- **도구(스크립트)**: 리스 충돌 검사 · worktree 생성/정리 · 리스 획득/반납 · 상태 이동
- **Claude(조율자)**: 분류 초안 · 발견작업 inbox 자동등록 · 저위험 자동 투입 · 통합 게이트 실행

**자동 투입 조건** (사람 승인 없이 Claude가 투입):
`status==ready` ∧ `touches ∩ 모든활성리스 == ∅` ∧ `depends_on 전부 done` ∧ `auto==true`.
그 외에는 사람 승인 필요. → 이 조건을 정책으로 분리해 두면 Phase 2~3에서 `auto` 기본값만 올려 완전자동으로 전환.

## Concurrency model

충돌 없는 동시 작업 수는 고정값이 아니라 **5개 병목의 최솟값**:

1. **독립 영역 수** — 코드 모듈성이 정하는 이론적 상한
2. **공유 초크포인트** — lockfile, 공통 타입, DB 마이그레이션, 설정 등 숨은 직렬화
3. **머지 대역폭** — K개 병렬 → 머지 시 나머지 rebase 유발(≈O(K²))
4. **머신 자원** — worktree별 작업본·dev서버·테스트(CPU/RAM/포트)
5. **사람 검토 대역폭** — (하이브리드 한정)

**리스가 안전성을 보장**하므로 위 숫자는 "안전 한계"가 아니라 "수익 체감 지점".
- 하이브리드(v1): ⑤가 병목 → **2~4개**
- 완전자동(미래): ③·④가 병목 → 보통 **4~8개** (진짜 독립 모듈이면 더)

**설계 반영**: 고정 상한 대신 (a) 리스가 자연히 자기제한 + (b) 모드별 천장만 설정값(`max_active`, 기본 하이브리드 4). 동시성을 늘리는 진짜 레버는 도구가 아니라 **코드 모듈성**임을 문서화.

## `touches` accuracy & 3-layer safety net

- **기본 입도**: 디렉터리/모듈 단위(거칠게 잡아 거짓 병렬 방지). 파일 단위는 옵션.
- **작성 주체**: Classifier(Claude)가 초안 → 사람 승인.
- **오선언 안전망 3중**:
  1. 작업 중 선언 밖 파일을 건드리면 **리스 확장 요청** → 겹치면 일시정지·재직렬화
  2. 통합 게이트의 **테스트**가 회귀 최종 차단
  3. **git 머지**가 물리적 충돌의 마지막 검출 지점

## Edge cases

- **고아 리스**(세션 죽음): heartbeat·worktree 경로로 GC 회수 (csm 연계); 회수 시 `cwo/<id>` 브랜치와 worktree 등록을 best-effort 삭제 → 재투입 시 동일 브랜치명 충돌 없이 클린 재시작 가능
- **의존 순환/데드락**: 분류 시 `depends_on` 순환 검사
- **머지 충돌**: integration에서 rebase, 충돌 시 사람 개입
- **active 폭주**: `max_active` 상한으로 제한
- **작업 중 touches 확장 충돌**: 해당 worktree 일시정지 후 재직렬화
- **다중 프로세스 동시 접근**: `backlog/.lock` 파일 락(`fcntl.flock` 배타 락)으로 변경 명령 경계를 직렬화. 데몬·웹 UI·멀티 세션이 동시에 백로그/LEASES.json을 변경해도 일관성이 보장된다. 기존의 "단일 오케스트레이터 직렬 전제"는 CLI 레벨 동시성에 한해 제거됨 (v1 범위). 읽기 명령은 락을 잡지 않는다.

## Evolution path

- **Phase 1 (v1, 지금)**: 파일 백로그 + 리스 엔진 + 하이브리드 디스패치. 입력=CLI/파일.
- **Phase 2**: 저위험 작업 승인 게이트 자동화 → "대부분 자동". *(첫 번째 Phase-2 증분 구현 완료: `auto_redispatch` config 정책 — `integrate`·`gc` 후 비충돌·auto 작업을 자동 투입하는 스케줄링 루프 자동화. 실행 루프 데몬화는 별도.)* *(두 번째 Phase-2 증분 구현 완료: 오케스트레이션 루프 프로토콜 — `loop-status` 명령(읽기 전용 JSON 스냅샷: counts·active·dispatchable·blocked_auto·needs_approval·loop_can_progress)과 SKILL 루프 절차 문서화. executor = Claude 서브에이전트; cwo는 스케줄링 + 상태 제공 역할 분리.)*
- **Phase 3 (미래지향)**: 웹UI 입력 어댑터 + 백로그 감시 오케스트레이터 데몬 → "등록하고 손 떼면 알아서".

## Testing strategy

- **스크립트 단위 테스트**: 리스 충돌 판정, 상태 전이, GC, 순환 검사.
- **시나리오 테스트**: 등록→분류→투입→충돌대기→머지→리스반납 전체 루프. 동시 다수 작업의 비충돌/충돌 케이스.

## Packaging

- 새 스킬 **`claude-work-orchestrator` (`cwo`)** — csm과 짝.
- csm 일관성 위해 **Python 스크립트 + `SKILL.md` + 슬래시 커맨드** 구성.
- 디렉터리: `claude-skills/claude-work-orchestrator/`.

## Open questions / deferred decisions

- 백로그 위치: 대상 프로젝트 루트의 `backlog/` vs 별도 디렉터리(중앙 registry) — v1은 프로젝트 로컬 가정.
- `cwo` 명칭 확정 (대안 검토 여지).
- worktree 명명 규칙 (`../proj-T-NNN` 가정).
