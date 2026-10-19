# RAG 문서 처리

가이드 문서를 읽어(파싱) 검색 단위(청크)로 나누고, 청크와 문서에 붙일 정보를 만든다.

| 파일 | WBS | 내용 |
|---|---|---|
| [`parser/`](parser/README.md) | M2-1-1 | 가이드 문서(PPTX·PDF·DOCX·MD·TXT) → 같은 모양의 결과 `ParsedDocument` |
| [`chunker/`](chunker/__init__.py) | M2-1-2 · M2-1-3 | `ParsedDocument` → 검색 단위 `Chunk`, 표에 넣을 행 `document_row()`·`version_row()`·`chunk_row()` |
| [`chunker/청크_규칙.md`](chunker/청크_규칙.md) | **M2-1-2 산출물** | 청크를 나누는 규칙, `unit_key`, 샘플, 결과 수치 |
| [`청크_메타데이터.md`](청크_메타데이터.md) | **M2-1-3 산출물** | 테이블 설계서(A)의 Knowledge 표에 넣는 값, 열람 범위, 외부 전송, A에게 요청하는 수정, 버전 전환, 검색 결과 형식 |
| [`chunker/baseline.json`](chunker/baseline.json) | M2-1-2 | 정리본 md 57종의 문서별 청크·항목·단위 수 (적재 검증 기준표) |

## 사용법

```python
from app.rag.parser import parse
from app.rag.chunker import chunk_document, chunk_row, document_row, validate, version_row

doc = parse(path)
chunks = chunk_document(doc)
problems = validate(chunks)               # 적재 전 검증. [] 이어야 적재한다
document_row(doc)                         # knowledge_documents 한 행
version_row(doc, path, row)               # document_versions 한 행. row = manifest.json 한 행 (등록 입력)
[chunk_row(c) for c in chunks]            # document_chunks 행들. 임베딩 입력은 c.text
```

## 확인 명령 (저장소 루트에서)

```bash
cd backend && python -m app.rag.chunker ../dataset/guides_final/SW/guide/*.md --out ../참고/chunks   # 문서마다 <이름>.chunks.md 미리보기
cd backend && python -m app.rag.chunker <md 57종> --baseline app/rag/chunker/baseline.json            # 규칙을 바꾼 뒤 기준표 다시 만들기
pytest tests/test_chunker.py
```

청크 규칙을 바꾸면 `chunker/__init__.py`의 `CHUNKER_VERSION`을 올리고 기준표를 다시 만든다. 파서 결과가 바뀌는 수정은 `parser.PARSER_VERSION`을 올린다.
