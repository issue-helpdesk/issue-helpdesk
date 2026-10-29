# 가이드 적재 (WBS M2-2-1 · M2-3-1)

`dataset/guides/manifest.json`의 검색 대상 문서(`rag_target=true`, 56종)를 Knowledge 표에 넣습니다. 규칙 원본은 [청크_메타데이터.md](../청크_메타데이터.md) 7장입니다.

관리자가 올린 버전 하나를 적재하는 **업로드 적재**는 아래 "업로드 적재" 절 (`upload.py`).

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
| 교체 중 오류 | 롤백 (`--apply-document`로 바꾼 문서 정보도 같이). 현행이 아닌 버전은 `FAILED` + `ingest_error`. 이전 현행은 그대로. 다시 실행하면 그 버전을 새로 넣는다 |
| manifest에 `transfer_policy` 없음 | 경고하고 `BLOCKED`로 적재 |

- **현행 전환은 이번 실행에서 처음 등록한 버전이거나 문서에 현행이 없을 때만** 한다. 이미 있던 버전(`DONE`, 실패했던 `FAILED`·`PENDING` 재시도)은 다른 현행이 있으면 `DONE`까지만 하고 `현행 아님`으로 알린다 (관리자가 API로 고른 현행을 적재가 되돌리지 않게). 실패했던 새 버전을 고쳐 넣고 바로 현행으로 하려면 `--force-activate`.
- **이미 있는 버전의 정책**(`view_scope`·`transfer_policy`, 관리자가 바꿨을 수 있다): manifest가 더 넓으면 DB 값을 두고 알린다. **manifest가 더 좁으면**(예: `ALLOWED` → `BLOCKED`) 검증 실패로 멈춘다 — 보내면 안 되는 본문이 외부 모델로 나가지 않게. 확인 뒤 `--apply-policy`로 manifest 값을 적용한다 (감사 로그 `DOCUMENT_POLICY_CHANGE`). 처음 넣는 버전은 manifest 값을 쓴다. 검증 뒤 임베딩하는 사이(수십 분)에 정책이 바뀔 수 있어, 교체 때 문서를 잠근 뒤 한 번 더 비교하고 더 좁아졌으면 그 문서만 멈춘다.
- 잠금 순서는 문서 → 버전 → 청크다. 교체와 `activate()`가 같은 순서라 관리자 API 전환과 겹쳐도 교착되지 않는다.
- **현행 버전의 청크를 교체할 때 검색과 겹치면** 결과가 섞이거나 검색이 오류로 끝날 수 있다. 검색이 점수(`HITS_SQL`)와 본문(`PIECES_SQL`)을 따로 읽는데 그 사이 청크 id가 바뀌기 때문이다 (M2-3-1 재검수). 사용자가 적을 때 실행한다. 근본 수정은 검색 쪽(C)에 전달. 업로드 적재는 현행의 청크 id를 바꾸지 않는다 (아래).
- 지정하지 않은 모델의 임베딩은 청크를 다시 넣을 때 글이 같은 것만 옮긴다. 글이 바뀐 청크는 빠지고 출력에 `… 임베딩 n개 빠짐`이 나온다 → 그 모델로 다시 실행.
- **이미 있는 문서의 정보**(`title`·`doc_type`·`category_code`·`owner_group_id`, 관리자가 화면에서 고쳤을 수 있다): DB 값을 두고 파일과 다르면 알린다. 파일 값으로 맞추려면 `--apply-document`. 처음 만드는 문서는 파일 값을 쓴다. `is_active`는 건드리지 않는다.
- manifest에서 빠진 문서는 지우지 않는다. 짝 문서(`pair`)는 표에 칸이 없어 넣지 않는다 (6장 "나중에").

## 현행 전환 `activate(conn, version_id, actor_id=None)`

관리자 API(A, `PATCH …/versions/{id}` `isCurrent: true`, docs/api/04)와 적재가 같이 쓰는 함수. 부른 쪽 트랜잭션 안에서 돌고 commit하지 않는다.

