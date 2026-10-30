# 검색 결과 형식 (WBS M3-1-1, C → D)

검색(M3)이 판단·답변(M4)에 넘기는 형식과 검색 기능입니다.

| 파일 | WBS | 내용 |
|---|---|---|
| [`result.py`](result.py) | M3-1-1 | 검색 요청·결과 형식, 역할별 열람 범위, 답변 출처 행 |
| [`evidence.py`](evidence.py) | M3-1-1 | 근거 문장 고르기 `pick_evidence()`, 검색어 만들기 `build_query()` |
| [`service.py`](service.py) | M3-2-2 · M3-2-3 | 검색 `search()`: pgvector 검색, 권한 필터, 단위 복원, 중복 묶기 |
| [`index.py`](index.py) | M3-3-1 준비 | 과거 사례 임베딩 만들기 `embed_legacy()` |
| [`runtime.py`](runtime.py) | M3-2-2 | 서버에서 검색 부르기: 임베딩 모델을 한 번만 열고, 요청마다 `search_fn`(`SearchFnDep`)을 만든다 |
| [`compare.py`](compare.py) | M3-2-1 · M3-4-1 | 임베딩 모델(+리랭커) 비교. DB 없이 가이드 파일과 Golden Set으로 잰다. FAQ 시나리오 코드를 이어받았을 때의 값도 함께 낸다 |
| [`틀린_검색_사례_분석.md`](틀린_검색_사례_분석.md) | M3-4-1 | 평가 46문항 중 1위가 틀린 12문항의 원인 분석 |

테스트: `tests/test_search_result.py`·`test_search_evidence.py` (DB 없이), `tests/test_search_db.py` (`TEST_DATABASE_URL`이 있을 때 임시 DB를 만들어 검사)

## 0. 검색 부르기 (M1·M4)

```python
from app.rag.search import SearchRequest, build_query
from app.rag.search.service import search

resp = search(session, SearchRequest(query=build_query(사용자_글_목록),
                                     service_role=로그인_사용자.service_role), embedder)
```

- `embedder`는 서버가 켜질 때 한 번 연 `Embedder`를 넘깁니다. 모델을 여는 데 노트북 10초, EC2(2 vCPU) 약 28초가 걸립니다.
- **API·서비스에서는 `SearchFnDep`을 받아 M4 판단 흐름에 넘깁니다.** 모델을 여는 일과 DB 세션 연결은 `runtime.py`가 합니다.

  ```python
  from app.rag.search.runtime import SearchFnDep

  def handler(..., search_fn: SearchFnDep):
      run_flow(inp, port, taxonomy, staff_names, search_fn)
  ```

  - 서버(EC2)는 `.env`에 `EMBEDDING_PRELOAD=true`를 두어 시작할 때 모델을 미리 엽니다 (`main.py` lifespan). 모델 파일이 없으면 서버가 시작하지 않습니다.
  - 꺼져 있으면(기본) 첫 검색 때 엽니다. 모델 파일이 없는 PC에서도 서버는 뜨고, 검색할 때만 오류가 납니다.
  - 모델이 메모리를 약 2GB 쓰므로 uvicorn worker는 1개로 띄웁니다 (worker마다 모델을 따로 엽니다).
- 검색은 단독 API가 없고 문의 처리(IQ-08) 안에서 부릅니다 (07 API 설계서).
- 처리 순서는 청크_메타데이터.md 8장 그대로입니다: 벡터 검색(k × 3) → 단위 복원 → 중복 묶기 → 모자라면 k × 6으로 한 번 더.
- **권한 필터 (M3-2-3)**: 열람 범위는 SQL 조건(`view_scope = any(역할이 볼 수 있는 범위)`)으로 겁니다. 범위 밖 문서는 결과·근거·`also_in` 어디에도 나오지 않습니다. 붙이는 조각도 같은 조건을 통과해야 합니다.
- 과거 사례는 `legacy_inquiry_embeddings`가 있어야 나옵니다. `python -m app.rag.search.index legacy`로 한 번 만듭니다 (기본 모델 BGE-M3, 400건, 1분 안쪽).
- **기본 모델은 BGE-M3입니다** ([모델_비교_결과.md](모델_비교_결과.md)). 검색은 `embedder.model_id`와 같은 `model` 값의 임베딩만 찾으므로, DB에 BGE-M3 임베딩이 있어야 결과가 나옵니다.

