# Jira 댓글 알림 시험 환경·결과

시험일: 2026-10-27 (Asia/Seoul) · [인수인계·후속 작업](HANDOFF.md)

## 실행 환경

| 항목 | 환경 |
|---|---|
| 장비·OS | 현우 로컬 Mac · macOS 14.8.4 · arm64 |
| Python | 3.12.14 · 별도 venv |
| 서버 | FastAPI 0.159.1 · Uvicorn 0.54.0 |
| 시험·통신 | pytest 9.1.1 · httpx 0.28.1 |
| 설정 읽기 | python-dotenv 1.2.4 · PyYAML 6.0.3 |
| 외부 통로 | ngrok 3.39.13 (문서 작성 시 설치 버전 확인) |
| 실제 Jira | [itssuehelpdesk.atlassian.net](https://itssuehelpdesk.atlassian.net) · ITHD-361 |

시험 기반은 develop [`1796f19`](https://github.com/issue-helpdesk/issue-helpdesk/commit/1796f19e372f1c2eee363a69f50a2ca35a81187a)에 댓글 패치를 적용한 사본이다.
이후 develop `6b9807c`에서도 기존 Jira 파일 6개가 동일하고 패치가 적용됨을 확인했다. 최신 develop 전체 서비스 시험을 다시 수행한 것은 아니다.

## 시험 방법과 결과

| 구분 | 방법 | 결과 |
|---|---|---|
| 자동 모의 시험 | httpx.MockTransport·FastAPI TestClient, 가상 계정·댓글 사용 | 기존 Jira 63 + 댓글 33 + 수신 서버 27 = **123개 통과** |
| 로컬 HTTP 시연 | `127.0.0.1:18765`에 서명된 합성 웹훅 전송, Jira 조회는 모의 응답 | **6개 사례 통과** |
| 실제 연결 시험 | Jira Cloud → ngrok HTTPS → `127.0.0.1:8765` → 별도 수신 서버 → Jira 댓글 조회 | **양방향 수신자 판단 성공** |

실제 시험은 `comment_created`를 `POST /api/v1/webhooks/jira`로 받았다.
팀 계정의 이메일·API 토큰으로 댓글을 조회하고 `X-Hub-Signature`로 웹훅 서명을 검증했다.
현우 개인 계정은 문의자 EMP-1321, 나영 개인 계정은 담당자 EMP-1408로 설정했고 팀 계정의 댓글은 제외했다.
역할은 로컬 설정에 고정했으며 Jira assignee나 운영 DB에서 읽지 않았다.

| 실제 댓글 ID | 작성자 → 계산된 수신자 | 응답 |
|---|---|---|
| 10006 | 현우 → 나영(EMP-1408) | `to_assignee` |
| 10007 | 나영 → 현우(EMP-1321) | `to_requester` |

실제 결과의 근거는 사용자가 제공한 ngrok의 HTTP 200 응답 JSON과 화면이다.
두 응답 모두 `ok=true`, `mode=real`, `notification_saved=false`였다. 알림 저장은 수행하지 않았다.

## 재현과 검증 범위

자동 시험은 코드 반영 후 저장소 루트에서 실행한다.

```bash
python -m pytest tests/test_jira_comment.py tests/test_jira_integration.py tests/test_jira_assignment.py -q
```

위 명령의 대상은 기존·댓글 시험 **96개**다. 나머지 27개와 HTTP 시연은 별도 전달한 `lab/` 시험 도구에 포함돼 있다.
실제 시험도 별도 도구의 real 모드·로컬 계정 연결표·공유 비밀값과 ngrok으로 재현한다. 설정값은 Git에 올리지 않는다.
전체 설치 버전·실행 절차·응답 원본은 별도 전달 묶음에 보관했다.

**확인 완료:** 웹훅 수신·서명 검증·댓글 조회·양방향 수신자 계산.

**후속 검증:** 운영 DB의 티켓별 사용자 조회·알림 저장·영구 중복 방지·실패 복구·화면 표시·읽음·Slack·운영 부하.