- `DONE`이 아니면 거부, 이미 현행이면 `False`
- 문서 행을 잠그고 → 기존 현행 `false` → 이 버전 `true` (DB 제약: 현행은 문서마다 하나, `DONE`만)
- 처음 현행이 되는 버전이면 `activated_at = now()`, 현행에서 내려가도 보존 (마이그레이션 `478ccde3a990`. 이미 현행이던 버전은 `registered_at`으로 채움)
- 감사 로그 `audit_logs`: `event_type = DOCUMENT_VERSION_ACTIVATE`, `target_type = document`, `target_id` = 문서 id, `result` = `v2.0 → v2.1` (처음이면 `없음 → v2.0`)

## 업로드 적재 `ingest_version(conn, version_id, embedder)` (M2-3-1, `upload.py`)

관리자가 올린 버전 **하나**를 적재한다. 업로드 API(DC-07)가 파일을 저장하고 버전 행을 만든 뒤 백그라운드로 부른다.

| 단계 | 누가 | 하는 일 |
|---|---|---|
| 문서 등록 | API DC-02 | `knowledge_documents` 행 (문서 번호·종류·제목·분류·관리 그룹) |
| 파일 업로드 | API DC-07 | 파일 저장 → `document_versions` 행: `ingest_status = PENDING`, `is_current = false`, `file_path`, 관리자가 고른 `view_scope`·`transfer_policy`(기본 ADMIN·BLOCKED), `registered_by` → 커밋 → 202 응답 → **백그라운드로 `ingest_version`** |
| 적재 | `ingest_version` | 아래 표 → `DONE` 또는 `FAILED` + `ingest_error` |
| 상태 확인 | API DC-08 | `ingest_status`·`ingest_error`(관리자에게 그대로 보여 줄 문구)·청크 수 |
| 현행 전환 | API DC-09 | `activate()`. 이때부터 검색에 나온다. **적재는 현행 전환을 하지 않는다** (DC-07) |

| 적재 단계 | 내용 | 실패하면 |
|---|---|---|
| 맡기 | `PENDING`·`FAILED`이고 현행이 아닌 버전만. `DONE`·현행은 `SKIPPED`. **`reload=True`**(`--reload`)면 `DONE`·현행도 다시 적재 (쓰기 행 참고) | |
| 파일 | `file_path`: 상대 경로면 `files_root`(기본 저장소 루트) 기준, 그 밖으로 나가면 거부. 절대 경로는 검사 없이 그대로 (아래 호출 약속). PDF·DOCX·PPTX·MD·TXT | 파서 안내 문구 (`암호가 걸린 문서입니다…`, `빈 파일입니다.` …) |
| 대조 (DB가 기준) | 파일 머리말의 문서 번호·버전이 등록값과 다르면 실패. 없으면 등록값을 쓴다 (청크 키가 저장된 파일 이름에 기대지 않게). 열람 범위·전송 정책은 버전 행 값, 제목·분류는 문서 행 값 — 파일과 다르면 경고만 | `파일의 문서 번호(…)가 등록한 문서(…)와 다릅니다` |
| 청크 | `chunk_document` → `validate()`. 파서 경고·보수 모드는 실패로 보지 않고 경고 (일반 업로드 파일은 정리본과 달리 경고가 흔하다) | 검증 문제 |
| 문의 유형 코드 | `inquiry_types`에 없는 코드는 **청크에서 빼고 적재**, 경고. 검색은 되고, 판단 흐름에 표에 없는 코드가 가지 않는다. 유형을 등록한 뒤 **`reload=True`로 다시 적재**(`--version-id N --reload`)하면 들어간다 (일반 호출은 `DONE`이라 `SKIPPED`). 새 유형 등록은 팀 협의 (`unknown_inquiry_types()` 자리) | |
| 임베딩 | 모델 하나 (기본 `bge-m3`, 로컬이라 `BLOCKED` 문서도 밖으로 나가지 않음). DB 트랜잭션 밖 | |
| 쓰기 | 한 트랜잭션: 문서 → 버전 잠금 → 상태 다시 확인(그새 끝났으면 `SKIPPED`) → 청크 통째로 교체 → 임베딩 → `DONE` | 롤백 → `FAILED` + 사유. 현행·다른 버전은 그대로. 실패를 남길 대상이 없으면(그새 다른 작업이 `DONE`, 버전이 지워짐) `SKIPPED`, 원래 오류는 로그에만 |

