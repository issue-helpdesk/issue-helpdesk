# 해결 사례 AI 가이드화 (M4)

담당자가 해결한 티켓 중 가이드에 없는 내용을 7일 단위로 찾아, 관리자가 고쳐서 등록할 초안으로 만든다.
결과는 DB 의 `guide_clusters`(묶음·초안)와 `ticket_guide_states`(티켓 상태)에 쓴다. Jira 로 보내지 않는다.

지금은 **티켓별 판단**까지 있다. 묶기·초안 작성은 다음 단계에서 `JudgeRun.forwarded` 를 받아 만든다.

## 파일

| 파일 | 하는 일 |
| --- | --- |
| `run.py` | `judge_round(session, port, search_fn)`: 한 회차 판단. 티켓마다 커밋 |
| `collect.py` | 대상 티켓 모으기, AI 없이 정하는 것, 같은 분류 가이드, 비교 항목 검색 (DB 읽기만) |
| `judge.py` | 프롬프트, 출력 형식, 가림·치환, 호출과 검사 |
| `store.py` | 티켓 상태·SEC 묶음·호출 기록 저장 |

## 한 회차 흐름

1. **모으기:** `work_status = CLS` 이고 상태 행이 없거나, 상태가 비었거나, `WAITING` 인 티켓
2. **AI 없이 정하기** (`collect.precheck`)

   | 조건 | 처리 |
   | --- | --- |
   | 분류 없음 | `EXCLUDED` "분류 없음" |
   | 처리 결과 없음, 20자 미만 | `EXCLUDED`. SEC 도 같다 |
   | SEC | `SEC_MANUAL` 묶음 1개 + 티켓 `REVIEWING`. 초안 글은 비어 있음 (김태연 님 조각 함수 연결 전) |

3. **비교 항목:** 요약·증상·처리 결과로 같은 분류 문서를 관리자 권한으로 검색해 상위 5개
4. **AI 판단:** 티켓 1건당 1회 (thinking 켬). 실패하면 한 번 다시 부른다
5. **저장**

   | 결과 | 처리 |
   | --- | --- |
   | `NOT_TARGET`, `EXISTS` | `EXCLUDED`, 이유 앞에 "대상 아님:" 또는 "이미 있음 (문서 항목):" |
   | `ADD_ITEM`, `CHANGE`, `NEW_GUIDE`, `MANUAL_CANDIDATE` | 상태를 쓰지 않고 `forwarded` 로 넘김. 실패 기록만 0 으로 |
   | 실패 | 상태는 그대로, `fail_code`·`fail_count + 1`. 다음 회차에 다시 |
   | 예상 못 한 오류 | 그 티켓만 되돌리고 `UNEXPECTED` 로 실패 기록. 다음 티켓을 계속 처리한다 |

## 외부 전송

- 티켓 요약·증상·대상 시스템·처리 결과: A·B 가림(`mask_secrets`) + C·D 치환(`Pseudonymizer`) (docs/10)
- 비교 항목: `ALLOWED` 그대로, `MASKED` 가림+치환, `BLOCKED` 는 제목만 (`content_hidden: true`)
- 검색 결과의 정책은 매뉴얼 항목 값이 있으면 그 값이다 (검색 `content_transfer_policy` 우선)

## 서버 검사 (`judge.check`)

| 판단 | `target_doc` | `target_item` |
| --- | --- | --- |
| `ADD_ITEM` | 같은 분류 가이드 목록 안 | 비움 |
| `CHANGE` | 같은 분류 가이드 목록 안 | 보낸 항목 중 그 가이드의 3.x 항목 (`ITEM`). 장·FAQ 는 안 됨 |
| `EXISTS` | 보낸 항목 안 (매뉴얼도 됨) | 보낸 항목 안 |
| 그 밖 | 비움 | 비움 |

틀리면 `INVALID_REFERENCE` 로 한 번 다시 부른다. 항목 추가·변경 대상이 매뉴얼이면 틀린 것이다 (매뉴얼에 넣을 내용은 `MANUAL_CANDIDATE`).

## 호출 기록

`llm_calls` 에 목적 `GUIDE_JUDGE`, 티켓의 `inquiry_id` 로 남긴다. 프롬프트·응답 원문은 남기지 않는다.

## 시험

`tests/test_guide_judge.py`: Mock 모델과 SQLite 메모리 DB. 외부로 아무것도 보내지 않는다.

## 한계

- **다시 열린 티켓:** 한 번 `EXCLUDED` 가 된 티켓은 미해결로 다시 열렸다가 다시 CLS 가 되어도 모으지 않는다.
  처음 처리 결과가 짧아 제외됐더라도, 나중에 자세한 처리 결과가 들어오면 빠진다.
  고치려면 티켓이 다시 열릴 때 `ticket_guide_states` 행을 지워야 한다 (티켓 상태 변경 코드, 박민경 님 담당).
