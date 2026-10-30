# Jira 연동 (ITHD)

ITssue가 티켓을 만드는 Jira Software 스페이스 「ITssue HelpDesk」(키 `ITHD`, 사이트 `itssuehelpdesk.atlassian.net`)입니다.
필드·선택값·상태 ID는 이 사이트 기준이며 `field_mapping.yaml`에 있습니다(2026-10-26에 조회해 맞춤).

접수 1건을 받아 ITHD 티켓을 만들고, Jira가 발급한 ID·키·주소를 돌려줍니다.
담당자 지정·상태 전환·웹훅 해석·담당자 선정·재시도 판단은 아래 "담당자 배정·상태 전환" 절을 봅니다. 이 모듈은 DB와 API 라우트를 쓰지 않습니다(백엔드가 호출).

| 파일 | 하는 일 |
|---|---|
| `field_mapping.yaml` | 필드·선택값·컴포넌트 ID(`fields`·`options`)와 생성 규칙(`create`). Jira 설정이 바뀌면 이 파일만 고칩니다. |
| `mapper.py` | 접수 데이터 → Jira 생성 요청(`fields`) 변환. 네트워크 없음 |
| `client.py` | 중복 확인 → 생성 → `{jira_issue_id, jira_key, jira_url, created}` 반환, 저장값 확인, 토큰 확인(`check_auth`) |
| `smoke_check.py` | 실제 Jira에 붙여 보는 점검 스크립트 (아래 "테스트") |
| `assignment.py` | 담당자 선정(`pick_assignee`): 후보 필터링 + 업무량 비교. 순수 함수 |
| `webhook.py` | Jira 웹훅 본문 해석(`parse_jira_webhook`, 상태·담당자·댓글), 서명 검증(`verify_hub_signature`) |
| `comment_notify.py` | 댓글이 달렸을 때 알림 받을 사번 판별(`route_comment`). 순수 함수 |
| `retry.py` | 실패 뒤 다음 행동 판단(`next_step`): 재시도·결과 조회·관리자 확인 |
| `time_off.py` | 연차·반차 일정에서 지금 부재인 사람 목록(`absent_user_ids`). 순수 함수 |
| `accounts.py` · `jira_accounts.yaml` | 사번 ↔ Jira accountId 연결표(테스트용 6명, 1:1). 값이 비면 Jira 계정 없음으로 봄. `account_id_for`(사번→계정), `employee_no_for`(계정→사번) |

## 사용법

```python
from app.integrations.jira import JiraClient, JiraError

ticket = {                       # 키 이름은 06 테이블 설계서 DB 컬럼 이름 (07 API 계약서)
    "receipt_no": "RCPT-0001",       # 필수
    "title": "VPN 연결이 안 됩니다",   # 필수
    "description": "재택근무 중 VPN 접속이 실패합니다.",
    "category_code": "NET",          # 필수 · ACC ACS NET SW HW SYS SEC
    "urgency": "P2",                 # 필수 · P1 ~ P4
    "group_name": "네트워크팀",        # 필수 · 담당 팀 6개 중 하나
}

with JiraClient.from_env() as jira:
    try:
        result = jira.create_ticket(ticket)
        # → tickets.jira_key = result["jira_key"], jira_sync_status = SYNCED
    except JiraError as e:
        # 접수 기록은 지우지 않는다.
        # result_unknown → jira_sync_status=VERIFYING. 생성 여부 확인 전 자동 재생성 금지.
        # 그 밖의 실패 → 오류별 재시도 또는 NEEDS_ADMIN (07 API 계약서 4장)
        ...
```