**문서 결과의 모양은 [청크_메타데이터.md](../청크_메타데이터.md) 8장을 그대로 따릅니다.** 8장의 검색 처리 순서(벡터 검색 → 단위 복원 → 중복 묶기 → 개수 맞추기)와 조인 조건도 바꾸지 않습니다. 이 문서는 8장에 없는 네 가지를 더합니다.

| # | 더한 것 | 이유 |
|---|---|---|
| 1 | 근거 문장 `evidence` | WBS 완료 기준 "근거 문장·출처·점수". 화면에 근거를 짧게 보여 주고, D가 답변이 근거와 맞는지 볼 때 쓴다 |
| 2 | 근거 충분 여부 `sufficient`, 기준값 `threshold` | 가이드만으로 근거가 충분한지. 부족하면 과거 사례를 쓸지 D가 판단한다 (PRD 4.2 검색 순서) |
| 3 | 요청 형식 `SearchRequest` | 열람 범위를 정하는 역할을 어디서 받는지 정해야 한다 |
| 4 | 과거 사례 결과 `LegacyResult` | SEARCH-02 과거 유사 사례 검색 (M3-3-1). 8장은 문서 결과만 다룬다 |

## 1. 요청 `SearchRequest`

| 칸 | 값 | 비고 |
|---|---|---|
| `query` | 검색어 | 빈 문자열 불가. 만드는 규칙은 아래 |
| `service_role` | `EMPLOYEE` / `AGENT` / `ADMIN` | **백엔드가 로그인 정보(`users.service_role`)로 채운다.** 화면이 보낸 값을 쓰지 않는다 (NFR-SEC-02) |
| `user_id` | `users.id` | 지금은 쓰지 않음. "본인 사례만" 같은 규칙이 생기면 쓴다 |
| `sources` | `DOCUMENT`, `LEGACY` | 기본은 둘 다 |
| `category_code` | `HW` 등 | 분류를 먼저 정했으면 좁힌다. 공통 기준(분류 없음)은 항상 포함 (8장) |
| `top_k` | 1~20, 기본 5 | 대상마다 따로 센다 |

**검색어 `query` 만들기** (2026-10-22 결정): 사용자가 글을 여러 번 쓰면 **앞의 사용자 글까지 시간순으로 이어 붙여** 넘깁니다. `build_query(사용자 글 목록)`이 만들어 줍니다.

- 예: "VPN이 안 돼요" → (AI 질문) → "691번이요"이면 검색어는 "VPN이 안 돼요⏎691번이요". "691번이요"만으로는 VPN 가이드를 찾지 못합니다.
- 범위: 이 문의를 연 뒤(다시 열면 그 이후부터) **사용자가 쓴 글만** 넣습니다. AI 메시지는 넣지 않습니다.
- 길이: 1,500자를 넘으면 오래된 글부터 뺍니다. 임베딩 모델이 1024토큰까지만 읽기 때문입니다 (가이드 글 기준 1토큰 ≈ 2자).
- 한계: 대화 중 화제가 바뀌면 이어 붙인 검색어가 흐려질 수 있습니다. Golden Set은 한 번에 묻는 문장이라 이 경우는 시연 시나리오로 확인합니다.

## 2. 응답 `SearchResponse`

