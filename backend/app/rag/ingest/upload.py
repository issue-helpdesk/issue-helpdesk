"""업로드 적재 (WBS M2-3-1). 관리자가 올린 버전 하나를 파싱 → 청크 → 임베딩 → 적재한다. 사용법은 README.md '업로드 적재'.

업로드 API(DC-07)가 파일을 저장하고 버전 행(PENDING)을 만든 뒤 백그라운드로 부른다:

    from app.rag.ingest import connect
    from app.rag.ingest.upload import ingest_version
    with connect(url, allow_remote=True) as conn:
        ingest_version(conn, version_id, embedder)        # → DONE, 또는 FAILED + ingest_error

연결은 이 작업 전용으로 연다 (이 함수가 commit·rollback 한다). file_path 는 업로드 API 가 만든 값만 넣는다.

현행 전환은 하지 않는다 (DC-07). 관리자가 DC-09 로 activate() 를 부르면 그때부터 검색에 나온다.
정리본 적재 run() 과 달리 기준은 DB 다: 열람 범위·전송 정책은 버전 행(관리자 입력), 제목·분류는 문서 행(DC-02·04).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from app.rag.chunker import Chunk, chunk_document, chunk_row, document_row, validate, version_row, view_scope
from app.rag.parser import ParseError, parse

from . import (ERROR_MAX, ROOT, SCOPE_RANK, IngestError, Prepared, Report, _drop_stale, _insert_chunks,
               _lock_document, _put_embeddings, activate, check_vectors, read_vectors)

log = logging.getLogger('app.rag.ingest')
STALE_PENDING = timedelta(minutes=10)                     # 이보다 오래 PENDING 이면 적재가 멈춘 것으로 본다


def ingest_version(conn, version_id: int, embedder, files_root: Path = ROOT, activate_version: bool = False,
                   actor_id: int | None = None, reload: bool = False) -> dict:
    """버전 하나를 적재한다. 결과 {'version_id', 'status': DONE·FAILED·SKIPPED, 'chunks', 'error', 'warnings', 'activated'}.

    1. PENDING·FAILED 이고 현행이 아닌 버전만 처리한다 (DONE·현행은 SKIPPED).
       reload=True 면 DONE·현행도 다시 적재한다 (문의 유형을 등록한 뒤 빠졌던 코드를 넣을 때). 실패하면 그대로 둔다.
       현행은 본문이 같을 때만 (이름표만 고쳐 쓰고 바뀐 칸을 경고). 본문이 다르면 거부: 새 버전으로 올린다.
    2. 파일 → parse → chunk_document → validate. 파일의 문서 번호·버전이 등록값과 다르면 실패, 없으면 등록값을 쓴다.
    3. 표(inquiry_types)에 없는 문의 유형 코드는 청크에서 빼고 경고한다 (검색은 되게, 판단 흐름에 없는 코드가 가지 않게).
    4. 임베딩 (DB 트랜잭션 밖) → 한 트랜잭션에서 잠금(문서 → 버전) 뒤 상태를 다시 보고 청크·임베딩 교체 → DONE.
    5. 실패: 롤백 → FAILED + ingest_error (관리자 화면 DC-08 에 그대로 보여 줄 문구). 다른 버전·현행은 그대로.
       그새 다른 작업이 DONE 으로 끝냈으면 FAILED 를 남기지 않고 SKIPPED (reload 는 FAILED, DB 는 DONE 그대로).

    activate() 와 달리 이 함수가 commit 한다 (백그라운드 작업 하나 = 이 호출 하나). 연결은 전용으로:
    부르기 전에 한 쓰기도 같이 확정된다. 없는 버전 id 는 ValueError.
    """
    out = {'version_id': version_id, 'status': '', 'chunks': 0, 'error': None, 'warnings': [], 'activated': False}
    v = _read_version(conn, version_id)
    codes = {c for (c,) in conn.execute('select code from inquiry_types')}
    conn.commit()
    if not reload and (v['is_current'] or v['status'] == 'DONE'):
        out['status'] = 'SKIPPED'
        return out
    try:
        p = prepare_version(v, files_root, codes, out['warnings'])
        p.vectors[embedder.model_id] = [list(x) for x in embedder.embed_documents(p.texts)]
        report = Report()
        check_vectors([p], [embedder.model_id], report)
        if report.problems:
            raise IngestError(report.problems)
        out['status'], out['activated'] = _write(conn, v, p, embedder.model_id, reload, activate_version, actor_id,
                                                 out['warnings'])
        out['chunks'] = len(p.chunks)
    except Exception as ex:                                # 어떤 실패든 FAILED 로 남겨 관리자가 알 수 있게
        conn.rollback()
        error = _message(ex)
        now = _record_failure(conn, version_id, error)
        if now == 'FAILED' or reload:                      # reload 실패: DB 는 DONE·청크 그대로, 결과만 FAILED
            out['status'], out['error'] = 'FAILED', error
            log.warning('업로드 적재 실패 version_id=%s: %s', version_id, error, exc_info=not _expected(ex))
        else:                                              # 실패를 남길 대상이 없다. 이 작업의 오류는 진단용으로만
            out['status'] = 'SKIPPED'
            log.info('업로드 적재 건너뜀 version_id=%s: %s (이 작업의 오류: %s)', version_id,
                     '다른 작업이 먼저 끝냄' if now == 'DONE' else '버전이 지워짐', error)
        return out
    for w in out['warnings']:
        log.warning('업로드 적재 경고 %s %s: %s', v['doc_code'], v['version'], w)
    log.info('업로드 적재 %s %s: %s, 청크 %d', v['doc_code'], v['version'], out['status'], out['chunks'])
    return out


def resume_pending(conn, embedder, older_than: timedelta = STALE_PENDING, files_root: Path = ROOT) -> list[dict]:
    """적재 도중 서버가 꺼져 PENDING 으로 남은 버전을 다시 적재한다 (서버 시작 때·명령으로).

    방금 올라와 적재 중인 버전은 건드리지 않게 older_than 보다 오래된 것만. 겹쳐도 ingest_version 이 잠근 뒤
    상태를 다시 봐서 한 번만 적재된다. FAILED 는 파일을 고쳐야 하므로 여기서 다시 하지 않는다.
    """
    ids = [i for (i,) in conn.execute("select id from document_versions where ingest_status = 'PENDING' "
                                      'and not is_current and registered_at < now() - %s order by id', (older_than,))]
    conn.commit()
    return [ingest_version(conn, i, embedder, files_root) for i in ids]


def prepare_version(v: dict, files_root: Path, codes: set[str], warnings: list[str]) -> Prepared:
    """파일 → 적재 준비물 (DB 밖). 문제가 있으면 IngestError, 파일을 못 읽으면 ParseError."""
    doc = parse(str(resolve_file(v['file_path'], files_root)))
    meta = doc.meta
    problems = []
    if meta.get('doc_no') and meta['doc_no'] != v['doc_code']:
        problems.append(f"파일의 문서 번호({meta['doc_no']})가 등록한 문서({v['doc_code']})와 다릅니다")
    if meta.get('version') and meta['version'] != v['version']:
        problems.append(f"파일의 버전({meta['version']})이 등록한 버전({v['version']})과 다릅니다")
    if problems:
        raise IngestError(problems)
    file_doc = document_row(doc)                           # 파일 값 (대조용, 문서 행은 바꾸지 않는다)
    meta['doc_no'], meta['version'] = v['doc_code'], v['version']   # 없으면 등록값. 청크 키가 파일 이름에 기대지 않게
    chunks = chunk_document(doc)
    problems = validate(chunks)
    if problems:
        raise IngestError(problems)

    for code, sections in unknown_inquiry_types(chunks, codes).items():
        warnings.append(f"표에 없는 문의 유형 코드 {code} (항목 {', '.join(sections)}): 코드는 빼고 적재했습니다. "
                        f"문의 유형을 등록한 뒤 다시 적재(reload, --version-id {v['id']} --reload)하면 코드가 들어갑니다")
    for c in chunks:
        c.inquiry_type_codes = [x for x in c.inquiry_type_codes if x in codes]
    if meta.get('access_level'):
        file_scope = view_scope(meta['access_level'])
        if SCOPE_RANK[file_scope] > SCOPE_RANK[v['view_scope']]:
            warnings.append(f"파일의 열람 등급({meta['access_level']} → {file_scope})이 등록한 열람 범위"
                            f"({v['view_scope']})보다 좁습니다. 등록값으로 적재했습니다")
    if meta.get('title') and file_doc['title'] != v['title']:
        warnings.append(f"파일의 제목({file_doc['title']})이 문서 제목({v['title']})과 다릅니다. 문서 제목은 그대로 둡니다")
    if meta.get('category') and file_doc['category_code'] != v['category_code']:
        warnings.append(f"파일의 분류({file_doc['category_code']})가 문서 분류({v['category_code']})와 다릅니다. "
                        '문서 분류는 그대로 둡니다')
    warnings += [f'파서 경고: {w}' for w in doc.warnings]

    return Prepared(entry={}, chunks=chunks, document={'doc_code': v['doc_code']},
                    version={'version': v['version'], 'file_format': version_row(doc, v['file_path'])['file_format']},
                    rows=[chunk_row(c) for c in chunks], parse_warnings=list(doc.warnings))


def unknown_inquiry_types(chunks: list[Chunk], codes: set[str]) -> dict[str, list[str]]:
    """표에 없는 문의 유형 코드 → 그 코드가 나온 항목 번호들.

    새 문의 유형 등록(M2-3-2, 팀 협의 중)을 붙일 자리. 지금은 경고만 하고 코드를 뺀다.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        where = c.section_no or c.chunk_type
        for x in c.inquiry_type_codes:
            if x not in codes and where not in out[x]:
                out[x].append(where)
    return dict(out)