- **중복 확인**: 만들기 전에 `ITssue 접수번호`(customfield_10043)로 검색의 모든 페이지를 확인합니다. 이미 있으면 새로 만들지 않고 그 티켓을 돌려줍니다(`created: False`). 생성 요청의 시간 초과·통신 오류·서버 오류는 `result_unknown`, `status=VERIFYING`, `retryable=False`로 반환합니다. 검색 반영 지연·동시 요청까지 원자적으로 막는 것은 아니므로, 백엔드는 접수별 작업 잠금·유일 제약과 결과 대조를 구현해야 합니다.
- **선택 항목**: `request_kind`(INCIDENT·REQUEST·QUESTION), `impact_scope`(PERSONAL·DEPARTMENT·COMPANY), `target_system`, `inquiry_type_code`, `inquiry_type_name`, `category_name`, `requester_employee_no`, `requester_name`, `requester_department_name`, `assignee_name`. 외부 전송 정책(설계서 12장)에서 허용한 것만 넘깁니다.
- **접수 내용**: `description`이 없으면 초안 항목 `summary`·`onset`·`business_impact`·`tried_actions`·`ai_summary`를 제목을 붙여 이어 씁니다. 접수 내용 칸(customfield_10130)은 255자까지이고, 전체 글은 Jira 기본 설명란에 들어갑니다.
- **고정값**: 접수 채널 `챗봇`(CHATBOT), 처리 유형 `티켓`(TICKET), 이슈 유형 `작업`(TASK).
- **계산값**: `urgency` 하나로 우선순위 등급(P2) · Jira 우선순위(High) · 긴급도(High)를 함께 채웁니다. `group_name`은 담당 팀 글 칸과 컴포넌트에 함께 들어갑니다.
- **보고자**: API 토큰 계정이 자동으로 들어갑니다. 문의자는 문의자 사번·이름·부서 칸으로 봅니다.

## 환경 변수 (서버 `.env`에만)

```
JIRA_BASE_URL=https://rlahw5367.atlassian.net
JIRA_EMAIL=<API 토큰을 발급한 Atlassian 계정 이메일>
JIRA_API_TOKEN=<Atlassian API 토큰>
```

Jira Cloud는 이메일 + API 토큰으로 인증합니다. 토큰은 저장소·프론트엔드에 두지 않습니다.

## 테스트

```bash
pytest tests/test_jira_integration.py      # 실제 Jira를 부르지 않음 (모의 응답)
```

실제 Jira 점검 (루트 `.env`에 Jira 변수 3개를 넣은 뒤, 저장소 루트에서):

```bash
python backend/app/integrations/jira/smoke_check.py            # 인증 + 기존 테스트 티켓 확인 (새로 만들지 않음)
python backend/app/integrations/jira/smoke_check.py --create   # 위 + 새 테스트 티켓 1건
python backend/app/integrations/jira/smoke_check.py --flow     # 위 + 담당자 지정·재조회·상태 전환(RDY→WIP→FIN→CLS)까지
python backend/app/integrations/jira/smoke_check.py --reopen   # 새 테스트 티켓으로 FIN→WIP→FIN 재처리를 해 보고 「최종 처리 결과」가 덮어써지는지 확인 (CLS까지 가지 않음)
```

기본 실행은 인증·검색·존재하는 테스트 티켓의 저장값만 확인합니다. 테스트 티켓을 삭제했어도 다시 만들지 않으며 저장값 비교는 생략했다고 표시합니다. 생성·중복 확인은 `--create`를 지정했을 때만 테스트합니다. 새 티켓이 검색에 나타나지 않으면 생성 함수를 재호출하지 않고 점검을 중단합니다. 테스트 티켓은 확인 후 Jira에서 지웁니다.

단순히 몇 초 기다린 것만으로 재생성이 안전해지지는 않습니다. 결과 불명 상태는 기존 생성 여부를 대조하고, 확인할 수 없으면 관리자 확인 대상으로 유지합니다.

## 담당자 배정·상태 전환 (M5-1-3 · M5-3-1)

`JiraClient`에 추가된 함수

| 함수 | 하는 일 |
|---|---|
| `assign_issue(key, account_id)` | 담당자 지정 → 다시 조회해 비교. `{matched, account_id, actual_account_id}` 반환. `matched=False`면 배정을 확정하지 않음 |
| `get_assignee(key)` | Jira에 지금 지정된 담당자 조회 (결과 불명확일 때 확인용) |
| `transition_issue(key, "WIP")` | 업무 상태(RDY·WIP·FIN·CLS) 전환. 이미 그 상태면 보내지 않음(`changed=False`). 허용되지 않는 전환은 `invalid_transition`. **FIN·CLS에서 뒤로 되돌리는 전환은 막되, FIN → WIP(미해결 재처리, SRS JIRA-06)만 허용한다**(CLS는 어디로도 못 돌아감. 그 밖의 끝난 티켓은 다시 열지 않고 새 티켓을 만든다) |
| `get_work_status(key)` | Jira 상태를 RDY·WIP·FIN·CLS로 바꿔 조회 |

