# Jira 생성·배정·상태 변경·웹훅 반영 실행기

`integrations/jira/worker.py`는 생성 → 배정 → 상태 변경 순서로 기존 실행 서비스를 호출한다. 각 종류의 오래된 RUNNING 작업을 해당 서비스의 복구 함수로 되돌리고, 실행 시각이 된 PENDING 작업을 ID 순으로 처리한다. 그 뒤 같은 회차에서 API가 저장해 둔 웹훅 이벤트(`jira_webhook_events`의 PENDING)를 `run_due_webhook_events`로 DB에 반영한다. 웹훅을 마지막에 두는 이유는, ITssue가 보낸 변경이 Jira에서 되돌아온 이벤트가 앞 단계 작업이 끝난 뒤에 값이 같아 그대로 끝나게 하기 위해서다.

## 실행

```bash
# 종류별 최대 10건씩 한 회차 실행
uv run python backend/app/integrations/jira/worker.py --once

# 특정 접수만 조회·복구·실행. 다른 접수의 방치 작업도 건드리지 않는다.
uv run python backend/app/integrations/jira/worker.py --once --ticket-id <접수 ID>

# 웹훅 이벤트 반영만 끄기 (작업 처리는 그대로)
uv run python backend/app/integrations/jira/worker.py --once --no-webhook

# 생성만 기존 방식으로 운영하거나, 배정·전환만 별도 점검
uv run python backend/app/integrations/jira/worker.py --job-types JIRA_CREATE
uv run python backend/app/integrations/jira/worker.py --once --job-types JIRA_ASSIGN JIRA_TRANSITION --ticket-id <접수 ID>

# 기존 배포 구성을 유지하고 별도 프로세스 추가
# 먼저 DB 마이그레이션과 서버 .env의 DB/Jira 인증값·매핑을 확인한다.
docker compose -f docker-compose.yml -f docker-compose.jira-worker.yml up -d --build jira-worker
```

`--limit`은 전체 합계가 아니라 **종류별 상한**이다(기본 10, 작업 종류별 한 회차 최대 30건이며, 웹훅은 별도로 Jira를 호출한 이벤트 기준 10건). `--ticket-id`를 주면 웹훅 이벤트는 접수별로 고르는 기능이 없어 처리하지 않는다. `--interval`은 회차 종료 뒤 대기 시간이며 기본 30초다. `--stale-minutes`는 중단 복구 기준이며 기본 5분이다. 이 숫자는 운영 확정값이 아니라 조정 가능한 기본값이다.

Compose 파일은 워커를 2개(`deploy.replicas: 2`) 띄운다. 둘 다 세 종류를 모두 처리하며, 한쪽이 멈춰도 다른 쪽이 이어받는다. 개수를 바꾸려면 `up -d --scale jira-worker=<개수>`를 쓴다.

별도 Compose 파일은 실행 방법을 제공한다. 파일 추가 자체가 서버 배포나 상시 실행 완료를 뜻하지 않는다. 기존 API 서버의 시작 코드·DB 구조·권한 규칙·작업 payload는 바꾸지 않는다.

## 오류·중복

- 각 작업은 기존 단건 서비스가 조건부 UPDATE로 선점한다. 담당자 revision, 실제 Jira 상태, 요청 payload 검증도 기존 서비스에서 수행한다.
- 단건 실행 중 예상하지 못한 예외가 나면 세션을 rollback하고 같은 종류의 다음 작업 및 다른 종류를 계속 처리한다. 이미 커밋된 RUNNING·조회 전용 표식은 보존하며 다음 회차의 중단 복구가 사용한다. 종류별 준비 단계가 실패하면 그 종류만 건너뛴다.
- `--once`는 예상하지 못한 예외가 있으면 종료 코드 1을 반환한다. 서비스가 정상적으로 반환한 NEEDS_ADMIN·재시도 결과는 종류/결과별 요약에 남긴다. 종료 코드 0만으로 업무 성공을 판단하지 말고 작업 상태도 확인한다.
- 로그에는 작업 종류·ID·결과·예외 형식만 남긴다. payload·접속 문자열·외부 응답 본문은 출력하지 않는다.
- FIN→WIP(미해결 재처리)도 다른 상태 변경과 같이 ID 순으로 실행한다. Jira 상태를 되돌린 뒤 남은 증상 댓글을 남기며, 이전 처리 결과는 지우지 않는다. 자세한 규칙은 [STATUS_TRANSITION.md](STATUS_TRANSITION.md).
- Ctrl+C/SIGTERM은 현재 회차를 마친 뒤 종료한다. 강제 종료 시 각 서비스의 중단 복구 경로가 필요하다.

## 남은 범위

이미 다른 Jira 담당자가 있는 승인 재배정, 댓글 알림, 주기적 상태 대조, FIN→WIP 때 이전 결과를 따로 보존하는 방식은 별도다. 웹훅 이벤트 반영은 실행기에 연결됐지만 실제 Jira 웹훅→서버 DB 반영 시험과 서버 상시 실행은 아직 하지 않았다. 최초 자동배정(PR #181)과 재완료 입력 강제(PR #179)는 반영됐고, 생성 성공 뒤 등록된 배정 작업은 같은 회차에 이어서 실행된다.

검증 결과와 실제 단건 시험 범위는 [WORKER_VALIDATION.md](WORKER_VALIDATION.md)에 기록한다.
