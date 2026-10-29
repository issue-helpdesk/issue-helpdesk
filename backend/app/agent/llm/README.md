# AI 판단 호출부 (WBS M4-2-2)

[docs/08.AI_입출력_형식.md](../../../../docs/08.AI_입출력_형식.md)를 코드로 옮기고 Claude를 부르는 곳입니다. **형식을 바꾸려면 문서를 먼저 고칩니다.**

## 한눈에 보기

```
AIInput ─▶ ① 치환 ─▶ ② 근거 거르기 ─▶ ③ Claude 호출 ─▶ ④ 형식 검사 ─▶ JudgeResult
              (docs/10)    (docs/10)         │      실패하면 한 번 다시
                             │                ▼
                     모두 차단이면 부르지 않음   그래도 안 되면 안전 기본값 (08 3.3)
```

| 파일 | 내용 | 근거 |
|---|---|---|
| [`schemas.py`](schemas.py) | 입력·출력 형식 (Pydantic), 안전 기본값 | 08 1·2장, 3.3 |
| [`call.py`](call.py) | `call_judge()` 호출 흐름 | 08 3.2 1~3단계, docs/10 3.1·3.3·4장 |
| [`prompt.py`](prompt.py) | 시스템 프롬프트, 보낼 값 고르기 | 08 1장 `LLM 전송` 열 |
| [`port.py`](port.py) | 모델 호출 공통 규칙 (LLMPort) | 시스템 설계서 6.3 |
| [`claude.py`](claude.py) | Claude Adapter | 시스템 설계서 6.3 |
| [`mock.py`](mock.py) | Mock Adapter (API 키 없이 시험) | 시스템 설계서 6.3 |
| [`config.py`](config.py) | `.env`의 `LLM_API_KEY`·`LLM_MODEL` | 시스템 설계서 16.2 |

시험: `tests/test_llm.py` (DB·API 키 없이 돌아갑니다)

| 이번에 하지 않는 것 | 누가 |
|---|---|
| 08 3.2 4~9단계 (허용값·세부 유형·추가 질문·근거 확인, 처리 방향 보정), 5.3 긴급도 규칙 | 판단 흐름 M4-2-1 |
| `inquiry_assessments`·`llm_calls`·`audit_logs` 저장 | 백엔드 M1 (값은 `JudgeResult`로 넘김) |

---

## 쓰는 법

```python
from app.agent.llm import AIInput, CategoryInfo, Taxonomy, TypeInfo, call_judge, get_llm_adapter

taxonomy = Taxonomy(
    categories=tuple(CategoryInfo(c.code, c.name, c.description or '') for c in 카테고리_목록),   # DB categories
    types=tuple(TypeInfo(t.code, t.category_code, t.name, t.request_kind, t.default_urgency)
                for t in 활성_세부유형_목록),                                                     # DB inquiry_types
)

r = call_judge(
    AIInput(session_id=..., inquiry_id=..., message=저장된_글, history=최근_대화, collected_facts=...,
            ask_more_count=..., user_context={...}, search=검색결과_또는_None),
    get_llm_adapter(),       # 시험·키 없을 때는 MockAdapter()
    taxonomy,
    직원_이름_목록,           # users.name (치환용)
    'CLASSIFY',              # llm_calls.purpose. 1차(검색 전) CLASSIFY, 2차(검색 뒤) ANSWER
)
```

- `message`·`history`에는 **DB에 저장된 글**(저장 전 가림을 거친 글)을 넣습니다. 치환은 이 함수가 합니다.
- `history`를 몇 턴 넣을지는 아직 합의 전입니다 (08 5.6). 부르는 쪽이 잘라서 넣습니다.

## 결과 쓰는 법 (`JudgeResult`)