두 호출 모두 같은 값으로 다시 불러도 결과가 같게 만들어서(멱등) 시간 초과 뒤 재호출해도 안전합니다.

백엔드가 부르는 방식

```python
from app.integrations.jira import Member, absent_user_ids, pick_assignee, next_step, parse_jira_webhook

# 1) 구성원·업무량을 DB에서 모아 Member 목록으로 만든다 → 오늘 부재자를 빼고 선정
absent = absent_user_ids(time_off_rows, now)        # time_off 표의 행(TimeOff)과 현재 시각(KST)
decision = pick_assignee(members, scenario_id="NET-01", exclude_user_ids=absent)
if decision.selected:        # 예약(assign_status=PENDING) 후 JIRA_ASSIGN 작업 등록
    ...
# 2) 작업 실행 중 JiraError 가 나면 다음 행동을 묻는다
step = next_step(error, attempts=2, elapsed_seconds=120)   # RETRY · VERIFY · NEEDS_ADMIN
# 3) 웹훅(TK-13)
event = parse_jira_webhook(payload, delivery_id=headers.get("X-Atlassian-Webhook-Identifier"))
# 4) 댓글 알림: 웹훅은 신호로만 쓰고 작성자·본문은 Jira에서 다시 읽는다
if event.is_comment_created:
    comment = jira.get_comment(event.issue_key, event.comment.comment_id)    # 읽기 전용, 재시도해도 안전
    route = route_comment(comment["author_account_id"], requester_no=ticket.requester_no,
                          assignee_no=ticket.assignee_no, ignore_account_ids={bot_account_id})
    for emp_no in route.recipient_nos:       # 비어 있으면 알림 없음. route.reason 은 로그용
        ...                                  # 이 사번의 계정에 알림 저장 (화면, 추후 Slack)
```