- 결과 `{'version_id', 'status': DONE·FAILED·SKIPPED, 'chunks', 'error', 'warnings', 'activated'}`. 경고는 로그(`app.rag.ingest`)에도 남는다. 경고를 화면에 보여 줄 칸(`ingest_meta`)은 아직 없다 (청크_메타데이터 6장 추가 요청 칸).
**reload로 `DONE` 버전을 다시 넣을 때** (새로 만든 청크를 DB 청크와 비교)

| 경우 | 동작 |
|---|---|
| 뼈대(`seq`·`unit_key`·`part`·`chunk_type`)와 본문(`content`)이 같음 | **같은 청크 id**에 이름표(`meta`·`heading_path`·`location`)만 고쳐 쓴다. 바뀐 칸은 경고 (`이름표 바뀜 item:3.4: inquiry_type_codes [] → ["HW-10"]`, 청크 10개까지). 임베딩 입력이 바뀐 벡터만 같은 id에서 갱신. 빠진 문의 유형 코드 넣기는 이 경우 |
| 다름, **현행** | **거부** `현행 버전의 내용(청크 구성이나 본문)이 파일과 다릅니다. 새 버전으로 올린 뒤 현행 전환하세요`. DB 그대로. 현행의 청크 id를 바꾸면 검색이 이전 점수와 새 본문을 섞거나 오류로 끝날 수 있어서 (재검수 P2) |
| 다름, 현행 아님 | 통째로 교체 (검색에 안 나온다). 다른 모델의 벡터는 글이 같은 것만 옮기고 빠진 수를 경고 |
| 실패 | 결과만 `FAILED` + 사유. DB는 `DONE`·청크 그대로 (DC-08에는 마지막 성공 적재가 보인다. 실패는 결과·명령 출력·로그로) |

- **호출 약속**: 연결은 이 작업 전용으로 연다. `ingest_version`·`resume_pending`은 받은 연결에서 commit·rollback 한다 (`activate()`와 다르다). 부르기 전에 같은 연결로 한 쓰기도 같이 확정된다. `file_path`에는 업로드 API가 만든 값만 넣는다 (사용자 입력을 그대로 넣지 않는다). 저장 위치가 정해지면 절대 경로도 그 안인지 검사를 더한다. `file_path`는 그 버전의 파일을 가리킨다고 믿는다 (다른 버전 파일로 덮였으면 머리말 대조에서 실패한다).
- **일반 호출**은 같은 버전을 동시에 두 번 불러도 한 번만 적재된다 (reload는 부른 만큼 처리하고 나중에 잠금을 얻은 쪽이 남는다). 한쪽이 실패해도 다른 쪽이 끝냈으면 실패한 쪽은 `SKIPPED` (원래 오류는 로그에만). 실패한 버전은 파일을 고친 뒤 다시 부르면 된다.
- **멈춘 PENDING** (적재 중 서버가 꺼짐): `resume_pending(conn, embedder)`가 10분 넘게 `PENDING`인 버전을 다시 적재한다. 서버 시작 때나 명령으로.
- 모델은 한 번 열어 두고 같이 쓴다 (여는 데 10초·메모리 2~3GB). 호출 쪽(API)이 프로세스에 하나만 만들어 넘긴다.
- `ingest_error`에는 내부 경로를 넣지 않는다. 예상 못 한 오류는 `적재 중 오류가 났습니다 (종류)`만 남기고 자세한 내용은 로그로.

## 명령 (backend 폴더에서)

