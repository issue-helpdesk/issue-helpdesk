# Jira 상태 변경 실행 연결

TK-07이 권한·허용 변경·민감정보를 검증하고 저장한 JIRA_TRANSITION 작업을 실행하는 서비스입니다.
브라우저의 입력을 직접 받는 API가 아니며, 기존 enqueue_jira_transition()의 등록·커밋 책임은 유지합니다.

## 구현 범위

| 항목 | 처리 |
|---|---|
| RDY → WIP | Jira 전환·최신 상태·변경 이력 확인 후 DB 상태와 이력 저장 |
| WIP → FIN | 최초 완료는 요청한 처리 결과 또는 기존 DB 결과를 사용. FIN → WIP 이력이 있는 재완료는 요청에 처리 결과 필수. 확인한 Jira FIN 전환 시각을 finished_at에 저장 |
| FIN → CLS | 문의자·해결 확인 기록 일치와 Jira 최종 처리 결과 확인. Jira CLS 확인 후 요청 시각을 closed_at에 저장하고 문의 해결 결과 확정 |
| 처리 결과만 수정 | WIP·FIN에서 전용 필드만 수정·재조회. 상태·완료 시각은 유지하고 상태 변경 이력은 추가하지 않음 |
| FIN → WIP | 미해결 재처리. 남은 증상(`reason`)이 필수이고 처리 결과는 받지 않는다. Jira 상태를 WIP로 되돌린 뒤 남은 증상을 Jira 댓글로 남긴다(접수번호·요청 시각 식별 문구로 이미 달렸는지 먼저 확인해 중복 방지). 이전 처리 결과는 DB에 보존하고 재완료 때 새 결과로 덮어쓴다. 완료마다의 결과는 상태 이력에도 남는다. `finished_at`은 WIP 확인 후 NULL로 비운다 |

## 함수

| 파일·함수 | 역할 |
|---|---|
| client.get_work_result() | 상태와 최종 처리 결과(customfield_10069)를 같은 조회로 읽음. 빈 문단 보존 |
| client.update_final_result() | 같은 결과면 PUT 생략. 그 외 전용 필드를 ADF로 수정 후 상태·내용 재조회 |
| client.get_status_changed_at() | changelog 모든 페이지에서 요청 이후의 해당 전환 시각 조회. 현재 실행 시각으로 대체하지 않음 |
| services.jira_transition.run_jira_transition_job() | 작업 한 건 선점·실행·확인·DB 저장 |
| run_due_jira_transition_jobs() | 실행 시각이 된 PENDING 전환 작업을 오래된 순서로 처리 |
| requeue_stale_transition_jobs() | 중단된 RUNNING 전환 작업을 조회 전용 PENDING으로 복구 |

기존 API 03의 payload를 사용하며 원본 payload는 수정하지 않습니다. 접수 ID·접수번호·Jira 키·요청 상태·요청자·확인 시각이 맞지 않으면 외부 쓰기를 중단합니다. 권한 검증은 기존 TK-07에서 수행합니다.

재완료 여부는 해당 Ticket의 `ticket_status_history`에 FIN → WIP 이력이 있는지로 판단하며 이력의 source는 제한하지 않습니다.
TK-07은 재완료 요청에 `resolutionNote`가 없거나 null이면 기존 저장값이 있어도 422 `TICKET_RESOLUTION_NOTE_REQUIRED`를 반환합니다.
실행 서비스도 Jira 호출 전에 같은 규칙을 검사합니다. 이미 등록된 작업에 입력이 없으면 이전 저장값으로 보충하지 않고 NEEDS_ADMIN으로 넘기며 원본 payload를 유지합니다.
직접 입력한 문구가 이전 결과와 같은지는 비교하지 않습니다. 공백 입력은 기존 유효성 검사로 거부하며, WIP·FIN의 처리 결과만 수정하는 요청은 그대로 허용합니다.

## 결과 저장·복구