- **중복 생성 방지**는 `create_ticket`이 이미 합니다(접수번호로 먼저 검색). 이 모듈에서 따로 늘리지 않았습니다.
- **재시도는 판단만** 합니다. 실제로 몇 분 뒤 다시 실행할지(작업 큐)는 백엔드의 `integration_jobs`가 정합니다. `RetryPolicy`의 숫자(3회, 1·5·15분, 결과 조회 15분)는 **제안값**이며 팀 합의 전입니다.
- `pick_assignee`는 팀장·비활성·자동배정 불가·세부 분류 처리 불가·Jira 계정 없음을 후보에서 뺍니다. 부재자는 `exclude_user_ids`로 넘기며, 그 목록은 `time_off.absent_user_ids(일정, 현재시각)`으로 만듭니다(연차는 종일, 오전 반차는 13시 전까지, 오후 반차는 13시부터 부재. 기준 시각은 `half_day_cutoff`로 바꿀 수 있습니다). `time_off` 표와 일정 입력은 백엔드 몫이며 `docs/11.Jira_티켓_담당자_배정_로직.md` 3.1절에 정리했습니다.
- **웹훅 비밀값**: Jira 관리자 웹훅은 비밀값(secret)으로 본문에 서명해 `X-Hub-Signature: sha256=…` 헤더로 보냅니다. `verify_hub_signature(본문 바이트, 헤더, 비밀값)`이 이를 검증합니다. 사용자 정의 헤더(`X-Itssue-Webhook-Secret`)를 Jira 설정에서 넣을 수 있다고는 확인하지 못해서 서명 방식을 기본으로 씁니다. `docs/api/03.접수_연동.md`의 TK-13 헤더 서술은 이에 맞춰 고쳐야 합니다.
- **웹훅 이벤트 ID**: 헤더 값(`delivery_id`) → 변경 이력 ID → 본문 해시 순으로 씁니다. 헤더 이름은 Jira 문서 기준이며 실제 웹훅으로는 아직 확인하지 않았습니다.
- **댓글 알림 받을 사람**: 문의자·담당자는 Jira의 reporter·assignee 가 아니라 ITssue DB 티켓의 사번을 `route_comment`에 넘깁니다(보고자는 API 토큰 계정이고 이관 티켓은 Jira 담당자가 비어 있을 수 있음). 작성자는 사번 연결표로 찾습니다. 문의자가 달면 담당자에게, 담당자가 달면 문의자에게, 둘 다 아닌 사람(팀장·관리자)이 달면 둘 모두에게 가고, 작성자 본인에게는 가지 않습니다. 연결표에 없는 계정(`unknown_author`)과 ITssue 봇 계정(`ignore_account_ids`, `check_auth()["account_id"]`)은 알림을 만들지 않습니다.
- **댓글 이벤트 ID**: 헤더 값 → 변경 이력 ID → `comment:<이벤트>:<댓글ID>:<updated>` → 본문 해시 순입니다. 수정(`comment_updated`)·삭제는 `is_comment_created` 가 False 입니다. 댓글 본문의 멘션(`@이름`)은 글자로만 남기고, 멘션된 사람에게 따로 알리는 일은 하지 않습니다.
- 상태·담당자 값은 웹훅 본문으로 덮어쓰지 않고, 이벤트를 신호로 받아 `get_work_status`·`get_assignee`로 최신값을 읽어 반영합니다(TK-13).
- 되돌림 금지는 ITssue가 보내는 전환만 막습니다(FIN → WIP 한 가지만 예외). Jira 화면에서 직접 되돌리는 것은 Jira 워크플로 설정(전환 권한)으로 제한합니다. FIN → WIP 전환에는 해결 결과(resolution)·해결 일시를 비우는 후처리가 설정돼 있어야 합니다(ITHD-355로 확인, 2026-10-30).
- 사번 연결표(`jira_accounts.yaml`)는 accountId 칸이 비어 있습니다. 팀원의 Jira 프로필 주소 끝 값을 넣습니다.
- **실제 Jira로는 아직 테스트하지 않았습니다.** 특히 워크플로가 RDY→CLS처럼 건너뛰는 전환을 허용하는지, 담당자 지정 권한이 토큰 계정에 있는지는 실제 ITHD에서 확인이 필요합니다.

테스트: `pytest tests/test_jira_assignment.py` (모의 응답 35개), `pytest tests/test_jira_comment.py` (댓글 알림 33개).

## 변경 기록

### 2026-10-19 · `feature/jira-create-ticket` (M5-1-2 티켓 생성)

**추가**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/__init__.py` | 패키지 표시용 빈 파일 |
| `backend/app/integrations/jira/__init__.py` | `JiraClient`·`JiraError`·`MappingError`·`to_jira_fields` 내보내기 |
| `backend/app/integrations/jira/mapper.py` | 접수 데이터 → Jira `fields` 변환, 접수 내용 조합, 필수·코드값 검사 |
| `backend/app/integrations/jira/client.py` | 중복 확인(접수번호 검색) · 생성 · 결과 반환 · `check_saved` · 오류를 `reason`·`retryable`로 분류 |
| `backend/app/integrations/jira/README.md` | 이 문서 |
| `backend/app/integrations/jira/smoke_check.py` | 실제 Jira 점검 스크립트 (토큰 인증 → 기존 테스트 티켓 확인 → `--create` 시 새 1건) |
| `tests/test_jira_integration.py` | 21개 테스트 (변환·코드값·조합·255자·중복·시간 초과·400 오류·저장값 비교·환경 변수·taxonomy 일치·토큰 확인) |

**수정**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/field_mapping.yaml` | 맨 아래 `create` 절 추가(이슈 유형·필수 키·고정값·계산값·제외 키·255자·접수 내용 항목), 머리말에 ITSD 뜻과 테스트 결과. 기존 `fields`·`options`는 그대로 |
| `backend/app/core/config.py` | `JiraSettings`·`get_jira_settings()` 추가 (`JIRA_BASE_URL`·`JIRA_EMAIL`·`JIRA_API_TOKEN`). 기존 `Settings`는 그대로 |
| `.env.example` | Jira 환경 변수 3줄 추가 |
| `requirements.txt` | `httpx==0.28.1`, `PyYAML==6.0.3` 추가 |
| `docs/04.시스템_설계서.md` | 8.3 번호 예시 `ITS-1520` → `ITSD-1520`·키 확정 문장, 16.2 `JIRA_EMAIL` 추가, v0.4 업데이트 로그 1줄 |

