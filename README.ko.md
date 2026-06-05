# Claude Work Orchestrator (`cwo`)

**한 프로젝트에서 여러 작업을 충돌 없이 병렬로** 처리하는 도구.

`cwo`는 파일 기반 작업 오케스트레이터입니다. 요구사항·버그·이슈를 백로그에 등록하면, 각 작업을 자체 git worktree에 격리하고 **영향범위 리스(ownership lease)** 로 두 작업이 같은 코드 영역을 동시에 건드리지 못하게 막습니다. 독립 작업은 병렬로, 충돌할 작업은 자동으로 직렬화됩니다.

> 짝 도구: **csm**(claude-session-manager)는 실행 중인 *세션*을 추적합니다. `cwo`는 *작업*을 관리합니다.

[English README](./README.md)

---

## 왜 필요한가

- LLM CLI에 요구사항을 하나씩 넣으면 순차 처리라 비효율적입니다.
- 같은 작업 디렉터리에서 터미널을 여러 개 열면 파일·git index·빌드·머지 충돌이 납니다.

`cwo`는 두 가지 발상으로 해결합니다:

1. **등록(capture)과 투입(dispatch)의 분리** — 떠오르면 언제든 무마찰로 백로그에 던지고, 실행 진입은 통제된 관문을 통과할 때만.
2. **영향범위 리스** — active 작업은 자기 코드 영역(`touches`)에 대해 쓰기 리스를 쥡니다. 새 작업은 그 영역이 어떤 활성 리스와도 겹치지 않을 때만 투입됩니다. 충돌이 코드 작성 *전에* 구조적으로 차단됩니다.

---

## 요구사항

- **Python 3.13+** — 표준 라이브러리만 사용, **무의존성**.
- **git** — `dispatch`/`integrate`(worktree·머지)에 필요.
- **대상 프로젝트**는 `main` 브랜치를 가진 git 저장소여야 하고, 빌드/테스트 아티팩트(`__pycache__/`, `*.pyc` 등)를 `.gitignore`해야 합니다. `cwo init`이 `.gitignore` 없으면 경고합니다.

---

## 설치

```bash
./install.sh
```

(재실행 가능한) 설치 스크립트가 스킬을 `~/.claude/skills/`에 링크하고(Claude Code 인식), **`cwo` 명령**을 PATH 디렉터리(`~/.local/bin` 우선)에 심링크합니다. Python(3.9+) 확인과 동작 검증까지 합니다. 제거는 `./install.sh --uninstall`.

수동 설치:

```bash
ln -s "$(pwd)" ~/.claude/skills/claude-work-orchestrator                  # 스킬 인식
alias cwo='python3 /절대경로/claude-work-orchestrator/scripts/cwo.py'      # CLI
```

아래 예시는 `cwo`가 PATH에 있다고 가정합니다(없으면 `python3 scripts/cwo.py`).

---

## 빠른 시작

```bash
# 대상 git 프로젝트에서:
cwo --root ~/myapp init                          # backlog/ 생성

# 1) 작업을 언제든 등록 (무마찰)
cwo --root ~/myapp add "환불 음수금액 버그" --type bug --priority high   # -> T-001
cwo --root ~/myapp add "장바구니 UI 개편"                                # -> T-002

# 2) 분류: 각 작업이 건드릴 영역 선언 (+ 자동 투입 허용)
cwo --root ~/myapp classify T-001 --touches payment/ --auto
cwo --root ~/myapp classify T-002 --touches ui/ --auto

# 3) 비충돌·독립 작업을 격리 worktree로 투입
cwo --root ~/myapp dispatch-auto                 # T-001, T-002 병렬 투입

# 4) 각 worktree(예: ~/myapp-T-001)에서 작업 후 통합
cwo --root ~/myapp integrate T-001               # 테스트 -> 머지 -> 리스 반납 -> done
```

---

## 충돌은 어떻게 막히나

리스는 `{task, touches, worktree, heartbeat}`를 기록합니다. `touches` 겹침은 **경로 계층** 기준입니다:

- `payment/` 는 `payment/refund.py` 와 겹침 (디렉터리가 조상).
- `payment` 는 `payment2` 와 안 겹침 (경로 경계 인식).