| 값 | 뜻 | 어디에 |
|---|---|---|
| `output` | 형식 검사를 통과한 AI 출력, 또는 안전 기본값. 항상 있음 | 판단 흐름이 보정한 뒤 확정값으로 |
| `ai_output` | AI 원본 (dict). 안전 기본값·`ALL_BLOCKED`면 `None` | `inquiry_assessments.ai_output` (08 5.4) |
| `failure` | `None` · `AI_FAILED` · `ALL_BLOCKED` | `override_reasons`의 `rule`, `audit_logs` `FAIL`·`BLOCK` |
| `error_code` | 실패 사유 (아래 표) | `override_reasons`의 `reason`, `FILTER_FAILED`면 `audit_logs` `FAIL`·`FILTER_FAILED` |
| `evidence` | Claude에 보낸 근거(`documents`·`legacy`)와 뺀 근거(`blocked`·`failed`). 검색 전이면 `None` | 3.2 8단계 근거 확인, `audit_logs` `DOC_BLOCKED` |
| `calls` | 호출마다 한 행 (다시 부르면 2행) | `llm_calls` (`inquiry_id`는 저장할 때) |

**`error_code`**

| 값 | 언제 | 다시 부르나 |
|---|---|---|
| `INVALID_JSON` | JSON으로 읽히지 않음 | 한 번 |
| `SCHEMA_INVALID` | 필수 키가 없거나 자료형이 틀림 | 한 번 |
| `MAX_TOKENS` | 응답이 길어 잘림 | 한 번 |
| `UNSUPPORTED_VERSION` | `schema_version`이 지원 목록에 없음 | 안 함 (08 3.2 1단계) |
| `TIMEOUT` · `CONNECTION` · `RATE_LIMIT` · `HTTP_<코드>` | API 오류. SDK가 이미 1번 더 시도함 | 안 함 |
| `REFUSAL` | Claude가 안전 판단으로 거절. 다른 모델로 넘기지 않고 안전 기본값(담당자 연결 제안)으로 끝냄 | 안 함 |
| `FILTER_FAILED` | 치환 중 오류. **Claude를 부르지 않음** (docs/10 3.3) | — |

## 지켜야 할 것

- **안전 기본값이 와도 오류를 던지지 않습니다.** `failure`를 보고 기록만 남기면 됩니다 (09 T11 → `offer`).
- `ALL_BLOCKED`면 화면 안내는 `app.agent.sensitive.BLOCKED_NOTICE`를 씁니다 (민감정보 필터 README).
- `ai_output`에는 치환된 값(`[직원1]`)이 그대로 있습니다. 원래 이름으로 되돌리지 않습니다 (docs/10 3.1).
- 프롬프트·응답 원문은 로그에 찍지 않습니다. 실패 사유 코드만 남깁니다 (docs/10 5.3).
- **허용값 밖의 값은 여기서 막지 않습니다.** 예를 들어 `category_code='XYZ'`도 통과하고, 판단 흐름이 `null`로 바꿉니다 (08 3.2 4단계). Claude에는 허용값을 출력 형식으로 알려 주므로 보통은 생기지 않습니다.

## Claude 설정

| 항목 | 값 | 이유 |
|---|---|---|
| 모델 | `LLM_MODEL`, 기본 `claude-sonnet-5-5` | |
| 출력 | JSON 형식 지정 (`output_config.format`) | `AIOutput` 모양으로만 답하게 함 |
| 거절 시 다른 모델로 | 끔 | 거절되면 담당자에게 넘긴다 (08 "불확실하면 사람에게"). 긴급 징후 규칙은 서버가 따로 적용 (08 3.3) |
| 시스템 프롬프트 캐시 | 켬 | 호출마다 같아서 비용·시간 절약 |
| 제한 시간 | 30초, 넘으면 1번 더 (최악 약 1분) | 응답 시간 목표가 없어 정한 값. 메시지 하나에 1·2차 두 번 부르므로 메시지당 최악 약 2분 |

⚠️ API 키가 아직 없어 **실제 Claude 호출은 확인하지 않았습니다.** 키를 받으면 실제 문의 몇 개로 아래를 확인합니다.

| 확인할 것 | 맞지 않으면 |
|---|---|
| 출력 형식(JSON Schema)을 API가 받는지 | `output_json_schema()` 고치기 |
| 1·2차 응답 시간 | 30초에 자주 걸리면 생각 깊이(`output_config.effort`)를 낮추거나 제한 시간 조정 |
| 호출당 토큰·비용 | 시스템 프롬프트 캐시가 맞는지(`cache_read_input_tokens`) 확인 |
