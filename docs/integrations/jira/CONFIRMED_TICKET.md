# 확정 접수 → Jira 티켓 생성 연결

기준: TK-04 `Ticket` 응답과 기존 `JiraClient.create_ticket`.

## 추가 파일 3개

| 저장소 기준 위치 | 역할 |
|---|---|
| `backend/app/integrations/jira/confirmed_ticket.py` | 확정 접수 변환·상태 확인·기존 Jira 생성 함수 호출 |
| `tests/test_jira_confirmed_ticket.py` | 모의 HTTP로 생성·재사용·누락·실패 처리 검증 |
| `docs/integrations/jira/CONFIRMED_TICKET.md` | 입력·호출 방법·백엔드 연결 조건 |

기존 파일과 `__init__.py`는 수정하지 않는다. 새 모듈에서 직접 import한다.
**기존 접수 키·DB 컬럼·API·서버 파일은 변경하지 않는다.**

## 입력 규칙

브라우저가 보낸 `{draftId, draftUpdatedAt}`를 받는 함수가 아니다. 서버가 인증·초안 버전 확인·접수 확정·DB 커밋을 마친 뒤, **저장된 접수에서 구성한 TK-04 Ticket 형식**을 넘긴다. JSON 모양만으로 실제 접수 확정 여부를 증명할 수 없으므로 외부 요청 본문을 직접 넘기지 않는다.

| Ticket 값 | Jira 입력 | 처리 |
|---|---|---|
| `id`, `draftId` | 결과 연결용 | 양의 정수 필요 |
| `receiptNo` | `receipt_no` | 필수, 255자 초과 시 거부 |
| `summary` | `title` | 필수, 제목은 기존 255자 제한 적용·전체 요약은 본문 보존 |
| `categoryCode`, `urgency` | `category_code`, `urgency` | 현재 매핑의 코드 사용, 누락·미등록 값 거부 |
| `groupId`, `group.id`, `group.name` | `group_name` | 두 ID 일치, 현재 Jira 매핑에 있는 그룹 이름 필요 |
| `targetSystem`, `symptom`, `occurredAt`, `businessImpact`, `triedActions`, `urgencyReason` | `description` | 값이 있는 항목만 제목과 함께 본문 구성 |
| `requester.employeeNo`, `requester.name` | 문의자 사번·이름 | 선택, 계약에 있는 항목만 전달 |
| `jiraSyncStatus`, `jiraKey` | 실행 조건 | 아래 기준 적용 |

분류·긴급도·그룹을 임의로 채우거나 다른 그룹으로 바꾸지 않는다. API 계약상 nullable인 값은 저장될 수 있지만, 현재 Jira 생성 규칙을 충족하지 않으면 생성은 중단한다. 담당자 자동 선정·개인 배정은 포함하지 않는다.

## 호출 예

아래 `saved_ticket`은 서버가 DB 커밋 후 읽은 값이라는 전제다. 실제 연결 위치는 백엔드 담당자가 확정한다.

```python
from app.integrations.jira.client import JiraClient
from app.integrations.jira.confirmed_ticket import create_from_confirmed_ticket

saved_ticket = {
    "id": 42,
    "draftId": 55,
    "receiptNo": "RCPT-0042",
    "summary": "VPN 접속 오류",
    "categoryCode": "NET",
    "urgency": "P2",
    "groupId": 3,
    "group": {"id": 3, "name": "네트워크팀"},
    "symptom": "인증 서버 연결 실패",
    "occurredAt": "오늘 오전",
    "businessImpact": "사내 시스템 접속 불가",
    "triedActions": "재설치",
    "jiraSyncStatus": "PENDING",
    "jiraKey": None,
}

with JiraClient.from_env() as jira:
    result = create_from_confirmed_ticket(jira, saved_ticket)
# result: ticket_id, receipt_no, jira_issue_id, jira_key, jira_url, created, source
# 백엔드가 result["jira_key"]를 같은 접수에 저장하고 연동 작업 완료를 기록한다.
```

인증정보는 기존 서버 설정을 사용한다. 실제 토큰·로컬 설정은 저장소에 포함하지 않는다.

기존 Jira 반환값(`jira_issue_id`, `jira_key`, `jira_url`, `created`)에 아래 항목만 추가한다. 새 DB 컬럼이 아니다.

| 추가 반환 키 | 의미 |
|---|---|
| `ticket_id` | 결과를 연결할 내부 접수 ID |
| `receipt_no` | 내부 접수번호 |
| `source` | `jira`: 생성/검색 결과, `saved_ticket`: DB에 이미 저장된 키 |

## 중복·실패 처리 및 남은 연결

- 저장된 `jiraKey`가 있으면 Jira를 호출하지 않고 반환한다(`source=saved_ticket`, `created=False`, `jira_issue_id=None`). 전달받은 `jiraUrl` 대신 서버 주소에서 URL을 만든다.
- Jira 키가 없으면 `PENDING`만 생성 가능하다. `VERIFYING`·`NEEDS_ADMIN`·키 없는 `SYNCED`에서는 생성하지 않는다.
- 기존 클라이언트가 접수번호로 Jira를 검색해 발견하면 재사용한다(`source=jira`, `created=False`). 검색 지연·동시 실행까지 중복을 보장하지는 않는다.
- `ConfirmedTicketError`: 입력·저장 상태 오류(`reason`, `fields`). 기존 `JiraError`: Jira 오류. 두 오류 모두 호출자에게 전달하고 성공으로 바꾸지 않는다.
- 생성 요청의 시간 초과 등 `JiraError.reason=result_unknown`은 백엔드가 `VERIFYING`으로 저장한다. 기존 생성 여부를 대조하기 전 재생성하지 않는다.
- **백엔드 필수 연결**: 접수별 작업 잠금/단일 실행, DB 확정값 조회·그룹 ID/이름 구성, 성공한 Jira 키의 즉시 저장, 실패·결과 불명 기록과 복구. 이 모듈은 DB·작업 큐·API 등록을 변경하지 않는다.
- 생성 성공 응답은 Jira 저장값 재조회·DB 저장·개인 배정까지 검증했다는 뜻이 아니다. 실제 환경에서는 기존 `check_saved`를 이용한 필드 확인도 별도로 한다.

## 검증 결과

- 신규 30개 + 기존 Jira 129개 = **159개 통과**. 모의 HTTP 응답으로 실행했으며 실제 Jira 티켓은 생성하지 않았다.
- 새 시험: 현재 ITHD 필드 변환, 본문 보존, 기존 Jira 키/검색 결과 재사용, 미확정 초안 거부, 누락·잘못된 코드·그룹 불일치, 인증 실패, 생성 시간 초과 시 재호출 없음.
- 실행: 저장소 루트에서 `PYTHONPATH=backend python -m pytest tests -q`.
- 운영 접수 API부터 DB까지의 통합 시험은 아직 하지 않았다.