def resolve_file(file_path: str | None, files_root: Path = ROOT) -> Path:
    """버전 행의 file_path → 실제 파일. 상대 경로는 files_root 기준이고 그 밖으로 나가면 거부한다.

    절대 경로는 검사하지 않는다: file_path 는 업로드 API 가 만든 값만 믿는다 (사용자 입력을 그대로 넣지 않는다).
    저장 위치가 정해지면 절대 경로도 그 안인지 볼 것.
    """
    if not file_path:
        raise IngestError(['버전에 파일 위치(file_path)가 없습니다'])
    path = Path(file_path)
    if path.is_absolute():
        return path
    root = Path(files_root).resolve()
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise IngestError(['파일 위치가 저장 폴더 밖입니다'])
    return full


def _read_version(conn, version_id: int) -> dict:
    row = conn.execute(
        'select v.id, v.document_id, v.version, v.file_path, v.ingest_status, v.is_current, v.view_scope, '
        'd.doc_code, d.title, d.category_code from document_versions v '
        'join knowledge_documents d on d.id = v.document_id where v.id = %s', (version_id,)).fetchone()
    if row is None:
        raise ValueError(f'없는 버전 id {version_id}')
    keys = ('id', 'document_id', 'version', 'file_path', 'status', 'is_current', 'view_scope',
            'doc_code', 'title', 'category_code')
    return dict(zip(keys, row))