**확인**

- 테스트 21개 통과.
- 2026-10-19(이전 사이트, 키 ITSD): 실제 Jira에 테스트 접수 1건(`RCPT-TEST-0001` → ITSD-353)을 만들고, `check_saved()` = `{}`, 접수번호 검색, 같은 접수 재호출 시 `created: False`를 확인했습니다. 이때는 API 토큰이 없어 같은 요청 본문을 로그인 세션으로 보냈습니다.
- 2026-10-20(이전 사이트): 본인 API 토큰으로 `smoke_check.py --create`를 실행해 토큰 인증(`/myself`), 기존 티켓 검색·저장값 비교, 새 티켓 생성(`RCPT-TEST-10200010` → ITSD-354), 같은 접수 재호출 시 `created: False`까지 모두 통과했습니다. 테스트 티켓 ITSD-353·354는 확인 후 Jira에서 지웁니다.

### 2026-10-20 · PR 리뷰 보완

- 검색 다음 페이지에서 발견한 접수도 재사용하고, 접수번호를 255자로 잘라 저장하지 않도록 검사합니다.
- 생성 결과 불명은 VERIFYING으로 구분하고 자동 재생성을 금지합니다. 조회 실패의 재시도 가능 여부와 분리합니다.
- 기본 점검은 조회만 수행하며, 삭제된 테스트 티켓을 다시 생성하지 않습니다.
- 모의 응답 회귀 테스트을 포함한 테스트 27개 통과. 위 실제 Jira 점검 기록과 로컬 회귀 검증 범위를 구분합니다.

### 2026-10-26 · `feature/jira-assignment-webhook` (M5-1-3 · M5-3-1 담당자 지정·상태 전환·웹훅)

**추가**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/assignment.py` | 담당자 선정 `pick_assignee` (후보 필터링, 업무량·마지막 배정 순 정렬) |
| `backend/app/integrations/jira/retry.py` | 재시도 판단 `next_step` (재시도·결과 확인·관리자 확인) |
| `backend/app/integrations/jira/webhook.py` | 웹훅 본문 해석 `parse_jira_webhook`, 서명 검증 `verify_hub_signature` |
| `backend/app/integrations/jira/accounts.py`, `jira_accounts.yaml` | 사번 ↔ Jira 계정 연결표 읽기 (테스트용 6명, 1:1) |
| `backend/app/integrations/jira/time_off.py` | 연차·반차 일정에서 지금 부재인 사람 목록 `absent_user_ids` |
| `tests/test_jira_assignment.py` | 35개 테스트 (모의 응답) |

**수정**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/client.py` | `assign_issue`·`get_assignee`·`transition_issue`·`get_work_status` 추가. 기존 함수는 그대로 |
| `backend/app/integrations/jira/mapper.py` | `work_status_from_jira` 추가 |
| `backend/app/integrations/jira/__init__.py` | 새 함수 내보내기 |
| `backend/app/integrations/jira/README.md` | 이 절과 사용법 |

**확인**

- 테스트 62개 통과 (기존 27개 + 새 35개). 실제 Jira는 호출하지 않았습니다.

### 2026-10-26 · `feature/jira-smoke-flow` (실제 Jira 점검 · FIN 전환에 최종 처리 결과 추가)

**추가·수정**

