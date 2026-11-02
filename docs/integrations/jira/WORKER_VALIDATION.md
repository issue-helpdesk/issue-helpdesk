# Jira worker 연결 검증 — 2026-11-02

## 기준과 변경

기반은 `develop`의 `29b53f0f1002bb9bde31186ca905416469ea3d99`다. 생성·배정·상태 변경 서비스는 그대로 재사용하고 worker의 호출을 연결했다. 복구 함수 3개에는 선택적 `ticket_id` 조건만 추가했다. API·모델·DB 마이그레이션·배정 규칙·payload 계약은 수정하지 않았다. 검증 후 최신 develop `289631b`의 관리자 화면 변경만 충돌 없이 반영했다. 해당 추가 변경에는 백엔드·시험 코드 변경이 없다.

## 자동 시험

```bash
PYTHONPATH=backend python -m pytest tests/test_jira_*.py tests/test_tickets.py tests/test_time_off.py -q
```

**560 passed**. 이 중 worker 시험은 기존 8개와 추가 15개를 합쳐 23개다.

추가 검증은 실제 배정/전환 서비스 실행·DB 확정, 중단된 배정/전환의 조회 전용 복구(추가 POST/PUT 없음), 접수 한정 복구·실행, 종류 선택, 보류 FIN→WIP 뒤 정상 요청 처리, 단건 예외 후 같은 종류/다른 종류 계속 실행, `--once` 오류 종료 코드, 잘못된 CLI 값 거부를 포함한다. 모의 HTTP와 임시 SQLite 기반이며, 아래 실제 시험과 구분한다.

Compose 추가 파일은 YAML 해석과 실행 명령을 확인했다. Docker 이미지 빌드·서버 상시 배포는 하지 않았다.

## 실제 PostgreSQL + Jira 단건 시험

- 실행 시각: **2026-11-02 14:20 KST**.
- 접수: **RCPT-0001**, Ticket ID **1**.
- Jira: **[ITHD-366](https://itssuehelpdesk.atlassian.net/browse/ITHD-366)**.
- 실제 연결: 사용자가 제공한 PostgreSQL DB 및 로컬 설정의 ITHD Jira 인증.
- API: 이 브랜치의 로컬 FastAPI TestClient. 문의·세션·초안은 전용 시험 데이터로 준비했으며 실제 AI 상담/검색은 실행하지 않았다.
- 인증: 전용 문의자/관리자 시험 계정으로 실제 로그인 API를 호출하고 발급된 토큰을 사용했다. 로컬 시험 인스턴스의 서명키는 임시 생성했으며 운영 서버 설정은 변경하지 않았다.
- 배정 대상: 시험 실행자의 Jira 계정. 전용 시험 관리자를 MANAGER 구성원으로 두어 자동선정 후보에서 제외하고, 이번 접수에만 TK-09 직접 지정했다. 기존 사용자의 계정·그룹·배정은 수정하지 않았다.
- worker: 모든 회차에서 `ticket_id=1`을 지정해 다른 접수의 조회·복구·실행을 제외했다.

| 단계 | 확인 결과 |
|---|---|
| TK-04 접수 확정 | 201, RCPT-0001, 생성 작업 PENDING |
| worker 생성 | CREATED, ITHD-366, SYNCED/RDY |
| 같은 초안 재확정 | 200, 동일 접수 반환. 새 접수 없음 |
| TK-09 직접 배정 요청 → worker | PENDING → ASSIGNED, 실제 Jira 재조회 일치 |
| TK-07 RDY→WIP → worker | 202/PENDING → CONFIRMED, DB WIP |
| TK-07 WIP→FIN + 시험 처리 결과 → worker | 202/PENDING → CONFIRMED, DB FIN 및 최종 처리 결과 일치 |
| 문의자 TK-07 FIN→CLS → worker | 202/PENDING → CONFIRMED, DB CLS 및 해결 확인 기록 |
| 상태 이력 조회 | WIP·FIN·CLS 이력 각 1건, 총 3건 |
| 실제 Jira 재조회 | CLS 및 DB의 최종 처리 결과와 일치 |
| 연동 작업 | 생성 1·배정 1·상태 변경 3, 총 5건 모두 DONE/attempts=1 |
| 완료 접수 worker 재실행 | 추가 작업 없음. 실제 CLI `--once --ticket-id 1`도 종료 코드 0, 복구 0건·작업 없음·오류 0건 |

시험 종료 후 두 시험 계정은 INACTIVE로 바꾸고, 시험 그룹 구성원은 비활성·배정 불가로 바꿨다. 시험 로그인 세션도 폐기했다. 시험 접수와 Jira 이슈는 검증 근거로 보존했다. 제목과 처리 결과에 시험임을 표시했으며 실제 해결 사례로 가이드에 활용하지 않는다.

## 검증하지 않은 범위

- 배포된 화면에서의 사용자 조작, 서버 상시 worker 프로세스, Docker 배포.
- 최초 자동배정 예약 연결(PR #181 미병합). 이번 실제 배정은 TK-09 직접 지정이다.
- FIN→WIP 재처리와 재완료 입력 강제(PR #179 미병합), 이미 다른 담당자가 있는 승인 재배정.
- Jira 웹훅 수신·상태 동기화·댓글 알림·Slack.
- 여러 worker의 PostgreSQL 동시 실행·장애 주입. 단일 worker와 실제 DB 저장은 확인했으나 동시성 전체 검증으로 보지 않는다.

이번 결과는 **실제 접수의 생성·명시적 배정·기본 상태 전환을 단건 worker로 처리한 통합 시험 통과**다. Jira 연동 전체나 운영 배포 완료를 의미하지 않는다.
