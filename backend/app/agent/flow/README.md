# 판단 흐름 (WBS M4-2-1)

사용자 글 하나를 받아 **1차 판단 → (검색 → 2차 판단) → 보정 → 긴급도 확정**까지 하고, 백엔드(M1)가 저장할 값을 돌려줍니다.
기준은 [docs/08](../../../../docs/08.AI_입출력_형식.md) 3.2·5.3·5.4, [docs/09](../../../../docs/09.대화_상태_정의.md) 4.1·4.2입니다. **규칙을 바꾸려면 문서를 먼저 고칩니다.**

## 한눈에 보기

```
judge_first ─▶ correct_first ─┬─ reply 위험 (1번만) ─▶ judge_first
                              ├─ 끝: 긴급 · 추가 질문 · 상한 · 호출 실패 ─▶ decide_urgency
                              └─ 검색 ─▶ search ─▶ judge_second ─▶ correct_second ─┬─ reply 위험 (1번만) ─▶ judge_second
                                                                                    └─▶ decide_urgency
decide_urgency ─▶ package ─▶ FlowResult
```

| 파일 | 내용 | 근거 |
|---|---|---|
| [`graph.py`](graph.py) | LangGraph 연결, `run_flow()` | 09 4.1 |
| [`correct.py`](correct.py) | 보정 4~9단계, 처리 방향 보정 | 08 3.2 |
| [`urgency.py`](urgency.py) | 긴급도 확정 | 08 5.3 |
| [`result.py`](result.py) | 결과 형식 `FlowResult`, 근거 저장 행 | 08 5.4 |
| [`state.py`](state.py) | 노드끼리 주고받는 값 | |

시험: `tests/test_flow_correct.py` · `test_flow_urgency.py` · `test_flow_graph.py` (DB·API 키 없이 돌아갑니다)

| 여기서 하지 않는 것 | 누가 |
|---|---|
| Claude 호출, 1~3단계 검사, 치환·근거 거르기, `ALL_BLOCKED` | 호출부 M4-2-2 (`call_judge`) |
| DB 읽기(분류 체계·직원 이름), 값 4개 계산, 저장 | 백엔드 M1 |
| 검색 | M3 (`search`). 함수를 넘겨받아 부르기만 합니다 |

---

## 쓰는 법

```python
from app.agent.flow import run_flow
from app.agent.llm import AIInput, get_llm_adapter
from app.rag.search import search

r = run_flow(
    AIInput(session_id=..., inquiry_id=..., message=저장된_글, history=최근_대화, collected_facts=...,
            ask_more_count=..., ask_more_unanswered_count=..., prior_urgent_signal=..., prior_urgency=...,
            user_context={...}, search=None),
    get_llm_adapter(),                         # 시험·키 없을 때는 MockAdapter()
    taxonomy,                                  # llm README 와 같은 Taxonomy (DB categories·inquiry_types)
    직원_이름_목록,                             # users.name
    lambda req: search(session, req, embedder),
)
```

- 값 4개(`ask_more_count`·`ask_more_unanswered_count`·`prior_urgent_signal`·`prior_urgency`)는 서버가 판단 이력에서 계산해 넣습니다 (09 4.2).
- `search`는 `None`으로 넘깁니다. 검색은 흐름이 합니다. 검색어는 `history`의 사용자 글과 이번 글을 이어 붙인 것이고, 1차 분류로 범위를 좁히지 않습니다.
- 같은 설정으로 여러 번 부르면 `build_flow(...)`로 그래프를 만들어 두고 `.invoke()`해도 됩니다.

## 결과 쓰는 법 (`FlowResult`)

