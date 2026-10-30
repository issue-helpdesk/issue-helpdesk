# M5-1-3 담당자 배정 연결

생성된 Jira 티켓에 백엔드가 정한 담당자를 지정하고 재조회한다. 후보 전체의 선정·DB·API 구현은 포함하지 않는다.

## 기준과 수정 사항

기준: 기획안 Assign-Rules·Assign-Tasks, [TK-09](../../api/03.접수_연동.md#tk-09-담당자-지정재배정), [배정 명세 2.4·2.6·3.1](../../11.Jira_티켓_담당자_배정_로직.md).

| 항목 | 적용 규칙 |
|---|---|
| 상태 제한 | TK-09대로 CLS만 제한. FIN을 일괄 차단하지 않음 |
| 최초 자동배정 | 기존 담당자가 없을 때 지정. 이미 목표 계정이면 재지정 없이 확인, 다른 계정이면 보호 |
| 승인된 재배정 | 서버의 재배정 작업 정보로 순번·이전 계정을 대조한 뒤 기존 담당자 변경 허용 |
| 예약 | 기획안에 있는 절차이므로 유지. 저장된 assigneeId·그룹이 대상자와 일치해야 함 |
| 자동·수동 자격 | 활성·구성원·assignable·Jira 계정·세부 유형 자격은 공통. 자동은 팀장·부재 제외, 사유를 받은 수동 지정에는 자동 전용 제외를 적용하지 않음 |

신규 파일은 `ticket_assignment.py`, `test_jira_ticket_assignment.py`, 이 문서 3개다. 기존 Jira 함수·민경님 코드·DB 모델·API 등록은 수정하지 않는다.

## 서버 호출 순서

1. 서버가 접수와 대상 그룹의 구성원을 조회·검증한다. 재배정은 TK-09의 요청자 권한·그룹 변경 권한·사유·활성 작업 충돌도 검사한다.
2. Jira 생성 결과를 DB에 저장하고, 대상자·그룹·PENDING 예약과 연동 작업을 저장한다. 재배정 시 assignment_revision을 증가시키고 작업 payload에 보존한다.
3. 서버가 접수별 실행을 직렬화하고, 최신 DB 순번과 작업 순번을 읽어 아래 함수를 호출한다. 외부 요청 JSON을 직접 전달하지 않는다.
4. Jira 재조회가 일치하면 서버가 배정을 확정한다. 실패·불일치·결과 불명 기록과 예약 처리는 서버가 담당하며 접수·Jira 키를 보존한다.

```python
from app.integrations.jira.ticket_assignment import (
    AssignmentTarget, ReassignmentContext, assign_confirmed_ticket,
)

# 실제 조회한 그룹 소속·서비스 역할을 사용한다.
target = AssignmentTarget(group_id=saved_ticket["groupId"], member=member,
                          service_role=member_service_role)

# 최초 자동배정: 재배정 정보를 전달하지 않는다.
result = assign_confirmed_ticket(jira, saved_ticket, target,
                                 exclude_user_ids=absent_ids)

# 승인된 재배정 작업 실행: 서버의 저장된 작업·DB 값으로 구성한다.
context = ReassignmentContext(
    expected_account_id=job_expected_account_id,
    revision=job_revision,
    current_revision=latest_db_revision,
    reason=approved_reason,
    manual=is_explicit_manual_selection,
)
result = assign_confirmed_ticket(jira, saved_ticket, target,
                                 exclude_user_ids=absent_ids,
                                 reassignment=context)
```

두 호출 예는 서로 다른 작업의 사용법이다. 같은 작업에서 연속 호출하지 않는다. `manual`은 기존 TK-09 요청의 개인 직접 지정 여부를 서버가 보존한 값이며 새 API 요청 필드가 아니다. `assigneeId=null`로 요청한 자동 재선정은 false로 실행한다.

## 입력·보호 범위

- 저장된 Ticket의 id·groupId·assigneeId, 현재 ITHD jiraKey, jiraSyncStatus=SYNCED, assignStatus=PENDING/ASSIGNED, inquiryType.code를 사용한다. ASSIGNED는 재조회용이며 이미 끝난 배정 작업을 다시 쓰지 않는다.
- AssignmentTarget은 기존 Member와 그룹 ID·서비스 역할을 담는다. 실제 소속·활성 그룹과 계정 매핑의 진위는 백엔드 조회·권한 검사로 보장한다. 이 함수가 요청자 권한을 승인하는 것은 아니다.
- 재배정의 expected_account_id는 작업 승인 시점의 이전 Jira 계정(미배정이면 None)이다. 실행 시점 조회값으로 임의 교체하지 않는다. revision이 현재 DB 순번과 다르면 StaleAssignmentError로 Jira 호출 없이 중단하고, 현재 배정 상태를 덮어쓰지 않는다.
- 현재 Jira 담당자가 이미 목표 계정이면 PUT 없이 성공을 확인한다. 이전 계정과 예상이 다르면 변경하지 않고 NEEDS_ADMIN을 반환한다. 완료된 ASSIGNED 작업도 다른 계정으로 다시 덮어쓰지 않는다.
- 지정 후 재조회가 일치해야 ASSIGNED를 반환하며 db_updated는 항상 false다. JiraError는 그대로 전달한다. 시간 초과는 예약·키를 유지하고 먼저 조회하며 자동 재시도하지 않는다.
- 조회와 PUT 사이의 동시 변경을 Jira의 원자적 비교·갱신으로 막는 기능은 없다. 서버의 실행 직렬화·최신 순번 검사·웹훅 대조가 필요하며, 이 함수만으로 완전한 동시 변경 방지를 보장하지 않는다.

## 검증과 남은 작업

배정 연결 53개 + 기존 Jira 171개 = **224개 통과**(모의 HTTP). 생성→같은 키에 지정→재조회, FIN 허용·CLS 차단, 기존 담당자 보호, 승인 재배정, 오래된 작업·예상 계정 불일치 차단, 자동·수동 자격, 실패 전파를 확인했다.

실제 Jira 담당자 변경·운영 DB·TK-09 API 연결은 아직 실행하지 않았다. 따라서 M5-1-3 전체 완료가 아니다. DB 후보·업무량 조회, 예약·잠금·revision 저장과 권한 API는 백엔드 연결 작업으로 남는다.