```json
{
  "query": "프로그램이 실행하자마자 꺼져요",
  "model": "kure-v1@<리비전>/v1",
  "threshold": 0.5,
  "took_ms": 84,
  "best_score": 0.71,
  "sufficient": true,
  "documents": [
    {
      "source_kind": "DOCUMENT",
      "unit_key": "IT-SW-003@v2.0/item:3.1", "chunk_type": "ITEM",
      "doc_code": "IT-SW-003", "title": "업무용 SW 실행·오류 대응 가이드", "version": "v2.0",
      "location": "3.1", "heading_path": "3. 증상별 조치 방법 > 3.1 프로그램이 멈추거나 바로 꺼질 때 (기본 조치)",
      "text": "머리말 + 조각을 part 순서로 붙인 본문",
      "evidence": ["프로그램을 완전히 종료한 뒤 다시 실행합니다."],
      "chunks": [{"id": 104, "part": 1, "score": null}, {"id": 105, "part": 2, "score": 0.71}],
      "unit_score": 0.71, "score_type": "cosine:kure-v1@<리비전>/v1",
      "inquiry_type_codes": ["SW-03"], "handling": "사용자 직접 조치",
      "view_scope": "ALL", "transfer_policy": "ALLOWED", "also_in": [],
      "citation": "IT-SW-003 3.1"
    }
  ],
  "legacy": [
    {
      "source_kind": "LEGACY",
      "legacy_inquiry_id": 245, "legacy_no": "INQ-2026-00245", "inquiry_type_code": "HW-02",
      "title": "노트북이 안 켜져요",
      "text": "노트북이 안 켜져요 / 메인보드 펌웨어 업데이트 후 디스크 암호화 복구 모드 진입 / 관리 콘솔에서 복구 키 확인·전달 후 정상 부팅",
      "root_cause": "메인보드 펌웨어 업데이트 후 디스크 암호화 복구 모드 진입",
      "resolution": "관리 콘솔에서 복구 키 확인·전달 후 정상 부팅",
      "resolved_at": "2026-07-09 13:51",
      "evidence": [], "score": 0.64, "score_type": "cosine:kure-v1@<리비전>/v1",
      "view_scope": "AGENT", "transfer_policy": "MASKED",
      "citation": "과거 처리 사례 참고 · INQ-2026-00245 (2026-07)"
    }
  ]
}
```

문서 예시는 8장의 예, 과거 사례 예시는 `history.csv`의 실제 행입니다. 점수·시간은 예시 값입니다.

### 근거 문장 `evidence`

- 단위 본문(`text`)에서 질문과 맞는 문장을 **최대 3개** 고릅니다. 맞는 문장이 없으면 빈 목록입니다.
- **본문에 그대로 있는 문장만** 넣습니다. 형식 검사에서 본문에 없는 문장은 오류로 막습니다.
- 답변 근거로 모델에 넣는 것은 여전히 `text` 전체입니다. `evidence`는 화면 표시와 근거 일치 검사용입니다.
- **고르는 방법** (2026-10-22 결정): M3가 `pick_evidence(검색어, text)`로 고릅니다. 본문에서 **질문과 단어가 많이 겹치는 줄**을 최대 3개, 겹치는 줄이 없으면 빈 목록입니다. M4는 `evidence`가 비어 있어도 동작해야 합니다.
  - 한국어는 조사가 붙어 단어가 달라지므로('키' ↔ '키를') 단어를 두 글자씩 잘라 겹침을 셉니다. 두 조각 미만으로 겹치는 줄은 고르지 않습니다.
  - 머리말 줄(`문서 > 장 > 항목`), 소제목(`###`), 속성 줄(`문의 유형: … · …`), 그림 줄(`[그림]`), 6자 미만 줄(`- 사번`)은 뺍니다. "문의 시 알려 주실 정보"·"이관 시 전달 정보"·"준비할 정보" 아래 목록도 뺍니다 (해결 근거가 아니라 준비 항목이라서). 목록 기호(`1.`·`-`)만 떼고 본문 글자는 바꾸지 않습니다.
  - 한계: 단어 겹침이라 뜻은 같고 표현이 다른 문장은 놓칠 수 있고, 겹침이 약한 줄이 골라질 수 있습니다. 검색 API(M3-2-2)를 만든 뒤 Golden Set 결과로 확인합니다.

### 근거 충분 여부 `sufficient`

- `best_score`(**가이드 문서** 결과 중 가장 높은 점수)가 `threshold` 이상이면 참입니다. 과거 사례 점수는 넣지 않습니다.
- `sufficient=true`: 가이드에서 충분히 맞는 내용을 찾음
- `sufficient=false`: **가이드만으로는 부족함. 과거 사례를 쓸지는 D(AI 판단)가 판단**합니다. PRD 4.2 검색 순서를 따릅니다.
  1. 가이드로 근거가 부족하면 과거 사례(`legacy`)를 한 번 더 검토한다.
  2. 과거 사례가 현재 가이드·운영 정책과 충돌하지 않으면 과거 사례로 답할 수 있다. 출처는 "과거 처리 사례 참고"로 구분해 표시한다.
  3. 그래도 근거가 없으면 추가 확인 또는 담당자 연결을 제안한다.