```bash
uv run python -m app.rag.ingest --embedder fake                                   # 검증까지만 (DB 없이, 모델 없이)
uv run python -m app.rag.ingest --embedder fake --database-url <임시 DB>           # 임시 DB에 적재 (가짜 벡터)
uv run python -m app.rag.ingest --database-url <임시 DB>                           # 기본 모델(bge-m3) 실제 임베딩
uv run python -m app.rag.ingest --database-url <DB> --models kure-v1,bge-m3       # 여러 모델 (비교할 때)
uv run python -m app.rag.ingest --database-url <DB> --drop-model kure-v1@8b418a5/v1  # 한 모델 임베딩 지우기
uv run python -m app.rag.ingest --database-url <DB> --version-id 57                # 업로드 적재: 버전 하나 (다시 시도)
uv run python -m app.rag.ingest --database-url <DB> --version-id 57 --reload       # 업로드 적재: DONE·현행도 다시 (빠진 문의 유형 코드 넣기)
uv run python -m app.rag.ingest --database-url <DB> --resume-pending               # 업로드 적재: 멈춘 PENDING 다시
```

| 옵션 | 뜻 |
|---|---|
| `--database-url` | 적재할 DB. **없으면 검증까지만 한다. `.env`는 읽지 않는다** |
| `--allow-remote` | localhost가 아닌 DB(공유 DB)에 쓸 때 꼭 줘야 한다. 판단은 libpq가 실제로 접속할 곳(주소 뒤 `?host=`·`hostaddr`·여러 호스트·`PGHOST`·`service`)으로 하고, `connect()`도 같은 검사를 한다 |
| `--apply-policy` | 이미 있는 버전의 정책을 manifest 값으로 바꾼다 (넓히는 쪽 포함) |
| `--apply-document` | 이미 있는 문서의 제목·종류·분류·관리 부서를 파일 값으로 바꾼다 |
| `--force-activate` | 다른 현행이 있어도 이번에 넣은 버전을 현행으로 |
| `--dry-run` | DB를 주어도 읽기(기준 데이터·기존 벡터 검사)만 한다 |
| `--embedder fake` | 모델 파일 없이 글에서 결정적으로 만든 1024차원 단위 벡터. `model` 값이 `fake-…`라 실제 벡터와 섞이지 않는다 |
| `--models` | 기본은 검색 기본 모델 `DEFAULT_MODEL`(`bge-m3`, M3-2-1 비교로 결정). 쉼표로 여러 모델 |
| `--docs` | 이 문서만 (쉼표로 구분) |
| `--no-activate` | `DONE`까지만, 현행 전환은 하지 않는다 |
| `--no-baseline` | 기준표 비교를 건너뛴다 (새 문서·청커 수정 확인용) |
| `--version-id` | 업로드 적재: 이 버전 하나 (`PENDING`·`FAILED`). 현행 전환은 하지 않는다. 모델은 하나만 |
| `--reload` | `--version-id`와 같이: `DONE`·현행 버전도 다시 적재 (문의 유형을 등록한 뒤 빠진 코드를 넣을 때) |
| `--resume-pending` | 업로드 적재: 10분 넘게 `PENDING`인 버전을 다시 적재 |

실제 모델은 [`embedding/README.md`](../embedding/README.md)대로 설치·받기를 먼저 한다. CPU로 712청크에 BGE-M3 약 12분 (0.99초/청크, 10.25 `smoke`. KURE-v1은 0.79초/청크). 모델은 임베딩할 글이 있을 때만 연다.

## 임시 DB로 시험

```bash
docker run -d --name itssue-ingest-db -e POSTGRES_PASSWORD=verify -p 55433:5432 pgvector/pgvector:pg17
docker exec itssue-ingest-db psql -U postgres -c "create database ingest"
export DATABASE_URL=postgresql://postgres:verify@localhost:55433/ingest SEED_INITIAL_PASSWORD=verify-only
cd backend && uv run alembic upgrade head && cd .. && uv run python db/seed.py   # 표 + 기준 데이터
cd backend && uv run python -m app.rag.ingest --embedder fake --database-url $DATABASE_URL

TEST_DATABASE_URL=postgresql://postgres:verify@localhost:55433/postgres uv run pytest tests/test_ingest.py tests/test_ingest_db.py tests/test_ingest_upload.py
```

DB 시험은 `TEST_DATABASE_URL`이 localhost일 때만 돌고, 같은 서버에 무작위 이름의 전용 DB(`itssue_test_xxxxxxxx`)를 만들어 그 안에서만 작업한 뒤 지운다.