def _write(conn, v: dict, p: Prepared, model_id: str, reload: bool, activate_version: bool, actor_id: int | None,
           warnings: list[str]) -> tuple[str, bool]:
    """한 트랜잭션: 문서 → 버전 잠금, 상태 다시 확인, 청크·임베딩 교체, DONE (필요하면 현행 전환).

    reload 로 DONE 버전을 다시 넣을 때: 뼈대·본문이 같으면 같은 청크 id 에 이름표(meta·heading_path·location)만
    고쳐 쓰고 바뀐 칸을 경고한다. 다르면 현행은 거부(새 버전으로), 현행이 아니면 통째로 교체하고 다른 모델의 벡터는
    글이 같은 것만 옮긴다. 현행의 청크 id 를 바꾸지 않는 이유: 검색은 점수(id)와 본문을 따로 읽어서, 그 사이에
    id 가 바뀌면 이전 점수와 새 본문이 섞이거나 결과가 깨진다 (재검수 P2).
    """
    _lock_document(conn, v['document_id'])
    status, current = conn.execute('select ingest_status, is_current from document_versions where id = %s for update',
                                   (v['id'],)).fetchone()
    if not reload and (current or status == 'DONE'):       # 그새 다른 작업이 끝냈다
        conn.rollback()
        return 'SKIPPED', False
    ids = _relabel(conn, v['id'], p, warnings) if status == 'DONE' else None
    if ids is not None:
        _put_embeddings(conn, ids, p, {}, update=True)
        dropped = _drop_stale(conn, v['id'], ids, p)
    elif current:
        raise IngestError(['현행 버전의 내용(청크 구성이나 본문)이 파일과 다릅니다. 새 버전으로 올린 뒤 현행 전환하세요'])
    else:
        before = [m for (m,) in conn.execute(
            'select distinct e.model from document_chunk_embeddings e join document_chunks c on c.id = e.chunk_id '
            'where c.version_id = %s and e.model <> %s', (v['id'], model_id))]
        cache = read_vectors(conn, set(p.texts)) if before else {}
        ids = _insert_chunks(conn, v['id'], p.rows)
        dropped = _put_embeddings(conn, ids, p, {m: [cache.get((m, t)) for t in p.texts] for m in before})
    warnings += [f'{m} 임베딩 {n}개 빠짐 (글이 바뀐 청크). 그 모델로 다시 적재하세요' for m, n in dropped.items()]
    conn.execute("update document_versions set ingest_status = 'DONE', ingest_error = null, file_format = %s "
                 'where id = %s', (p.version['file_format'], v['id']))
    activated = activate(conn, v['id'], actor_id) if activate_version else False
    conn.commit()
    return 'DONE', activated


