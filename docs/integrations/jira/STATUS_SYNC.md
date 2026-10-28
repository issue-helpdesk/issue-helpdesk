# Jira 상태 동기화 — 연동 부품 및 시험

기준일: 2026-10-27 · 방향: **Jira → ITssue**

## 현재 범위

상태 변경 웹훅을 감지하고 Jira의 최신 상태를 읽어 ITssue에 반영할 상태를 계산한다.
DB 갱신·상태 이력 저장·화면 반영은 민경 담당 후속 작업이다. Jira 상태를 바꾸는 API는 이 수신 경로에서 호출하지 않는다.

## 변경 파일

- `backend/app/integrations/jira/status_sync.py`: 새 판단 함수. 기존 `get_work_status()`와 상태 매핑을 재사용한다.
- `tests/test_jira_status_sync.py`: 판단 및 별도 수신 서버 시험 33개.
- `tools/jira_status_lab/`: 상태 전용 시험 서버·모의 시연·설정 예시. 로컬 설정은 Git에서 제외한다.
- 기존 Jira 코드·댓글 기능·서버·DB·인증 파일은 수정하지 않았다.

## 처리 규칙

| 입력/조회 결과 | 처리 |
|---|---|
| `jira:issue_updated`이고 status 변경 있음 | Jira 최신 상태 조회 후 `RDY/WIP/FIN/CLS` 반환 |
| 제목·담당자만 변경 | `not_status_change`, 조회 생략 |
| 댓글 등 다른 사건 | `ignored_event`, 조회 생략 |
| Jira 상태 매핑 없음 | `unmapped_status`, 반영 후보 없음 |
| 실제 DB 현재값과 조회 상태가 같음 | `unchanged`, 새 변경 이력 불필요 |
| Jira 조회 실패 | 오류와 재시도 가능 여부 반환. 재시도 실행은 별도 |

웹훅의 과거 to 값으로 덮어쓰지 않는다. `plan_status_sync(event, latest, current_work_status=...)`에 최신 조회 결과와 DB의 현재값을 전달한다.
시험 서버는 DB를 읽지 않으며 모든 응답의 `db_updated`는 false다.

## 시험 결과

- Python 3.12.14, FastAPI 0.159.1, Uvicorn 0.54.0, pytest 9.1.1, httpx 0.28.1.
- 기반: develop `bd98c7c16ea492c613c55025ee819cebcd7d856c`.
- 기존 Jira·댓글 96개 + 상태 시험 33개 = **129개 통과**.
- 실제 로컬 HTTP 서버/모의 Jira로 상태·제목·댓글·다른 티켓 4개 사례 통과.
- 실제 Jira ITHD-361에서 사용자가 RDY → WIP으로 변경한 웹훅 수신 성공.
- 응답: `status_changed=true`, `jira_status_id=10005`, `work_status=WIP`, `reason=status_resolved`, `db_updated=false`.
- 사용자 제공 ngrok 응답 JSON으로 확인했다. `current_work_status=null`은 DB 현재값을 읽지 않았다는 뜻이다.

## 실제 연결 시험

1. 별도 환경에 `tools/jira_status_lab/requirements.txt`를 설치한다.
2. `.env.example`을 같은 폴더의 `local/real.env`로 복사해 Jira 인증값·시험 티켓·웹훅 비밀값을 채운다.
3. 저장소 루트에서 아래 명령으로 서버를 실행한다.

```bash
python tools/jira_status_lab/receiver.py --mode real --env-file tools/jira_status_lab/local/real.env --port 8766
```

4. `ngrok http 8766`을 실행하고 Jira 상태 웹훅 URL에 `https://<주소>/api/v1/webhooks/jira`를 지정한다.
5. 이벤트는 이슈 수정(`jira:issue_updated`), 필터는 우선 `key = ITHD-361`, 비밀값은 로컬 설정과 동일하게 지정한다.
6. 시험 티켓을 RDY → WIP으로 바꾸고 `status_changed=true`, `work_status=WIP`, `reason=status_resolved`, `db_updated=false`를 확인한다.
7. 종료 시 시험 웹훅을 비활성화하고 ngrok·서버를 종료한다.

기존 ‘ITssue 상태 동기화’의 옛 ITSD 필터·webhook.site 주소를 시험 티켓·ngrok 주소·동일한 비밀값으로 수정해 검증했다. 재시험 시 현재 설정을 다시 확인한다.
댓글 웹훅은 별도 등록돼 있으므로 이번 상태 시험에서 수정할 필요가 없다.

## 민경 후속 연결

정식 수신 서비스에서 서명 검증 → 이벤트 기록 → `jira_key`로 티켓 조회 → 티켓 잠금/직렬 처리 → 최신 상태 조회·계산 → `Ticket.work_status` 및 `TicketStatusHistory(source=JIRA)` 저장을 연결한다.
중복·실패 재처리와 동시 갱신을 관리하고, 매핑 불가/이미 같은 상태는 덮어쓰지 않는다. 알 수 없는 티켓은 임의로 생성하지 않는다.
ITssue→Jira 전환 기능과 수신 갱신을 구분해 동일 상태를 다시 전송하는 순환을 막는다.
