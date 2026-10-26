# 가이드 적재 (WBS M2-2-1)

`dataset/guides/manifest.json`의 검색 대상 문서(`rag_target=true`, 56종)를 Knowledge 표에 넣습니다. 규칙 원본은 [청크_메타데이터.md](../청크_메타데이터.md) 7장입니다.

| 단계 | 하는 일 | 실패하면 |
|---|---|---|
| 준비 (DB 밖) | md 파싱 → `chunk_document` → 모델마다 임베딩. 같은 `model` + 같은 `source_text`인 DB 벡터는 다시 쓴다 (청크를 지우기 전에 미리 읽어 둔다) | |
| 검증 | 파서 경고 0, `validate()`, 문서별 청크·항목·단위 수 = [`chunker/baseline.json`](../chunker/baseline.json), 문의 유형 코드가 `inquiry_types`에, 관리 부서가 `support_groups`에, 모델이 하나 이상·겹치지 않음, 지정한 **모든 모델**의 임베딩이 청크마다 있음(1024차원 단위 벡터), 이미 있는 버전의 정책보다 manifest가 더 좁지 않음 | **DB에 아무것도 쓰지 않는다** |
| 교체 (문서마다 짧은 트랜잭션) | 아래 표 | 그 문서만 롤백, 나머지 문서는 계속 |
| 끝 | 현행 버전 기준 분류별 문서·청크·모델별 임베딩 수 출력 | |

| 경우 | 동작 |
|---|---|
| 새 버전 | `PENDING`·비현행으로 넣고 커밋 → 한 트랜잭션에서 문서 칸·청크·임베딩 → `DONE` → 현행 전환(`activate`) |
| 같은 버전, 내용이 바뀜 (파서·청커 수정 뒤) | 한 트랜잭션에서 그 버전 청크를 **통째로 지우고 새로 넣는다** (순번 upsert 금지, 7장). 청크 id가 새로 생긴다 |
| 같은 버전, 청크 행이 같음 | 청크는 그대로(id 유지). 지정한 모델 벡터는 지금 입력으로 맞추고, 지정하지 않은 모델 중 임베딩 입력(머리말의 문서 제목 등)이 바뀐 벡터는 지우고 알린다. 두 번 실행해도 결과가 같다 |
| 교체 중 오류 | 롤백 (문서 제목·분류 변경도 같이). 현행이 아닌 버전은 `FAILED` + `ingest_error`. 이전 현행은 그대로. 다시 실행하면 그 버전을 새로 넣는다 |
| manifest에 `transfer_policy` 없음 | 경고하고 `BLOCKED`로 적재 |

- **현행 전환은 이번 실행에서 처음 등록한 버전이거나 문서에 현행이 없을 때만** 한다. 이미 있던 버전(`DONE`, 실패했던 `FAILED`·`PENDING` 재시도)은 다른 현행이 있으면 `DONE`까지만 하고 `현행 아님`으로 알린다 (관리자가 API로 고른 현행을 적재가 되돌리지 않게). 실패했던 새 버전을 고쳐 넣고 바로 현행으로 하려면 `--force-activate`.
- **이미 있는 버전의 정책**(`view_scope`·`transfer_policy`, 관리자가 바꿨을 수 있다): manifest가 더 넓으면 DB 값을 두고 알린다. **manifest가 더 좁으면**(예: `ALLOWED` → `BLOCKED`) 검증 실패로 멈춘다 — 보내면 안 되는 본문이 외부 모델로 나가지 않게. 확인 뒤 `--apply-policy`로 manifest 값을 적용한다 (감사 로그 `DOCUMENT_POLICY_CHANGE`). 처음 넣는 버전은 manifest 값을 쓴다. 검증 뒤 임베딩하는 사이(수십 분)에 정책이 바뀔 수 있어, 교체 때 문서를 잠근 뒤 한 번 더 비교하고 더 좁아졌으면 그 문서만 멈춘다.
- 잠금 순서는 문서 → 버전 → 청크다. 교체와 `activate()`가 같은 순서라 관리자 API 전환과 겹쳐도 교착되지 않는다.
- 지정하지 않은 모델의 임베딩은 청크를 다시 넣을 때 글이 같은 것만 옮긴다. 글이 바뀐 청크는 빠지고 출력에 `… 임베딩 n개 빠짐`이 나온다 → 그 모델로 다시 실행.
- manifest에서 빠진 문서는 지우지 않는다. 짝 문서(`pair`)는 표에 칸이 없어 넣지 않는다 (6장 "나중에").