SHOW_CHANGED = 10                                         # 바뀐 칸 경고는 청크 이만큼까지, 나머지는 개수만


def _relabel(conn, vid: int, p: Prepared, warnings: list[str]) -> list[int] | None:
    """뼈대(seq·unit_key·part·chunk_type)와 본문이 DB 와 같으면 이름표(heading_path·location·meta)만 같은 id 에
    고쳐 쓰고 청크 id 들을 돌려준다. 조각 식별·본문은 그대로라 겹친 검색이 섞이지 않는다 (순위·이름표는 이전 것을
    볼 수 있다). 바뀐 칸은 경고 ('item:3.4: inquiry_type_codes [] → ["HW-10"]'). 다르면 아무것도 안 하고 None."""
    old = conn.execute('select id, seq, unit_key, part, chunk_type, content, heading_path, location, meta '
                       'from document_chunks where version_id = %s order by seq', (vid,)).fetchall()
    if [tuple(r[1:6]) for r in old] != [tuple(x[k] for k in ('seq', 'unit_key', 'part', 'chunk_type', 'content'))
                                         for x in p.rows]:
        return None
    from psycopg.types.json import Jsonb
    changed = []
    for (cid, *_, heading, location, meta), x in zip(old, p.rows):
        diff = _diff({'heading_path': heading, 'location': location, **(meta or {})},
                     {'heading_path': x['heading_path'], 'location': x['location'], **x['meta']})
        if diff:
            conn.execute('update document_chunks set heading_path = %s, location = %s, meta = %s where id = %s',
                         (x['heading_path'], x['location'], Jsonb(x['meta']), cid))
            changed.append(f"{x['unit_key'].split('/', 1)[-1]}: {', '.join(diff)}")
    warnings += [f'이름표 바뀜 {c}' for c in changed[:SHOW_CHANGED]]
    if len(changed) > SHOW_CHANGED:
        warnings.append(f'이름표 바뀜 외 청크 {len(changed) - SHOW_CHANGED}개')
    return [r[0] for r in old]


def _diff(old: dict, new: dict) -> list[str]:
    def show(v):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= 60 else s[:57] + '…'
    return [f'{k} {show(old.get(k))} → {show(new.get(k))}' for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k)]


def _record_failure(conn, version_id: int, error: str) -> str | None:
    """FAILED + 사유를 남긴다. DONE·현행은 덮지 않는다 (현행은 DONE 이어야 한다).
    돌려주는 값: 남겼으면 'FAILED', 못 남겼으면 지금 상태 (그새 다른 작업이 끝냄 → 'DONE', 버전이 지워짐 → None)."""
    n = conn.execute("update document_versions set ingest_status = 'FAILED', ingest_error = %s "
                     "where id = %s and not is_current and ingest_status <> 'DONE'",
                     (error[:ERROR_MAX], version_id)).rowcount
    row = None if n else conn.execute('select ingest_status from document_versions where id = %s',
                                      (version_id,)).fetchone()
    conn.commit()
    return 'FAILED' if n else row[0] if row else None


def _message(ex: Exception) -> str:
    """ingest_error 에 남길 문구. 관리자 화면(DC-08)에 보이므로 내부 경로는 넣지 않는다."""
    if isinstance(ex, ParseError):
        return ex.message
    if isinstance(ex, IngestError):
        return '; '.join(ex.problems)
    return f'적재 중 오류가 났습니다 ({type(ex).__name__})'


def _expected(ex: Exception) -> bool:
    return isinstance(ex, (ParseError, IngestError))