새 작업의 `touches`가 활성 리스와 겹치면 **투입되지 않고** `ready`에서 대기합니다. 리스 보유 작업이 통합(또는 `gc` 회수)되면 영역이 풀리고, 대기 작업은 *갱신된* `main`에서 분기되어 투입됩니다(이전 변경 위에 쌓이므로 머지 충돌 없음).

작업의 전체 `touches`를 dispatch 시점에 한 번에 획득하므로(hold-and-wait 없음) 리스 방식은 **데드락이 없습니다**.

---

## 명령 레퍼런스

`--root <PROJ>` 로 대상 프로젝트 지정 (기본 `.`).

| 명령 | 용도 |
|---|---|
| `init [--auto-redispatch]` | `backlog/` 생성. `--auto-redispatch`로 자동 모드. |
| `add "<제목>" [--type] [--source] [--priority]` | 작업 등록(`inbox`로). |
| `classify <id> [--touches ...] [--depends-on ...] [--auto]` | touches/의존 설정 후 `ready`로. |
| `list [--status <s>]` | 작업 목록(상태별 필터). |
| `leases` | 활성 리스(점유 영역). |
| `check <id>` | 지금 투입 가능한가? (exit 0/1) |
| `dispatch <id>` | worktree 생성 + 리스 획득 + `active`. |
| `dispatch-auto` | `auto`·비충돌·의존완료 작업 일괄 투입. |
| `integrate <id>` | 테스트 게이트 → 머지 → 리스 반납 → `done` (exit 0/1). |
| `gc` | 고아 리스 회수(죽은 세션 / stale heartbeat). |
| `heartbeat <id>` | active 작업의 리스 heartbeat 갱신. |
| `loop-status` | 오케스트레이션 루프용 JSON 상태. |
| `run [--executor CMD] [--max-iters N] [--max-parallel N] [--dry-run]` | 무인 자율 루프. |
| `serve [--host] [--port] [--token]` | 읽기/쓰기 웹 대시보드. |

### 작업 레코드 (`backlog/<status>/T-NNN.json`)

```json
{
  "id": "T-042", "title": "...", "type": "bug",
  "source": "human", "touches": ["payment/refund.py"], "depends_on": [],
  "status": "inbox", "priority": "high", "auto": false, "worktree": null
}
```

상태: `inbox → ready → active → (integrating) → done`. `integrating`은 `active/` 디렉터리를 공유합니다.

---

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

- `max_active` — 동시 작업 상한.
- `test_command` — 통합 게이트. 이게 통과해야만 머지(worktree에서 실행).
- `auto_redispatch` — `true`면 `integrate`/`gc` 후 막혔던 작업을 자동 투입.

---

## 동시성 모델

충돌 *안전성*은 리스가 보장합니다(활성 리스는 서로 겹치지 않음). 실제 병렬 *개수*는 다섯 병목의 최솟값입니다: 독립 코드 영역(모듈성), 공유 초크포인트, 머지 대역폭, 머신 자원, (하이브리드 한정) 사람 검토. 하이브리드는 보통 **2~4개**(`max_active`). 병렬성을 늘리는 진짜 레버는 도구가 아니라 **코드 모듈성**입니다.

변경 명령은 `backlog/.lock`에 배타적 `flock`을 잡아 다중 프로세스(데몬/웹/세션)의 일관성을 지킵니다. `integrate`는 (느린) 테스트를 *락 없이* 실행하고, 머지/리스 반납 임계구역만 락을 보유합니다.

---

## 웹 대시보드 (`cwo serve`)

```bash
cwo --root ~/myapp serve --port 8787
# http://127.0.0.1:8787  열기   (토큰은 시작 시 출력됨)
```

- 작업(상태별)·활성 리스·loop 상태를 실시간 폴링으로 표시.
- 등록/분류/dispatch/dispatch-auto/integrate/gc를 버튼으로 실행.
- localhost 전용. 쓰기 엔드포인트는 시작 시 토큰과 일치하는 `X-CWO-Token` 헤더 필요(CSRF 방지); 페이지에 토큰이 주입되어 정상 쓰기는 동작. `--token`으로 고정 토큰 지정.