## 현행 전환 `activate(conn, version_id, actor_id=None)`

관리자 API(A, `PATCH …/versions/{id}` `isCurrent: true`, docs/api/04)와 적재가 같이 쓰는 함수. 부른 쪽 트랜잭션 안에서 돌고 commit하지 않는다.

- `DONE`이 아니면 거부, 이미 현행이면 `False`
- 문서 행을 잠그고 → 기존 현행 `false` → 이 버전 `true` (DB 제약: 현행은 문서마다 하나, `DONE`만)
- 처음 현행이 되는 버전이면 `activated_at = now()`, 현행에서 내려가도 보존 (마이그레이션 `478ccde3a990`. 이미 현행이던 버전은 `registered_at`으로 채움)
- 감사 로그 `audit_logs`: `event_type = DOCUMENT_VERSION_ACTIVATE`, `target_type = document`, `target_id` = 문서 id, `result` = `v2.0 → v2.1` (처음이면 `없음 → v2.0`)

## 명령 (backend 폴더에서)

```bash
python -m app.rag.ingest --embedder fake                                   # 검증까지만 (DB 없이, 모델 없이)
python -m app.rag.ingest --embedder fake --database-url <임시 DB>           # 임시 DB에 적재 (가짜 벡터)
python -m app.rag.ingest --database-url <임시 DB>                           # 두 모델(kure-v1,bge-m3) 실제 임베딩
python -m app.rag.ingest --database-url <DB> --models bge-m3               # 한 모델만 다시 넣기
python -m app.rag.ingest --database-url <DB> --drop-model bge-m3@5617a9f/v1   # 한 모델 임베딩 지우기 (모델을 정한 뒤)
```

| 옵션 | 뜻 |
|---|---|
| `--database-url` | 적재할 DB. **없으면 검증까지만 한다. `.env`는 읽지 않는다** |
| `--allow-remote` | localhost가 아닌 DB(공유 DB)에 쓸 때 꼭 줘야 한다. 판단은 libpq가 실제로 접속할 곳(주소 뒤 `?host=`·`hostaddr`·여러 호스트·`PGHOST`·`service`)으로 하고, `connect()`도 같은 검사를 한다 |
| `--apply-policy` | 이미 있는 버전의 정책을 manifest 값으로 바꾼다 (넓히는 쪽 포함) |
| `--force-activate` | 다른 현행이 있어도 이번에 넣은 버전을 현행으로 |
| `--dry-run` | DB를 주어도 읽기(기준 데이터·기존 벡터 검사)만 한다 |
| `--embedder fake` | 모델 파일 없이 글에서 결정적으로 만든 1024차원 단위 벡터. `model` 값이 `fake-…`라 실제 벡터와 섞이지 않는다 |
| `--models` | 기본 `kure-v1,bge-m3` (두 모델 모두 넣어 비교하기로 결정, 10.25) |
| `--docs` | 이 문서만 (쉼표로 구분) |
| `--no-activate` | `DONE`까지만, 현행 전환은 하지 않는다 |
| `--no-baseline` | 기준표 비교를 건너뛴다 (새 문서·청커 수정 확인용) |

실제 모델은 [`embedding/README.md`](../embedding/README.md)대로 설치·받기를 먼저 한다. CPU로 712청크 × 2모델 약 21분 (KURE-v1 0.79초/청크, BGE-M3 0.99초/청크, 10.25 `smoke`). 모델은 임베딩할 글이 있을 때만 연다.

## 임시 DB로 시험

```bash
docker run -d --name itssue-ingest-db -e POSTGRES_PASSWORD=verify -p 55433:5432 pgvector/pgvector:pg17
docker exec itssue-ingest-db psql -U postgres -c "create database ingest"
export DATABASE_URL=postgresql://postgres:verify@localhost:55433/ingest SEED_INITIAL_PASSWORD=verify-only
cd backend && alembic upgrade head && cd .. && python db/seed.py          # 표 + 기준 데이터
cd backend && python -m app.rag.ingest --embedder fake --database-url $DATABASE_URL

TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres pytest tests/test_ingest.py tests/test_ingest_db.py
```

DB 시험은 `TEST_DATABASE_URL`이 localhost일 때만 돌고, 같은 서버에 무작위 이름의 전용 DB(`itssue_test_xxxxxxxx`)를 만들어 그 안에서만 작업한 뒤 지운다.
