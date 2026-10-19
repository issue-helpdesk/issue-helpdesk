# Jira 연동 (ITSD)

**ITSD = IT Service Desk (IT 서비스 데스크).** ITssue가 티켓을 만드는 Jira Software 스페이스 "ITssue HelpDesk"의 키입니다.
예전 JSM 프로젝트 `ITS`는 과거 이력 보관용이고, 연동은 `ITSD`만 씁니다. (예전 키 `HELP`는 Jira에 별칭으로만 남아 있습니다.)

접수 1건을 받아 ITSD 티켓을 만들고, Jira가 발급한 ID·키·주소를 돌려줍니다.
자동배정·상태 전환·재시도는 아직 없습니다(다음 단계).

| 파일 | 하는 일 |
|---|---|
| `field_mapping.yaml` | 필드·선택값·컴포넌트 ID(`fields`·`options`)와 생성 규칙(`create`). Jira 설정이 바뀌면 이 파일만 고칩니다. |
| `mapper.py` | 접수 데이터 → Jira 생성 요청(`fields`) 변환. 네트워크 없음 |
| `client.py` | 중복 확인 → 생성 → `{jira_issue_id, jira_key, jira_url, created}` 반환, 저장값 확인, 토큰 확인(`check_auth`) |
| `smoke_check.py` | 실제 Jira에 붙여 보는 점검 스크립트 (아래 "시험") |

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

- **중복 확인**: 만들기 전에 `ITssue 접수번호`(customfield_10113)로 검색의 모든 페이지를 확인합니다. 이미 있으면 새로 만들지 않고 그 티켓을 돌려줍니다(`created: False`). 생성 요청의 시간 초과·통신 오류·서버 오류는 `result_unknown`, `status=VERIFYING`, `retryable=False`로 반환합니다. 검색 반영 지연·동시 요청까지 원자적으로 막는 것은 아니므로, 백엔드는 접수별 작업 잠금·유일 제약과 결과 대조를 구현해야 합니다.
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

## 시험

```bash
pytest tests/test_jira_integration.py      # 실제 Jira를 부르지 않음 (가짜 응답)
```

실제 Jira 점검 (루트 `.env`에 Jira 변수 3개를 넣은 뒤, 저장소 루트에서):

```bash
python backend/app/integrations/jira/smoke_check.py            # 인증 + 기존 시험 티켓 확인 (새로 만들지 않음)
python backend/app/integrations/jira/smoke_check.py --create   # 위 + 새 시험 티켓 1건
```

기본 실행은 인증·검색·존재하는 시험 티켓의 저장값만 확인합니다. 시험 티켓을 삭제했어도 다시 만들지 않으며 저장값 비교는 생략했다고 표시합니다. 생성·중복 확인은 `--create`를 지정했을 때만 시험합니다. 새 티켓이 검색에 나타나지 않으면 생성 함수를 재호출하지 않고 점검을 중단합니다. 시험 티켓은 확인 후 Jira에서 지웁니다.

단순히 몇 초 기다린 것만으로 재생성이 안전해지지는 않습니다. 결과 불명 상태는 기존 생성 여부를 대조하고, 확인할 수 없으면 관리자 확인 대상으로 유지합니다.

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
| `backend/app/integrations/jira/smoke_check.py` | 실제 Jira 점검 스크립트 (토큰 인증 → 기존 시험 티켓 확인 → `--create` 시 새 1건) |
| `tests/test_jira_integration.py` | 21개 시험 (변환·코드값·조합·255자·중복·시간 초과·400 오류·저장값 비교·환경 변수·taxonomy 일치·토큰 확인) |

**수정**

| 파일 | 내용 |
|---|---|
| `backend/app/integrations/jira/field_mapping.yaml` | 맨 아래 `create` 절 추가(이슈 유형·필수 키·고정값·계산값·제외 키·255자·접수 내용 항목), 머리말에 ITSD 뜻과 시험 결과. 기존 `fields`·`options`는 그대로 |
| `backend/app/core/config.py` | `JiraSettings`·`get_jira_settings()` 추가 (`JIRA_BASE_URL`·`JIRA_EMAIL`·`JIRA_API_TOKEN`). 기존 `Settings`는 그대로 |
| `.env.example` | Jira 환경 변수 3줄 추가 |
| `requirements.txt` | `httpx==0.28.1`, `PyYAML==6.0.3` 추가 |
| `docs/04.시스템_설계셔.md` | 8.3 번호 예시 `ITS-1520` → `ITSD-1520`·키 확정 문장, 16.2 `JIRA_EMAIL` 추가, v0.4 업데이트 로그 1줄 |

**확인**

- 테스트 21개 통과.
- 2026-10-19: 실제 ITSD에 시험 접수 1건(`RCPT-TEST-0001` → ITSD-353)을 만들고, `check_saved()` = `{}`, 접수번호 검색, 같은 접수 재호출 시 `created: False`를 확인했습니다. 이때는 API 토큰이 없어 같은 요청 본문을 로그인 세션으로 보냈습니다.
- 2026-10-20: 본인 API 토큰으로 `smoke_check.py --create`를 실행해 토큰 인증(`/myself`), 기존 티켓 검색·저장값 비교, 새 티켓 생성(`RCPT-TEST-10200010` → ITSD-354), 같은 접수 재호출 시 `created: False`까지 모두 통과했습니다. 시험 티켓 ITSD-353·354는 확인 후 Jira에서 지웁니다.

### 2026-10-20 · PR 리뷰 보완

- 검색 다음 페이지에서 발견한 접수도 재사용하고, 접수번호를 255자로 잘라 저장하지 않도록 검사합니다.
- 생성 결과 불명은 VERIFYING으로 구분하고 자동 재생성을 금지합니다. 조회 실패의 재시도 가능 여부와 분리합니다.
- 기본 점검은 조회만 수행하며, 삭제된 시험 티켓을 다시 생성하지 않습니다.
- 모의 응답 회귀 시험을 포함한 테스트 27개 통과. 위 실제 Jira 점검 기록과 로컬 회귀 검증 범위를 구분합니다.