| 값 | 뜻 | 어디에 |
|---|---|---|
| `output` | 확정값 (보정 후). `urgency_suggested`는 AI 제안 그대로 | `inquiry_assessments` 기존 칸, `inquiries.title` |
| `urgency` | 확정 긴급도 | `inquiry_assessments.urgency` |
| `needs_triage` | 긴급도 시작값이 없어 P3로 둠 | 서비스데스크 확인 표시 |
| `next_step` | `offer` · `collect` · `answered` | 다음 상태 (09 4.1) |
| `ai_output` | **최종 판단**의 AI 원본. 안전 기본값·`ALL_BLOCKED`면 `None` | `inquiry_assessments.ai_output` |
| `override_reasons` | 보정·긴급도 규칙이 바꾼 것 `{field, ai, final, rule, reason}` | `inquiry_assessments.override_reasons` |
| `llm_calls` | 이 메시지의 모든 호출 (1·2차, 다시 생성 포함) | `llm_calls` |
| `failure` · `error_code` | `AI_FAILED`·`ALL_BLOCKED`와 사유 | `audit_logs` `FAIL`·`BLOCK` (09 3.3) |
| `sources` | 확정 `evidence`가 가리키는 검색 결과의 저장 행 | `message_sources` (`message_id`는 저장할 때) |
| `evidence` | 2차에서 Claude에 보낸·뺀 근거 | `audit_logs` `DOC_BLOCKED`·`FILTER_FAILED` |

- 2차까지 가면 확정값·`ai_output`·`override_reasons`는 **최종(2차) 판단 것만** 넣습니다. `llm_calls`만 1·2차를 합칩니다.
- `sources`는 가리기 전 **원래 검색 결과**로 만듭니다 (M3 스냅샷 규칙).
- `ALL_BLOCKED`면 화면 안내는 `app.agent.sensitive.BLOCKED_NOTICE`를 씁니다.

`error_code`는 [llm README](../llm/README.md)의 표에 아래 하나가 더해집니다.

| 값 | 언제 |
|---|---|
| `UNSAFE_REPLY` | `reply`가 비밀번호·인증번호·API 키를 달라고 하거나 접수·배정됐다고 말해서 한 번 다시 불렀는데 또 그랬음 (08 3.2 9단계) |

## 정한 것 (문서에 없는 부분)

| 경우 | 처리 | 이유 |
|---|---|---|
| 1차에서 Claude 실패 (`AI_FAILED`) | 검색·2차 없이 `offer` | 09 T11. SDK가 이미 한 번 더 시도한 뒤라 바로 다시 불러도 실패하기 쉬움 |
| `reply` 위험 | `call_judge`를 한 번 더 부름. 또 위험하면 안전 기본값 | 판단 전체를 다시 받음. 새 프롬프트를 만들지 않음 |
| 1차 `reply`가 위험한데 검색으로 넘어감 | 보지 않음 | 이 `reply`는 사용자에게 보여 주지 않음. 2차 `reply`를 봄 |
| 위험한 `reply` 판단 | 비밀번호·인증번호·API 키를 **달라는** 말, 접수·배정됐다는 말. "하지 마세요"가 있는 문장은 안내로 보고 넘김 | `correct.py` `unsafe_reply`. 재설정 포털 안내("새 비밀번호를 입력해 주세요")는 통과 |
| 검색 자체가 오류 (DB 연결 끊김 등) | 잡지 않고 그대로 던짐 | 서버 전체 문제라 M1이 한곳에서 처리. 지금 M1 `InquiryService.reply()`가 AI 오류를 모두 잡아 안내함 |
| `facts.work_stopped`가 허용값 밖 | `unknown` | null 을 받지 않는 칸 |
| `ESCALATE`가 아닌데 사유가 있음 | 사유를 `null`로 (`INVALID_VALUE`) | 08 2.5 |

## 설정

| 환경변수 | 기본 | 뜻 (09 4.2) |
|---|---|---|
| `ASK_MORE_UNANSWERED_LIMIT` | 2 | 답을 못 얻은 추가 질문 수 상한 |
| `ASK_MORE_TOTAL_LIMIT` | 5 | 전체 추가 질문 수 상한 |

## 아직 안 한 것

- **실제 Claude로 평가 문항 확인** (WBS 완료 기준). 개인 키로 `dataset/data/eval_inquiries.csv` 몇 개를 돌려 볼 예정입니다.
- 08 3.3 "사용자 메시지에 보안 의심 단어가 있으면 기본값을 쓰더라도 긴급 징후 규칙은 서버에서 따로 적용" — 어떤 단어로 볼지 정해지지 않아 넣지 않았습니다. 이전 판단의 긴급 징후(`prior_urgent_signal`)는 안전 기본값에도 적용됩니다.
