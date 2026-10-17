# RAG 문서 처리

가이드 문서를 읽어(파싱) 검색 단위(청크)로 나누고, 청크와 문서에 붙일 정보를 만든다.

| 파일 | WBS | 내용 |
|---|---|---|
| [`parser/`](parser/README.md) | M2-1-1 | 가이드 문서(PPTX·PDF·DOCX·MD·TXT) → 같은 모양의 결과 `ParsedDocument` |
| [`chunker.py`](chunker.py) | M2-1-2 · M2-1-3 | `ParsedDocument` → 검색 단위 `Chunk` + 문서 정보 `document_record()` |
| [`청크_규칙.md`](청크_규칙.md) | **M2-1-2 산출물** | 청크를 나누는 규칙, `unit_id`, 샘플, 결과 수치 |
| [`청크_메타데이터.md`](청크_메타데이터.md) | **M2-1-3 산출물** | 문서·청크 필드, DB 표, 열람 권한, 외부 전송, 버전 전환, 검색 결과 형식 |
| [`chunk_baseline.json`](chunk_baseline.json) | M2-1-2 | 정리본 md 57종의 문서별 청크·항목·단위 수 (적재 검증 기준표) |

## 사용법

```python
from app.rag.parser import parse
from app.rag.chunker import chunk_document, document_record, validate

doc = parse(path)
guide = document_record(doc, path, row)   # 가이드·가이드 버전 표 한 행. row = manifest.json 한 행 (등록 입력)
chunks = chunk_document(doc)              # 청크 표 행들
problems = validate(chunks)               # 적재 전 검증. [] 이어야 적재한다
```

## 확인 명령 (저장소 루트에서)

```bash
cd backend && python -m app.rag.chunker ../dataset/guides_final/SW/guide/*.md --out ../참고/chunks   # 문서마다 <이름>.chunks.md 미리보기
cd backend && python -m app.rag.chunker <md 57종> --baseline app/rag/chunk_baseline.json               # 규칙을 바꾼 뒤 기준표 다시 만들기
pytest tests/test_chunker.py
```

청크 규칙을 바꾸면 `chunker.py`의 `CHUNKER_VERSION`을 올리고 기준표를 다시 만든다. 파서 결과가 바뀌는 수정은 `parser.PARSER_VERSION`을 올린다.
