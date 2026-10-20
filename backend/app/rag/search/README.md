# 검색 결과 형식 (WBS M3-1-1, C → D)

검색(M3)이 판단·답변(M4)에 넘기는 형식입니다. 코드는 [`result.py`](result.py), 테스트는 `tests/test_search_result.py`입니다.

**문서 결과의 모양은 [청크_메타데이터.md](../청크_메타데이터.md) 8장을 그대로 따릅니다.** 8장의 검색 처리 순서(벡터 검색 → 단위 복원 → 중복 묶기 → 개수 맞추기)와 조인 조건도 바꾸지 않습니다. 이 문서는 8장에 없는 네 가지를 더합니다.

| # | 더한 것 | 이유 |
|---|---|---|
| 1 | 근거 문장 `evidence` | WBS 완료 기준 "근거 문장·출처·점수". 화면에 근거를 짧게 보여 주고, D가 답변이 근거와 맞는지 볼 때 쓴다 |
| 2 | 근거 충분 여부 `sufficient`, 기준값 `threshold` | D가 AI 안내 / 추가 확인 / 담당자 연결을 고를 기준 (PRD 4.2 "충분한 근거가 없으면 추가 확인 또는 담당자 연결") |
| 3 | 요청 형식 `SearchRequest` | 열람 범위를 정하는 역할을 어디서 받는지 정해야 한다 |
| 4 | 과거 사례 결과 `LegacyResult` | SEARCH-02 과거 유사 사례 검색 (M3-3-1). 8장은 문서 결과만 다룬다 |

## 1. 요청 `SearchRequest`

| 칸 | 값 | 비고 |
|---|---|---|
| `query` | 질문 문장 | 빈 문자열 불가 |
| `service_role` | `EMPLOYEE` / `AGENT` / `ADMIN` | **백엔드가 로그인 정보(`users.service_role`)로 채운다.** 화면이 보낸 값을 쓰지 않는다 (NFR-SEC-02) |
| `user_id` | `users.id` | 지금은 쓰지 않음. "본인 사례만" 같은 규칙이 생기면 쓴다 |
| `sources` | `DOCUMENT`, `LEGACY` | 기본은 둘 다 |
| `category_code` | `HW` 등 | 분류를 먼저 정했으면 좁힌다. 공통 기준(분류 없음)은 항상 포함 (8장) |
| `top_k` | 1~20, 기본 5 | 대상마다 따로 센다 |

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
      "citation": "과거 사례 INQ-2026-00245 (2026-07)"
    }
  ]
}
```

문서 예시는 8장의 예, 과거 사례 예시는 `history.csv`의 실제 행입니다. 점수·시간은 예시 값입니다.

### 근거 문장 `evidence`

- 단위 본문(`text`)에서 질문과 맞는 문장을 **최대 3개** 고릅니다. 맞는 문장이 없으면 빈 목록입니다.
- **본문에 그대로 있는 문장만** 넣습니다. 형식 검사에서 본문에 없는 문장은 오류로 막습니다.
- 답변 근거로 모델에 넣는 것은 여전히 `text` 전체입니다. `evidence`는 화면 표시와 근거 일치 검사용입니다.
- 고르는 방법은 검색 API(M3-2-2)를 만들 때 정합니다. 후보는 둘입니다. 문장마다 다시 임베딩하는 방법은 정확하지만 느리고, 질문과 겹치는 단어로 고르는 방법은 빠릅니다.

### 근거 충분 여부 `sufficient`

- `best_score`(**문서** 결과 중 가장 높은 점수)가 `threshold` 이상이면 참입니다.
- **과거 사례만으로는 충분하다고 보지 않습니다.** 과거 사례는 현재 정책·상황과 맞는지 따로 확인해야 하기 때문입니다 (PRD 4.2, 설계서 7.5).
- `threshold`는 지금 임시값 0.5입니다. M3-2-1에서 Golden Set으로 다시 정하고, 응답마다 그때 쓴 값을 함께 돌려줍니다.
- 이 값은 점수만 보는 1차 기준입니다. `transfer_policy` 때문에 외부 모델에 넣을 근거가 남지 않는 경우는 D가 판단합니다 (8장 끝).

### 과거 사례 `LegacyResult`

- 대상 표는 `legacy_inquiries`, 임베딩 표는 `legacy_inquiry_embeddings`입니다 (테이블 설계서).
- 열람 범위는 문서와 같은 규칙으로 거릅니다: `legacy_inquiries.view_scope`를 역할에 맞게 고릅니다. 그래서 일반 임직원이 과거 사례를 볼 수 있는지는 **시드에서 각 행에 넣는 `view_scope` 값으로** 정해집니다. 기본값 `ADMIN`이면 일반 임직원 검색에는 나오지 않습니다.
- 요청자·담당자처럼 **사람을 가리키는 칸은 결과에 넣지 않습니다.**
- 출처 표시는 `과거 사례 INQ-2026-00245 (2026-07)` 형식입니다.

## 3. 열람 범위

`visible_scopes(service_role)`이 역할마다 볼 수 있는 `view_scope`를 돌려줍니다. 검색 쿼리의 조건에 그대로 넣습니다 (청크_메타데이터.md 4장).

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

## 5. 합의할 것

| 누구 | 무엇 |
|---|---|
| D (M4) | 이 형식으로 판단 흐름(M4-2-1)을 만들 수 있는지. 특히 `sufficient`의 뜻, `evidence` 사용 방법 |
| B (M2) | 8장에 이 문서 링크를 다는 것 |
| A (M1) | `document_chunk_embeddings`·`legacy_inquiry_embeddings` 마이그레이션 (검색 API 전에 필요). `message_sources`를 6장대로 만들 때 `message_source_rows()`의 칸 이름과 맞추기 |
| 팀 | 일반 임직원에게 과거 사례를 보여 줄지 (`legacy_inquiries.view_scope` 시드 값) |