| 파일 | 내용 |
|---|---|
| `smoke_check.py` | `--flow` 추가: 테스트 티켓 생성 → 담당자 지정 → 재조회 비교 → RDY→WIP→FIN→CLS 전환, RDY→CLS 건너뛰기 거부와 CLS→WIP 되돌림 차단 확인 |
| `client.py` | `transition_issue(..., final_result=)` 추가. FIN 으로 옮길 때 최종 처리 결과를 Jira 문서 형식(ADF)으로 함께 보낸다. 비어 있으면 Jira를 부르기 전에 `invalid_fields` |
| `field_mapping.yaml` | `transition_fields.final_result`(customfield_10069, FIN 필수) 추가 |
| `tests/test_jira_assignment.py` | FIN 전환 본문 검증, 최종 처리 결과 누락 검증 추가 (테스트 63개) |

**실제 Jira 확인 (본인 토큰, ITHD)**

- 인증, 티켓 생성(저장값 차이 없음), 같은 접수 재호출 시 중복 없음, 담당자 지정 후 재조회 일치(토큰 계정의 담당자 지정 권한 확인), RDY→WIP 전환 정상.
- RDY→CLS 바로 전환은 거부됨. 전환은 한 단계씩만 가능하다.
- WIP→FIN 은 최종 처리 결과 없이는 거부됨 → 이번 수정으로 해결. 수정 후 FIN·CLS 전환은 `--flow` 재실행으로 확인한다.

### 2026-10-26 · `feature/jira-mapping-ithd` (새 사이트 ITHD 기준으로 ID 교체)

**수정**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/field_mapping.yaml` | 프로젝트 `ITSD`(10007) → `ITHD`(10001). 사용자 지정 필드 24개, 분류·영향 범위·긴급도 선택값, 컴포넌트, 이슈 유형(작업 10010), 상태(RDY 10004 · WIP 10005 · FIN 10006 · CLS 10007) ID를 새 사이트 조회 값으로 교체 |
| `tests/test_jira_integration.py`, `tests/test_jira_assignment.py` | 위 ID에 맞춰 기대값 변경 |
| `backend/app/integrations/jira/*.py`, `README.md`, `app/core/config.py`, `.env.example` | 프로젝트 키·필드 번호 표기 변경 |
| `docs/01~04`, `docs/api/03`, `docs/11`, `design/` 문서·프로토타입, `frontend/` 목업·테스트 | Jira 키 표기 `ITSD` → `ITHD` (예시 번호·목업 데이터만, 동작 변경 없음) |

**확인**

- 테스트 62개 통과(모의 응답). 새 사이트에서 티켓 생성·담당자 지정은 아직 실행하지 않았습니다.
- 새 사이트에 있는 `최종 처리 결과`(customfield_10069)는 이 PR에서 매핑에 넣지 않았습니다.

### 2026-10-26 · Jira 댓글 알림 (Jira 쪽 순수 함수)

**추가**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/comment_notify.py` | 알림 받을 사번 판별 `route_comment`, 결과 `CommentRoute(recipient_nos, reason)` |
| `tests/test_jira_comment.py` | 33개 테스트 (모의 응답) |

**수정**

| 파일 | 내용 |
|---|---|
| `webhook.py` | 댓글 이벤트 읽기: `WebhookComment`, `WebhookEvent.comment`·`is_comment_created`, 댓글 이벤트 ID. 기존 상태·담당자 해석은 그대로 |
| `client.py` | `get_comment(issue_key, comment_id)` 추가 (읽기 전용) |
| `mapper.py` | `adf_to_text` 추가 (댓글 본문 ADF → 글자) |
| `accounts.py` | `employee_no_for` 추가 (accountId → 사번) |
| `__init__.py` | 새 이름 내보내기 |

**하지 않은 것 (백엔드 몫)**: 수신 라우트(`POST /webhooks/jira`), 이벤트 저장·중복 거르기, `notifications` 컬럼 확장·마이그레이션, 알림 조회·읽음 API, 화면 연결, Slack 발송.

**확인**

- 테스트 96개 통과 (기존 63개 + 새 33개). 실제 Jira는 호출하지 않았고, 댓글 이벤트 본문과 `GET /rest/api/3/issue/{key}/comment/{id}` 응답은 Atlassian 문서 형식을 기준으로 만든 모의값입니다. 실제 ITHD 웹훅으로 `comment_created` 본문(`comment.author.accountId` 등)을 한 번 확인해야 합니다.
