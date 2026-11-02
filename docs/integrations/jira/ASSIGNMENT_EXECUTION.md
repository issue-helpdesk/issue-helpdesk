# Jira 배정 작업 실행

민경님 PR #174의 `reserve_assignment()`가 저장한 JIRA_ASSIGN 작업을 실행합니다. 후보를 다시 고르거나 공용 배정 함수를 수정하지 않습니다.

## 처리 범위

| 상황 | 처리 |
|---|---|
| Jira 미배정 | 현재 예약·공통 자격 확인 → 지정 → 상태·담당자 재조회 → ASSIGNED 저장 |
| 이미 같은 담당자 | PUT 없이 확인·저장 |
| 다른 담당자가 있음 | 덮어쓰지 않고 NEEDS_ADMIN. 현재 payload에 변경 전 Jira 담당자가 없어 승인 재배정과 외부 변경을 구분할 수 없음 |
| 오래된 assignmentRevision | 해당 작업만 DONE/STALE 처리. 최신 접수·예약·이력은 변경하지 않음 |
| 확실한 실패 | 현재 작업의 예약만 해제(assignee_id=NULL), assign_status=NEEDS_ADMIN, FAIL 이력 1건 |
| 응답·저장 결과 불명확 | 예약을 유지하고 조회만 수행. 확인 한도 이후 NEEDS_ADMIN이어도 대상 ID는 남겨 관리자 확인에 사용 |

## 함수·입력값

| 파일·함수 | 역할 |
|---|---|
| services/jira_assign.py · run_jira_assign_job() | 작업 한 건 선점·실행·확인·결과 저장 |
| run_due_jira_assign_jobs() | 실행 시각이 된 배정 작업을 오래된 순서로 처리 |
| requeue_stale_assign_jobs() | 중단된 RUNNING 배정 작업만 조회 전용 PENDING으로 복구 |
| client.set_assignee() | 지정 요청만 전송. 기존 assign_issue()의 지정·재조회 반환 형식은 유지 |

기존 payload(ticketId·receiptNo·jiraKey·groupId·assigneeId·jiraAccountId·assignmentRevision·requestedBy·requestedAt)를 그대로 사용합니다. `requestedBy=None`인 시스템 자동배정도 지원합니다. 권한·직접 지정 사유·자동 선정·부재 제외는 TK-09와 공용 예약 함수의 책임입니다.

실행 전과 저장 전에 접수·그룹·담당자·revision·Jira 계정 연결이 예약과 같은지 다시 확인합니다. 활성 그룹·활성 사용자(AGENT/ADMIN)·활성 구성원·assignable·해당 세부 유형 skill을 검사합니다. 자동/수동을 임의로 추정해 팀장·부재 제외 규칙을 다시 적용하지 않습니다.

Jira의 상태·담당자를 같은 요청으로 읽습니다. CLS·알 수 없는 상태, 담당자 필드가 빠진 불완전 응답은 미배정으로 간주하지 않습니다. 배정 성공 뒤 jira_sync_status=SYNCED와 assign_status=ASSIGNED를 확인한 경우에만 문의를 RECEIVED→HANDED_OFF로 바꿉니다. 업무 상태·처리 결과·완료 시각은 변경하지 않습니다.

## 중복·중단 복구

- 조건부 UPDATE로 작업을 선점하고, 저장할 때 RUNNING·실행 횟수를 다시 확인합니다. 실행 권한을 잃은 작업은 DB를 덮어쓰지 않습니다.
- PUT 전에 `last_error=verify_only:write_started`를 커밋합니다. 응답 시간 초과·쓰기 후 조회 실패·프로세스 중단·DB 확정 저장 실패 뒤에는 다시 지정하지 않고 조회합니다.
- 400·401·404처럼 지정 요청이 거절된 경우와, 지정 이후 조회에 실패한 경우를 구분합니다. 지정 요청의 429는 재조회 후 재시도하며, 지정 이후 조회의 429는 조회 전용 표식을 유지합니다.
- 원본 payload와 jira_sync_status는 수정하지 않습니다. 기존 ASSIGN/REASSIGN 예약 이력도 성공 때 중복 추가하지 않습니다.
- DB 예외는 호출자에게 전달합니다. 호출자는 rollback/세션 종료 후 중단 복구 함수를 사용합니다. 재시도·조회 횟수는 기존 RetryPolicy의 제안값을 따릅니다.

## 남은 연결

- 생성 성공 후 최초 배정 예약은 [CREATE_AUTO_ASSIGNMENT.md](CREATE_AUTO_ASSIGNMENT.md)에 연결했습니다. worker의 배정 실행·서버 배포는 별도이며, 기존 worker가 배정 작업을 소비하지는 않습니다.
- 다른 Jira 담당자를 바꾸는 승인 재배정은 변경 전 계정 등 비교 기준을 서버가 보존하는 계약부터 맞춰야 합니다. 임의의 추가 payload 필드를 도입하거나 현재 담당자를 예상 이전 값으로 간주하지 않았습니다.
- Jira 조회와 PUT 사이 외부 변경을 원자적으로 막지는 못합니다. 요청 도중 DB revision이 바뀌면 DB 저장은 차단하지만 이미 전송한 Jira 변경을 취소할 수는 없습니다. 최신 배정의 재대조가 필요합니다.
- 실제 계정·프로젝트 배정 권한, PostgreSQL 잠금·동시 실행은 통합 시험이 필요합니다. time_off DB·API 연결과 후보 선정 규칙은 공용 예약 쪽에서 관리합니다.

## 검증

신규 41개, 기존 포함 Jira 관련 374개 통과(모의 HTTP·임시 SQLite). PR #174 공용 함수의 시스템 자동배정·직접 지정 연결, 자격 변경, 다른 Jira 담당자 보호, 오래된 revision, 시간 초과·429, DB 저장 실패·중단 복구를 확인했습니다. 실제 Jira·운영 DB는 호출하지 않았습니다.