- 과거 사례 결과는 `sufficient`와 상관없이 응답의 `legacy`에 함께 들어 있습니다. 검색을 다시 부르지 않고 바로 검토할 수 있습니다.
- `threshold`는 지금 임시값 0.5입니다. M3-2-1에서 Golden Set으로 다시 정하고, 응답마다 그때 쓴 값을 함께 돌려줍니다.
- 이 값은 점수만 보는 1차 기준입니다. `transfer_policy` 때문에 외부 모델에 넣을 근거가 남지 않는 경우는 D가 판단합니다 (8장 끝).

### 과거 사례 `LegacyResult`

- 대상 표는 `legacy_inquiries`, 임베딩 표는 `legacy_inquiry_embeddings`입니다 (테이블 설계서).
- 열람 범위는 문서와 같은 규칙으로 거릅니다: `legacy_inquiries.view_scope`를 역할에 맞게 고릅니다. **일반 임직원도 과거 사례를 볼 수 있다고 팀에서 합의했습니다.** 시드(`db/seed.py`)는 과거 사례를 `ALL`·`MASKED`로 넣고, 보안(SEC) 사례만 `AGENT`·`BLOCKED`로 넣습니다.
- 요청자·담당자처럼 **사람을 가리키는 칸은 결과에 넣지 않습니다.**
- 출처 표시는 `과거 처리 사례 참고 · INQ-2026-00245 (2026-07)` 형식입니다. PRD 4.2의 "과거 처리 사례 참고" 문구로 가이드 출처와 구분합니다. 화면에 어떻게 보여 줄지는 M6과 확인합니다.

## 3. 열람 범위

`visible_scopes(service_role)`이 역할마다 볼 수 있는 `view_scope`를 돌려줍니다. 검색 쿼리의 조건에 그대로 넣습니다 (청크_메타데이터.md 4장). 규칙은 문의 출처 등 다른 API와 함께 쓰므로 `app/core/permissions.py` 한 곳에서 관리하고, 이 모듈은 같은 함수를 다시 내보냅니다.

| 역할 | 볼 수 있는 `view_scope` |
|---|---|
| `EMPLOYEE` | `ALL` |
| `AGENT` | `ALL`, `AGENT` |
| `ADMIN` | `ALL`, `AGENT`, `ADMIN` |
| 그 밖 | 없음 |

## 4. 답변 출처 저장

D가 답변에 실제로 쓴 결과를 `message_source_rows(used)`에 넘기면 `message_sources` 행이 나옵니다. 청크_메타데이터.md 6장의 스냅샷 규칙을 따릅니다.

- **문서**: 단위를 이루는 조각마다 한 행입니다. `doc_code`·`version`·`location`과 실제로 쓴 본문(`excerpt`)을 함께 저장합니다.
- **과거 사례**: 한 행입니다. `chunk_id`는 비우고 `legacy_inquiry_id`를 채웁니다.
- **`rank`**: D가 넘긴 순서입니다.

## 5. 정한 것

| 항목 | 결정 | 반영 |
|---|---|---|
| 형식 | M4가 이 형식을 그대로 받음 | `docs/08.AI_입출력_형식.md` 1.4 (PR #38) |
| `sufficient=false`의 뜻 | 가이드만으로는 부족함. 과거 사례를 쓸지는 M4가 판단 | PR #44, 08 문서 |
| 일반 임직원의 과거 사례 열람 | 볼 수 있음. 시드는 `ALL`·`MASKED`, 보안(SEC)만 `AGENT`·`BLOCKED` | `db/seed.py` |
| `evidence` | M3가 고름. 질문과 단어가 많이 겹치는 줄 최대 3개, 없으면 빈 목록 | 2026-10-22, `evidence.py` |
| 검색어 `query` | 이 문의를 연 뒤 사용자 글을 시간순으로 이어 붙임 | 2026-10-22, `evidence.py` |
| 임베딩·출처 표 | `document_chunk_embeddings`·`legacy_inquiry_embeddings`·`message_sources` 생성. `message_source_rows()`의 칸과 일치 확인 | 마이그레이션 `d20ad6bde15c` |
