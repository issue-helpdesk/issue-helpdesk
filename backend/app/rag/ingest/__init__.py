"""가이드 적재 (WBS M2-2-1). 규칙은 청크_메타데이터.md 7장, 사용법은 README.md.

준비(파싱·청크·임베딩, DB 밖) → 검증(하나라도 실패하면 DB에 손대지 않는다) → 문서마다 짧은 트랜잭션으로 교체.

    from app.rag.ingest import FakeEmbedder, run
    run('postgresql://…', [FakeEmbedder('kure-v1')])          # 임시 DB에 전체 적재

현행 전환은 activate() 하나로 한다. 관리자 API(A, 버전 PATCH isCurrent:true)도 이 함수를 부른다.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.models.embedding import EMBED_DIM
from app.rag.chunker import Chunk, baseline, chunk_document, chunk_row, document_row, validate, version_row
from app.rag.parser import parse

ROOT = Path(__file__).resolve().parents[4]                 # 저장소 루트
GUIDES = ROOT / 'dataset' / 'guides'
BASELINE = Path(__file__).resolve().parents[1] / 'chunker' / 'baseline.json'
VERSION_COLUMNS = ('version', 'file_path', 'file_format', 'view_scope', 'transfer_policy')   # version_row 중 표에 있는 칸
CHUNK_COLUMNS = ('seq', 'unit_key', 'part', 'chunk_type', 'heading_path', 'location', 'content', 'meta')
ERROR_MAX = 1000                                           # ingest_error 에 남기는 글자 수
NORM_TOLERANCE = 1e-3                                      # 임베딩은 길이 1 (두 모델 모두 정규화)
LOCAL_HOSTS = ('', 'localhost', '127.0.0.1', '::1')       # 이 컴퓨터. 아니면 --allow-remote 가 있어야 쓴다
SCOPE_RANK = {'ALL': 0, 'AGENT': 1, 'ADMIN': 2}            # 클수록 좁다
POLICY_RANK = {'ALLOWED': 0, 'MASKED': 1, 'BLOCKED': 2}


class IngestError(Exception):
    """검증 실패. DB에는 아무것도 쓰지 않았다."""

    def __init__(self, problems: list[str]):
        super().__init__(f'검증 실패 {len(problems)}건')
        self.problems = problems


class FakeEmbedder:
    """개발·시험용 가짜 임베딩기. Embedder 와 같은 모양(model_id·embed_documents)으로 모델 파일 없이 돈다.

    글자에서 결정적으로 만든 1024차원 단위 벡터라 같은 글이면 늘 같은 벡터다. 검색 품질과는 상관없다.
    model_id 가 진짜 모델과 달라(fake-…) 진짜 벡터와 섞이지 않는다.
    """

    def __init__(self, key: str = 'kure-v1'):
        self.key = key
        self.model_id = f'fake-{key}@0000000/v1'
        self.dim = EMBED_DIM
        self.calls = 0                                     # embed_documents 에 넘긴 글 수 (재사용 확인용)

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        self.calls += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        rnd = random.Random(hashlib.sha256(f'{self.key}\n{text}'.encode('utf-8')).digest())
        v = [rnd.gauss(0, 1) for _ in range(self.dim)]
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]


@dataclass
class Prepared:
    """문서 하나의 적재 준비물 (DB 밖에서 만든다)."""
    entry: dict                                            # manifest.json 한 행
    chunks: list[Chunk]
    document: dict                                         # knowledge_documents 행 (owner_group 은 이름)
    version: dict                                          # document_versions 행 (VERSION_COLUMNS)
    rows: list[dict]                                       # document_chunks 행들 (chunk_row)
    parse_warnings: list[str]
    vectors: dict[str, list[list[float]]] = field(default_factory=dict)   # model_id → 청크 순서대로
    apply_policy: bool = False                             # 이미 있는 버전의 정책을 manifest 값으로 바꿀지 (check_policies)

    @property
    def doc_code(self) -> str:
        return self.document['doc_code']

    @property
    def texts(self) -> list[str]:                          # 임베딩 입력 = source_text
        return [c.text for c in self.chunks]


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)      # 하나라도 있으면 DB에 쓰지 않는다
    warnings: list[str] = field(default_factory=list)
    embedded: dict[str, Counter] = field(default_factory=dict)   # model_id → {'reused': n, 'new': n}
    results: list[dict] = field(default_factory=list)      # 문서별 적재 결과


# ── 준비 ──────────────────────────────────────────────────────

def load_manifest(guides: Path = GUIDES, docs: list[str] | None = None) -> list[dict]:
    """manifest.json 에서 검색 대상(rag_target=true) 문서. docs 를 주면 그 문서만."""
    with open(Path(guides) / 'manifest.json', encoding='utf-8') as f:
        rows = [r for r in json.load(f) if r.get('rag_target') is True]
    if docs:
        unknown = set(docs) - {r['doc_no'] for r in rows}
        if unknown:
            raise IngestError([f'manifest 에 없거나 검색 대상이 아닌 문서: {", ".join(sorted(unknown))}'])
        rows = [r for r in rows if r['doc_no'] in docs]
    return rows


def prepare(entries: list[dict], guides: Path = GUIDES) -> list[Prepared]:
    """md 를 파싱해 청크·행을 만든다. 정리본은 문서마다 md 하나만 등록한다."""
    out = []
    for e in entries:
        path = (Path(guides) / e['files']['md']).resolve()
        doc = parse(str(path))
        chunks = chunk_document(doc)
        try:
            shown = path.relative_to(ROOT).as_posix()      # 원문 위치는 저장소 기준 상대 경로
        except ValueError:
            shown = path.as_posix()
        v = version_row(doc, shown, e)
        out.append(Prepared(entry=e, chunks=chunks, document=document_row(doc),
                            version={k: v[k] for k in VERSION_COLUMNS}, rows=[chunk_row(c) for c in chunks],
                            parse_warnings=list(doc.warnings)))
    return out


def load_baseline(path: Path = BASELINE) -> dict[str, dict]:
    with open(path, encoding='utf-8') as f:
        return json.load(f)['docs']


def check_files(prepared: list[Prepared], base: dict[str, dict] | None, report: Report) -> None:
    """DB 없이 하는 검사: 파서 경고, validate(), 기준표, manifest 값."""
    for code, n in Counter(p.doc_code for p in prepared).items():
        if n > 1:
            report.problems.append(f'{code}: 같은 문서가 {n}번 들어 있음')
    for p in prepared:
        if p.doc_code != p.entry['doc_no']:
            report.problems.append(f'{p.entry["doc_no"]}: 문서 머리말 번호가 다름 ({p.doc_code})')
        if p.version['version'] != p.entry.get('version'):
            report.problems.append(f'{p.doc_code}: 버전이 manifest({p.entry.get("version")})와 문서({p.version["version"]})에서 다름')
        report.problems += [f'{p.doc_code}: 파서 경고 {w}' for w in p.parse_warnings]
        report.problems += [f'{p.doc_code}: {x}' for x in validate(p.chunks)]
        if not p.chunks:
            report.problems.append(f'{p.doc_code}: 청크 0개')
        if base is not None:
            got, want = baseline(p.chunks).get(p.doc_code), base.get(p.doc_code)
            if want is None:
                report.warnings.append(f'{p.doc_code}: 기준표에 없는 문서 (청크 {len(p.chunks)}개, 담당자 확인)')
            elif got != want:
                report.problems.append(f'{p.doc_code}: 기준표와 다름 {got} ≠ {want}')
        tp = p.entry.get('transfer_policy')
        if tp != p.version['transfer_policy']:
            report.warnings.append(f'{p.doc_code}: manifest 의 transfer_policy {tp!r} → BLOCKED 로 적재')


def check_reference(prepared: list[Prepared], codes: set[str], groups: dict[str, int], report: Report) -> None:
    """DB 기준 데이터와 맞는지: 문의 유형 코드, 관리 부서 이름."""
    for p in prepared:
        bad = sorted({x for c in p.chunks for x in c.inquiry_type_codes} - codes)
        if bad:
            report.problems.append(f'{p.doc_code}: inquiry_types 에 없는 문의 유형 코드 {", ".join(bad)}')
        owner = p.document['owner_group']
        if owner and owner not in groups:
            report.problems.append(f'{p.doc_code}: support_groups 에 없는 관리 부서 {owner!r}')


def embed(prepared: list[Prepared], embedders: list, cache: dict[tuple[str, str], list[float]], report: Report) -> None:
    """모델마다 청크 벡터를 채운다. 같은 model + 같은 source_text 인 기존 벡터(cache)는 다시 쓴다."""
    for emb in embedders:
        mid = emb.model_id
        todo = sorted({t for p in prepared for t in p.texts if (mid, t) not in cache})
        stat = report.embedded.setdefault(mid, Counter())
        stat['reused'] += sum(1 for p in prepared for t in p.texts if (mid, t) in cache)
        stat['new'] += len(todo)
        if todo:
            for t, v in zip(todo, emb.embed_documents(todo)):
                cache[(mid, t)] = list(v)
        for p in prepared:
            p.vectors[mid] = [cache[(mid, t)] for t in p.texts if (mid, t) in cache]


def check_vectors(prepared: list[Prepared], model_ids: list[str], report: Report) -> None:
    """모든 청크에 지정한 모델 전부의 임베딩이 있다 (1024차원, 유한한 값, 길이 1)."""
    if not model_ids:
        report.problems.append('임베딩 모델이 없음 (모델을 하나 이상 지정)')
    for mid, n in Counter(model_ids).items():
        if n > 1:
            report.problems.append(f'같은 모델이 {n}번 지정됨: {mid}')
    for p in prepared:
        for mid in dict.fromkeys(model_ids):
            vecs = p.vectors.get(mid, [])
            if len(vecs) != len(p.chunks):
                report.problems.append(f'{p.doc_code}: {mid} 임베딩 {len(vecs)}개, 청크 {len(p.chunks)}개')
            elif any(len(v) != EMBED_DIM or not all(math.isfinite(x) for x in v)
                     or abs(math.sqrt(sum(x * x for x in v)) - 1) > NORM_TOLERANCE for v in vecs):
                report.problems.append(f'{p.doc_code}: {mid} 임베딩 차원·값이 이상함 ({EMBED_DIM}차원 단위 벡터 기대)')


def check_policies(conn, prepared: list[Prepared], apply: bool, report: Report) -> None:
    """이미 있는 버전의 열람 범위·외부 전송 정책과 manifest 비교.

    관리자가 바꿨을 수 있어 기본은 DB 값을 둔다. 다만 manifest 가 더 좁으면(예: ALLOWED → BLOCKED) 검증 실패로 멈춘다
    — 그대로 두면 보내면 안 되는 본문이 외부 모델로 나간다. apply=True(--apply-policy)면 manifest 값으로 바꾼다.
    """
    for p in prepared:
        row = conn.execute('select v.view_scope, v.transfer_policy from document_versions v join knowledge_documents d '
                           'on d.id = v.document_id where d.doc_code = %s and v.version = %s',
                           (p.doc_code, p.version['version'])).fetchone()
        want = (p.version['view_scope'], p.version['transfer_policy'])
        if row is None or tuple(row) == want:
            continue
        shown = f'DB {row[0]}/{row[1]}, manifest {want[0]}/{want[1]}'
        if apply:
            p.apply_policy = True
            report.warnings.append(f'{p.doc_code}: 정책을 manifest 값으로 바꿈 ({shown})')
        elif _narrower(want, tuple(row)):
            report.problems.append(f'{p.doc_code}: manifest 정책이 더 좁음 ({shown}). 확인 후 --apply-policy')
        else:
            report.warnings.append(f'{p.doc_code}: DB 정책 유지 ({shown})')


def _narrower(want: tuple[str, str], have: tuple[str, str]) -> bool:
    """(view_scope, transfer_policy) want 가 have 보다 한 칸이라도 좁은가. 한 칸이 넓어진 것으로 상쇄하지 않는다."""
    return SCOPE_RANK[want[0]] > SCOPE_RANK[have[0]] or POLICY_RANK[want[1]] > POLICY_RANK[have[1]]


# ── DB ────────────────────────────────────────────────────────

def is_local(url: str) -> bool:
    """libpq 가 실제로 접속할 곳이 이 컴퓨터인가. 주소 뒤 ?host=·hostaddr·여러 호스트·PGHOST·service 까지 본다."""
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(url)
    if info.get('service') or os.environ.get('PGSERVICE'):
        return False
    hosts = [h.strip() for k in ('host', 'hostaddr')
             for h in str(info.get(k) or os.environ.get(f'PG{k.upper()}', '')).split(',')]
    return all(h in LOCAL_HOSTS or h.startswith('/') for h in hosts)


def connect(url: str, allow_remote: bool = False):
    """DB 연결. 이 컴퓨터 밖(공유 DB)은 allow_remote=True 일 때만."""
    import psycopg
    from pgvector.psycopg import register_vector

    if not allow_remote and not is_local(url):
        raise ValueError('localhost 가 아닌 DB 입니다. 공유 DB 에 쓰려면 allow_remote(--allow-remote)를 주세요.')
    conn = psycopg.connect(url)
    register_vector(conn)
    return conn


def read_reference(conn) -> tuple[set[str], dict[str, int]]:
    codes = {c for (c,) in conn.execute('select code from inquiry_types')}
    groups = {name: id_ for id_, name in conn.execute('select id, name from support_groups')}
    return codes, groups


def read_vectors(conn, texts: set[str]) -> dict[tuple[str, str], list[float]]:
    """다시 쓸 벡터를 청크를 지우기 전에 미리 읽어 둔다 (청크를 지우면 임베딩도 CASCADE 로 지워진다). 모든 모델."""
    rows = conn.execute('select model, source_text, embedding from document_chunk_embeddings '
                        'where source_text = any(%s)', (list(texts),))
    return {(m, t): [float(x) for x in e.to_list()] for m, t, e in rows}


def activate(conn, version_id: int, actor_id: int | None = None) -> bool:
    """현행 전환 (docs/api/04 버전 PATCH isCurrent:true). 부른 쪽의 트랜잭션 안에서 돌고 commit 하지 않는다.

    기존 현행 버전 → false, 이 버전 → true (DB 제약: 현행은 문서마다 하나, DONE 만).
    처음 현행이 되는 버전이면 activated_at = now() (이후 전환에서도 보존. 마이그레이션 478ccde3a990).
    감사 로그 DOCUMENT_VERSION_ACTIVATE. 이미 현행이면 아무것도 하지 않고 False.
    잠금 순서는 문서 → 버전 (write_document 와 같다. 순서가 다르면 교착된다).
    """
    row = conn.execute('select document_id from document_versions where id = %s', (version_id,)).fetchone()
    if row is None:
        raise ValueError(f'없는 버전 id {version_id}')
    doc_id = row[0]
    _lock_document(conn, doc_id)
    version, status, current = conn.execute('select version, ingest_status, is_current from document_versions '
                                            'where id = %s', (version_id,)).fetchone()     # 잠근 뒤에 읽는다
    if current:
        return False
    if status != 'DONE':
        raise ValueError(f'적재가 끝난(DONE) 버전만 현행으로 바꿀 수 있다: {version} {status}')
    old = conn.execute('select id, version from document_versions where document_id = %s and is_current',
                       (doc_id,)).fetchone()
    if old:
        conn.execute('update document_versions set is_current = false where id = %s', (old[0],))
    conn.execute('update document_versions set is_current = true, activated_at = coalesce(activated_at, now()) '
                 'where id = %s', (version_id,))
    _audit(conn, 'DOCUMENT_VERSION_ACTIVATE', doc_id, actor_id, f'{old[1] if old else "없음"} → {version}')
    return True


def _lock_document(conn, doc_id: int) -> None:
    conn.execute('select id from knowledge_documents where id = %s for update', (doc_id,))   # 같은 문서 동시 변경 막기


def _audit(conn, event: str, doc_id: int, actor_id: int | None, result: str) -> None:
    conn.execute("insert into audit_logs (event_type, target_type, target_id, actor_id, result) "
                 "values (%s, 'document', %s, %s, %s)", (event, doc_id, actor_id, result))


def write_document(conn, p: Prepared, groups: dict[str, int], cache: dict, activate_version: bool = True,
                   force_activate: bool = False) -> dict:
    """문서 하나를 교체한다 (7장). 결과 {'doc', 'action': new·reloaded·unchanged·failed, 'activated', 'error', …}.

    1. 버전 행 확보: 새 버전이면 PENDING·비현행으로 넣고 커밋한다 (실패해도 FAILED 를 남길 곳). 문서 행은 없을 때만 만든다.
    2. 교체 (한 트랜잭션, 문서 → 버전 → 청크 순으로 잠금):
       - 문서 칸(제목·분류·관리 부서) 갱신 — 실패하면 같이 롤백된다
       - 같은 버전 다시 적재: 그 버전 청크를 통째로 지우고 새로 넣는다 (순번 upsert 금지).
         DB의 청크 행이 지금 결과와 똑같으면 지우지 않는다 (청크 id 유지): 지정한 모델 벡터는 맞추고,
         지정하지 않은 모델 중 임베딩 입력(source_text)이 바뀐 벡터는 지우고 알린다 (예전 입력의 벡터를 남기지 않는다).
       - 정책 다시 확인: 검증(check_policies) 뒤 임베딩하는 사이에 DB 정책이 manifest 보다 넓어졌으면 이 문서는 멈춘다.
       - DONE → 현행 전환: 이번 실행에서 처음 등록한 버전이거나 문서에 현행이 없을 때만 (force_activate 면 늘).
         이미 있던 버전(DONE·FAILED 재시도)은 다른 현행이 있으면 DONE 까지만 한다 (관리자가 고른 현행을 되돌리지 않게).
    3. 실패: 롤백 → 그 버전이 현행이 아니면 FAILED·ingest_error. 이전 현행은 그대로.
    """
    out = {'doc': p.doc_code, 'version': p.version['version'], 'action': '', 'activated': False, 'error': None}
    try:
        doc_id = _document_id(conn, p, groups)
        row = conn.execute('select id from document_versions where document_id = %s and version = %s',
                           (doc_id, p.version['version'])).fetchone()
        if row is None:
            vid = conn.execute(
                "insert into document_versions (document_id, version, file_path, file_format, view_scope, transfer_policy, "
                "is_current, ingest_status) values (%s, %s, %s, %s, %s, %s, false, 'PENDING') returning id",
                (doc_id, *(p.version[k] for k in VERSION_COLUMNS))).fetchone()[0]
            out['action'] = 'new'
        else:
            vid = row[0]
        conn.commit()
    except Exception as ex:                                # 버전 행도 못 만들었으면 남길 곳이 없다
        conn.rollback()
        out['action'], out['error'] = 'failed', f'{type(ex).__name__}: {ex}'
        return out

    try:
        _lock_document(conn, doc_id)
        status = conn.execute('select ingest_status from document_versions where id = %s', (vid,)).fetchone()[0]
        _update_document(conn, doc_id, p, groups)
        if p.apply_policy:
            _apply_policy(conn, doc_id, vid, p)
        elif out['action'] != 'new':                       # 잠근 뒤 지금 정책으로 다시 비교 (검증 뒤 바뀌었을 수 있다)
            have = tuple(conn.execute('select view_scope, transfer_policy from document_versions where id = %s',
                                      (vid,)).fetchone())
            want = (p.version['view_scope'], p.version['transfer_policy'])
            if _narrower(want, have):
                raise IngestError([f'검증 뒤 DB 정책이 바뀜: DB {have[0]}/{have[1]}, manifest {want[0]}/{want[1]}. '
                                   '확인 후 --apply-policy'])
        if status == 'DONE' and _same_chunks(conn, vid, p):
            out['action'] = 'unchanged'
            ids = [i for (i,) in conn.execute('select id from document_chunks where version_id = %s order by seq', (vid,))]
            _put_embeddings(conn, ids, p, {}, update=True)
            out['dropped'] = _drop_stale(conn, vid, ids, p)
        else:
            out['action'] = out['action'] or 'reloaded'
            before = [m for (m,) in conn.execute(
                'select distinct e.model from document_chunk_embeddings e join document_chunks c on c.id = e.chunk_id '
                'where c.version_id = %s', (vid,))]
            conn.execute('delete from document_chunks where version_id = %s', (vid,))      # 임베딩은 CASCADE
            ids = [conn.execute(f'insert into document_chunks (version_id, {", ".join(CHUNK_COLUMNS)}) '
                                f'values (%s, {", ".join(["%s"] * len(CHUNK_COLUMNS))}) returning id',
                                (vid, *_chunk_values(r))).fetchone()[0] for r in p.rows]
            others = {m: [cache.get((m, t)) for t in p.texts] for m in before if m not in p.vectors}
            out['dropped'] = _put_embeddings(conn, ids, p, others)
        conn.execute("update document_versions set ingest_status = 'DONE', ingest_error = null, file_path = %s, "
                     "file_format = %s where id = %s", (p.version['file_path'], p.version['file_format'], vid))
        has_current = conn.execute('select 1 from document_versions where document_id = %s and is_current',
                                   (doc_id,)).fetchone() is not None
        if activate_version and (force_activate or out['action'] == 'new' or not has_current):
            out['activated'] = activate(conn, vid)
        elif activate_version and not conn.execute('select is_current from document_versions where id = %s',
                                                   (vid,)).fetchone()[0]:
            out['note'] = '현행 아님 (다른 버전이 현행). 바꾸려면 관리자 API(activate) 또는 --force-activate'
        conn.commit()
    except Exception as ex:                                # 한 문서 실패가 다른 문서를 막지 않게
        conn.rollback()
        out['action'], out['error'] = 'failed', _error(ex)
        # 현행은 DONE 이어야 해서 FAILED 로 바꿀 수 없다 (롤백으로 그대로). 현행 여부는 지금 값으로 본다
        conn.execute("update document_versions set ingest_status = 'FAILED', ingest_error = %s "
                     "where id = %s and not is_current", (out['error'][:ERROR_MAX], vid))
        conn.commit()
    return out


def _error(ex: Exception) -> str:
    return '; '.join(ex.problems) if isinstance(ex, IngestError) else f'{type(ex).__name__}: {ex}'


def _document_id(conn, p: Prepared, groups: dict[str, int]) -> int:
    """문서 id. 없을 때만 만든다 (이미 있는 문서의 칸은 교체 트랜잭션에서 바꾼다)."""
    d = p.document
    row = conn.execute(
        'insert into knowledge_documents (doc_code, doc_type, title, category_code, owner_group_id) '
        'values (%s, %s, %s, %s, %s) on conflict (doc_code) do nothing returning id',
        (d['doc_code'], d['doc_type'], d['title'], d['category_code'], groups.get(d['owner_group']))).fetchone()
    return row[0] if row else conn.execute('select id from knowledge_documents where doc_code = %s',
                                           (d['doc_code'],)).fetchone()[0]


def _update_document(conn, doc_id: int, p: Prepared, groups: dict[str, int]) -> None:
    d = p.document
    conn.execute('update knowledge_documents set doc_type = %s, title = %s, category_code = %s, owner_group_id = %s '
                 'where id = %s', (d['doc_type'], d['title'], d['category_code'], groups.get(d['owner_group']), doc_id))


def _apply_policy(conn, doc_id: int, vid: int, p: Prepared) -> None:
    """--apply-policy: 이미 있는 버전의 정책을 manifest 값으로. 감사 로그 DOCUMENT_POLICY_CHANGE."""
    old = conn.execute('select view_scope, transfer_policy from document_versions where id = %s', (vid,)).fetchone()
    new = (p.version['view_scope'], p.version['transfer_policy'])
    if tuple(old) != new:
        conn.execute('update document_versions set view_scope = %s, transfer_policy = %s where id = %s', (*new, vid))
        _audit(conn, 'DOCUMENT_POLICY_CHANGE', doc_id, None, f'{p.version["version"]} {old[0]}/{old[1]} → {new[0]}/{new[1]}')


def _chunk_values(r: dict) -> tuple:
    from psycopg.types.json import Jsonb
    return tuple(Jsonb(r[k]) if k == 'meta' else r[k] for k in CHUNK_COLUMNS)


def _same_chunks(conn, vid: int, p: Prepared) -> bool:
    rows = conn.execute(f'select {", ".join(CHUNK_COLUMNS)} from document_chunks where version_id = %s order by seq',
                        (vid,)).fetchall()
    return [tuple(r) for r in rows] == [tuple(x[k] for k in CHUNK_COLUMNS) for x in p.rows]


def _put_embeddings(conn, ids: list[int], p: Prepared, others: dict[str, list], update: bool = False) -> dict[str, int]:
    """지정한 모델의 벡터를 넣는다. update=True 면 이미 있는 행은 source_text 가 다를 때만 바꾼다.
    others: 이번에 지정하지 않았지만 이 버전에 있던 모델 → 다시 쓸 벡터 (글이 바뀐 청크는 None → 빠짐). 빠진 수를 돌려준다."""
    sql = 'insert into document_chunk_embeddings (chunk_id, model, embedding, source_text) values (%s, %s, %s, %s)'
    if update:
        sql += (' on conflict (chunk_id, model) do update set embedding = excluded.embedding, source_text = excluded.source_text, '
                'created_at = now() where document_chunk_embeddings.source_text is distinct from excluded.source_text')
    rows = [(i, mid, _vec(v), t) for mid, vecs in p.vectors.items() for i, v, t in zip(ids, vecs, p.texts)]
    rows += [(i, mid, _vec(v), t) for mid, vecs in others.items() for i, v, t in zip(ids, vecs, p.texts) if v is not None]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return {mid: sum(v is None for v in vecs) for mid, vecs in others.items() if any(v is None for v in vecs)}


def _drop_stale(conn, vid: int, ids: list[int], p: Prepared) -> dict[str, int]:
    """청크는 그대로인데 머리말(문서 제목 등)이 바뀌어 임베딩 입력이 달라진 경우: 지정하지 않은 모델의 예전 벡터를 지운다."""
    texts = dict(zip(ids, p.texts))
    stale = [(cid, m) for cid, m, t in conn.execute(
        'select e.chunk_id, e.model, e.source_text from document_chunk_embeddings e '
        'join document_chunks c on c.id = e.chunk_id where c.version_id = %s', (vid,)) if t != texts[cid]]
    with conn.cursor() as cur:
        cur.executemany('delete from document_chunk_embeddings where chunk_id = %s and model = %s', stale)
    return dict(Counter(m for _, m in stale))


def _vec(v):
    import numpy as np
    return np.asarray(v, dtype=np.float32)


def drop_model(conn, model_id: str) -> int:
    """한 모델의 가이드 청크 임베딩을 지운다 (모델을 하나로 정한 뒤). commit 은 부른 쪽이."""
    return conn.execute('delete from document_chunk_embeddings where model = %s', (model_id,)).rowcount


def summary(conn) -> list[tuple]:
    """현행 버전 기준 분류별 (분류, 문서 수, 청크 수, {모델: 임베딩 수})."""
    docs = conn.execute(
        "select coalesce(d.category_code, '공통'), count(distinct d.id), count(c.id) from knowledge_documents d "
        'join document_versions v on v.document_id = d.id and v.is_current left join document_chunks c on c.version_id = v.id '
        'group by 1 order by 1').fetchall()
    emb = defaultdict(dict)
    for cat, model, n in conn.execute(
            "select coalesce(d.category_code, '공통'), e.model, count(*) from knowledge_documents d "
            'join document_versions v on v.document_id = d.id and v.is_current join document_chunks c on c.version_id = v.id '
            'join document_chunk_embeddings e on e.chunk_id = c.id group by 1, 2'):
        emb[cat][model] = n
    return [(cat, nd, nc, emb[cat]) for cat, nd, nc in docs]


# ── 전체 흐름 ─────────────────────────────────────────────────

def run(url: str | None, embedders: list, docs: list[str] | None = None, guides: Path = GUIDES,
        base: dict[str, dict] | None | bool = True, dry_run: bool = False, activate_version: bool = True,
        prepared: list[Prepared] | None = None, allow_remote: bool = False, apply_policy: bool = False,
        force_activate: bool = False) -> Report:
    """준비 → 검증 → (dry_run 이 아니면) 교체. 검증에 실패하면 IngestError (DB 변화 없음).

    url 이 없으면 DB 검사(문의 유형 코드·관리 부서·정책·기존 벡터)를 건너뛰고 검증까지만 한다.
    prepared 를 주면 그것을 쓴다 (시험에서 일부를 바꿔 넣을 때).
    """
    report = Report()
    if prepared is None:
        prepared = prepare(load_manifest(guides, docs), guides)
    check_files(prepared, load_baseline() if base is True else base or None, report)
    if not embedders or len({e.model_id for e in embedders}) != len(embedders):
        check_vectors([], [e.model_id for e in embedders], report)        # 모델 없음·중복을 같은 문구로
    if report.problems:                                    # 임베딩(모델당 십여 분) 전에 멈춘다
        raise IngestError(report.problems)
    conn = connect(url, allow_remote) if url else None
    try:
        cache, groups = {}, {}
        if conn:
            codes, groups = read_reference(conn)
            check_reference(prepared, codes, groups, report)
            check_policies(conn, prepared, apply_policy, report)
            if report.problems:
                raise IngestError(report.problems)
            cache = read_vectors(conn, {t for p in prepared for t in p.texts})
            conn.commit()
        embed(prepared, embedders, cache, report)
        check_vectors(prepared, [e.model_id for e in embedders], report)
        if report.problems:
            raise IngestError(report.problems)
        if conn and not dry_run:
            for p in prepared:
                report.results.append(write_document(conn, p, groups, cache, activate_version, force_activate))
    finally:
        if conn:
            conn.close()
    return report