## TUI (`cwo watch`)

```bash
cwo --root ~/myapp watch
```

`cwo --root <PROJ> watch` 명령으로 인터랙티브 터미널 UI를 실행합니다(stdlib curses, 무의존성) — 실시간 뷰 + 키 바인딩(d dispatch, i integrate, a dispatch-auto, g gc, q quit).

---

## 무인 데몬 (`cwo run`) — 고위험

`loop-status → dispatch-auto → executor(worktree) → integrate` 를 진행 여지가 없을 때까지 자동 반복합니다.

```bash
cwo --root ~/myapp run --executor 'claude -p "$CWO_PROMPT"' --dry-run   # 먼저 미리보기!
cwo --root ~/myapp run --executor 'claude -p "$CWO_PROMPT"' --max-parallel 4
```

- **executor**가 각 worktree에서 실제 코딩을 합니다. 프롬프트는 환경변수(`$CWO_PROMPT`, `$CWO_TASK_ID`, `$CWO_WORKTREE`)로 전달 — 셸 문자열에 보간하지 않음(인젝션 안전).
- executor는 **병렬 실행**(`--max-parallel`, 기본 4), `integrate`는 직렬(main 머지는 동시 불가).
- **안전장치**: executor 미지정 시 실행 거부(또는 `--dry-run`); `--max-iters` 상한; 각 작업 1회 실행(종료 보장); 진짜 테스트 게이트가 모든 머지를 보호; 실패 작업은 `active`로 남겨 사람이 처리.
- ⚠️ 무인으로 코드를 생성하고 `main`에 자동 머지합니다. 신뢰된 환경 + 충분한 테스트 게이트와 함께만 사용. 헤드리스 `claude` 인증·비용은 사용자 책임.

---

## 트리아지: 발견된 작업

active 작업 중 새 이슈를 발견하면 **즉시 고치지 말고** 먼저 분류:

- 현재 작업에 **Blocking** → 현재 worktree에서 처리(별도 커밋).
- **무관** → 백로그에 등록(`add ... --source "discovered(from: T-038)"`), 현재 브랜치에 안 섞음.

백로그가 단일 진실 공급원이고, worktree는 발견 작업을 백로그로 *되먹입니다*.

---

## 아키텍처

```
scripts/
  paths.py     # touches 겹침 판정(충돌 감지)
  config.py    # 설정 로드
  backlog.py   # 작업 레코드 + 상태 디렉터리 전이
  lease.py     # 영향범위 리스 + 충돌 게이트
  lock.py      # flock 기반 프로젝트 락
  dispatch.py  # can_dispatch + dispatch(worktree) + dispatch_auto + loop_status
  integrate.py # 통합 게이트(테스트 -> 머지 -> 반납)
  cwo_gc.py    # 고아 리스 회수
  runner.py    # 무인 실행 루프(병렬 executor)
  web.py       # 대시보드(http.server, 읽기+쓰기+토큰)
  tui.py       # 인터랙티브 터미널 UI(curses)
  cwo.py       # CLI 엔트리
tests/         # pytest(stdlib), 92개
SKILL.md       # Claude 오케스트레이터용 프로토콜
design.md      # 설계 스펙    plan.md  # 구현 계획
```

백로그(파일)가 안정적 계약이고, 입력 어댑터(CLI·웹)와 디스패치 정책(하이브리드·자동)이 그 위에 얹혀 교체 가능 — 엔진은 안 바뀝니다.

---

## 상태

- **Phase 1 — 엔진**: 파일 백로그 · 영향범위 리스 · 하이브리드 디스패치 · 통합 게이트 · gc.
- **Phase 2 — 자동화**: auto-redispatch · 의존 순환 검사 · heartbeat · loop-status · 오케스트레이션 루프(Claude 서브에이전트가 worktree에서 실행).
- **Phase 3 — 운영**: 동시성 락 · 웹 대시보드(읽기+쓰기+토큰 인증) · 무인 데몬(병렬·가드레일).

stdlib 전용, 92개 테스트 통과.