- 성공: job=DONE, transition_status=IDLE, requested_work_status=NULL. 확인한 상태·처리 결과·work_status_confirmed_at을 저장합니다. jira_sync_status는 바꾸지 않습니다.
- 상태 이력: Jira 전환 시각을 사용하고 source=ITSSUE로 기록합니다. 같은 티켓·목표 상태·전환 시각의 이력이 이미 있으면 중복 저장하지 않습니다.
- 외부 쓰기 전에 last_error에 `verify_only:write_started`를 커밋합니다. 응답 시간 초과, 쓰기 후 조회 실패, 프로세스 중단 뒤에는 POST/PUT을 다시 보내지 않고 조회만 합니다. 결과가 확인되지 않으면 기존 상태를 유지하다 NEEDS_ADMIN으로 넘깁니다.
- 쓰기 함수가 429를 반환한 경우는 재조회 후 재시도할 수 있습니다. 쓰기 이후 결과 조회의 429는 조회 전용 상태를 유지합니다. 재시도·확인 횟수는 기존 RetryPolicy의 제안값을 따릅니다.
- Jira 응답 직후 DB 저장에 실패하면 호출자는 세션을 rollback/종료합니다. job은 RUNNING과 조회 표식으로 남으며, 중단 복구 후 조회·저장만 수행합니다.
- job의 실행 횟수와 RUNNING 상태를 다시 확인해 실행 권한을 잃은 작업이 DB 결과를 덮어쓰지 않게 합니다. 다른 요청·상태로 바뀐 접수는 덮어쓰지 않습니다.
- `resolution_confirmed_at`은 문의자의 요청 시각으로 유지합니다. FIN 전환 시각·Jira 조회 확인 시각과 구분합니다.

## 현재 연결 상태와 남은 확인 (11.08 정정)

- 최초 구현 당시에는 worker 연결이 후속이었으나 현재 `integrations/jira/worker.py`는 JIRA_TRANSITION을 소비합니다. 실행 설정과 검증 범위는 [WORKER.md](WORKER.md), [WORKER_VALIDATION.md](WORKER_VALIDATION.md)를 따릅니다. 코드 연결을 실제 운영 E2E 완료로 해석하지 않습니다.
- 배정·생성·웹훅·주기 대조·관리자 재처리는 별도 구현 경로로 연결돼 있습니다. 이 문서는 상태 변경 실행 서비스의 역할을 다룹니다.
- **이력 보존 반영:** FIN 전환마다 `ticket_status_history.resolution_note`와 `changed_at`을 저장합니다. 미해결 사유는 FIN→WIP 이력의 `reason`과 Jira 댓글에 남습니다. 기능 추가 전의 과거 이력 본문은 비어 있을 수 있습니다. FIN 상태에서 결과만 편집한 중간값까지 모두 보존하는 기능은 아닙니다.
- **완료 시각:** FIN→WIP 후 `finished_at = NULL`은 API 03·테이블 설계서 기준이며, `jira_webhook.sync_work_status`와 `_save_confirmed`가 모두 따릅니다. 재완료 때는 새 Jira 전환 시각이 저장됩니다.
- 미해결 사유 댓글을 쓰는 계정은 연동 계정입니다. 댓글 알림을 운영하는 환경에서는 `ignore_account_ids`에 이 계정을 넣어 자기 댓글이 다시 알림을 만들지 않도록 확인합니다.
- Jira에는 조회와 수정 사이의 비교 후 교환을 이 서비스가 보장할 방법이 없습니다. 전후 상태를 대조해 충돌을 감지하지만, 사이에 일어난 외부 편집까지 원자적으로 차단하지는 못합니다.
- 여러 필드를 수정한 뒤 전환하는 요청은 일부만 Jira에 반영될 수 있습니다. 확인이 끝나기 전에는 DB를 완료로 바꾸지 않으며, 불명확한 작업을 자동으로 덮어써 복구하지 않습니다.
- PostgreSQL 잠금·동시 실행, 실제 Jira의 필드 편집 권한·전환·변경 이력 형식은 통합 시험이 필요합니다.

## 검증

모의 HTTP·임시 SQLite로 신규 57개, 기존 포함 Jira 관련 333개 통과. 정상 전환·처리 결과 수정·빈 문단·중복 실행·시간 초과·429·이력 조회 지연·DB 커밋 실패·중단 복구·오래된 실행의 저장 차단을 확인했습니다. 실제 Jira·운영 DB는 호출하지 않았습니다.

재완료 검증 회귀시험 22개 추가. Jira 관련 385개, 티켓·인증·문의 API 관련 275개를 모의 HTTP·SQLite로 확인했습니다. 실제 Jira·PostgreSQL 동시 실행은 검증하지 않았습니다.

Jira 필드 수정·전환·changelog API는 [Atlassian REST v3 Issues 문서](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/)를 기준으로 구현했습니다. API의 실제 사용 가능 여부는 프로젝트 권한·화면·워크플로 설정에 따라 별도로 확인해야 합니다.
