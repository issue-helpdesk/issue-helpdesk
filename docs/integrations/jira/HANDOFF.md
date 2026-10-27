# Jira 댓글 알림 인수인계

기준일: 2026-10-27 · [시험 환경·결과](TEST_ENVIRONMENT.md)

## 현재 상태

**실제 Jira 댓글 수신 → 서명 검증 → 댓글 조회 → 상대방 사번 계산까지 양방향 확인했다.**
알림 DB 저장·조회 API·화면 표시는 후속 작업이다. 시험 서버는 티켓 1건과 두 사람의 역할을 고정해서 사용했다.

## 담당별 남은 작업

| 담당 | 작업 | 완료 기준 |
|---|---|---|
| 현우 | Jira 코드·테스트와 이 문서 2개를 PR로 공유 | develop 대상 검토·병합 |
| 민경 | 정식 수신, 티켓별 사용자 조회, 알림 저장·중복 방지·실패 재처리, 알림 API | 사용자별 알림 1건 저장·조회·읽음 처리 |
| 나영 | 알림 숫자·목록·읽음·관련 문의 이동을 API에 연결 | 상대방 화면에서 알림 확인 |
| 배포 담당(팀 확정) | DB 변경 적용, 서버 설정·배포, Jira 전송 주소 변경 | 정식 HTTPS 주소에서 전체 흐름 확인 |

## 민경 구현 위치

신규 파일명은 제안이며 API 계약에 맞춰 확정한다. 경로는 저장소 루트 기준이다.

| 위치 | 변경 | 역할 |
|---|---|---|
| `backend/app/main.py` | 기존 수정 | 웹훅·알림 라우터 등록 |
| `backend/app/api/jira_webhook.py` | 신규 제안 | `POST /api/v1/webhooks/jira` 수신·서명 검증 |
| `backend/app/services/jira_webhook.py` | 신규 제안 | 문의 조회 → 댓글 조회 → 수신자 계산 → 저장 연결 |
| `backend/app/repositories/` | 새 파일 추가 | 문의·사용자·알림·이벤트 기록의 DB 처리 |
| `backend/app/models/ticket.py` | 기존 확장 시 수정 | `Notification`에 댓글 ID·읽음·채널 등 보완 |
| `backend/app/models/` 및 `backend/app/db/migrations/versions/` | 추가·등록 | 이벤트 모델, 새 DB 변경 이력·고유 제약 |
| `backend/app/api/notifications.py` 및 `backend/app/schemas/`·`backend/app/services/` | 신규 제안 | 본인 알림 목록·안 읽은 개수·읽음 API |
| `backend/app/core/config.py` | 필요 시 수정 | 웹훅 비밀값·봇 제외 계정·계정 연결 설정 |
| `tests/`·`docs/` | 추가·갱신 | 중복·실패·권한 시험, 테이블·API 명세 반영 |

`backend/app/api/deps.py`의 로그인 인증은 알림 API에서 재사용한다. Jira 웹훅은 별도 서명으로 검증한다.

## 기존 DB와 연결하는 방법

```text
Jira issue.key → Ticket.jira_key
문의자: Ticket.inquiry_id → Inquiry.user_id → User.employee_no
담당자: Ticket.assignee_id → User.employee_no
계산된 수신자 사번 → User.id → Notification.recipient_id
```

`route_comment(author_account_id, requester_no=..., assignee_no=..., accounts=..., ignore_account_ids=...)`는
`recipient_nos`(사번 튜플)와 `reason`을 반환한다. 빈 튜플이면 알림을 만들지 않는다.
`Ticket.requester_no`·`Ticket.assignee_no`는 실제 DB 필드가 아니다. 기존 사용자 정보에서 사번을 구한다.

운영 계정↔사번 명부의 관리 위치는 팀에서 정한다. 재수신·동시 처리의 중복을 막고 실패한 처리는 재개할 수 있게 기록한다.
`retryable=True`는 재시도 가능 표시이며 자동 재시도가 아니다. 읽음 여부는 기존 발송 상태와 구분한다.

## 이번 PR 범위 및 충돌 확인

- 코드 8개: `backend/app/integrations/jira/`의 `webhook.py`, `client.py`, `mapper.py`, `accounts.py`, `__init__.py`, `README.md`, `comment_notify.py`와 `tests/test_jira_comment.py`.
- 문서 2개: 이 파일과 `TEST_ENVIRONMENT.md`. **총 10개 파일**이다.
- `lab/` 등 재현 도구는 별도 전달 자료다. 실제 설정·토큰·계정 연결표·가상환경은 올리지 않는다.
- 10월 27일 develop [`6b9807c`](https://github.com/issue-helpdesk/issue-helpdesk/commit/6b9807cd8a222a157ceb99329a36476266c803d8) 기준, 백엔드 계정 `parkpingu`의 PR 9건과 코드 8개의 변경 파일은 겹치지 않았고 패치 적용 검사도 통과했다. 미공유 작업은 확인 범위 밖이며 적용 직전에 최신 변경을 다시 확인한다.

## 배포·최종 확인

1. 코드 병합 후 정식 수신·DB·알림 API와 프론트를 연결한다. 비밀값은 서버 설정에 저장한다.
2. DB 변경을 적용하고 배포한 뒤 Jira 웹훅을 `https://<백엔드 주소>/api/v1/webhooks/jira`로 설정한다.
3. DB에 연결된 시험 접수로 양방향 댓글, 중복 방지, 미접속 후 알림, 읽음 처리, 다른 사용자 접근 차단을 확인한다.

ngrok과 고정 역할의 시험 서버는 개발 시험용이다. 시험 종료 시 Jira 시험 웹훅을 비활성화하고 ngrok·서버를 종료한다.
