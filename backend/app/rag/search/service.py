"""검색 (WBS M3-2-2 검색, M3-2-3 권한 필터). 처리 순서는 청크_메타데이터.md 8장.

    from app.rag.search.service import search
    resp = search(session, SearchRequest(query=build_query(user_messages), service_role=user.service_role), embedder)

1. 벡터 검색: 선택 모델의 임베딩으로 k × 3 개 청크를 뽑는다. 조건은 SQL 에서 건다
   - 현행·적재 완료 버전, 활성 문서, **사용자 역할이 볼 수 있는 view_scope** (권한 필터), 분류(공통 기준 포함)
2. 단위 복원: ITEM·FAQ·PREFACE 는 같은 unit_key 조각을 모두, CHAPTER 는 맞은 조각과 앞뒤 조각만 붙인다
   붙이는 조각도 1의 조건을 똑같이 통과해야 한다 (같은 버전 안에서만 찾는다)
3. 중복 묶기: 본문이 같고 transfer_policy 도 같은 단위는 하나로. 대표는 문의 분류와 같은 문서 → 공통 문서 → 점수
4. 개수 맞추기: 단위가 k 개보다 적으면 k × 6 개로 한 번 더 뽑는다

열람 범위 밖 문서는 결과·근거·also_in 어디에도 나오지 않는다 (SRS GUIDE-06).
"""
import hashlib
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.search.evidence import pick_evidence
from app.rag.search.result import (DEFAULT_THRESHOLD, ChunkHit, DocumentResult, LegacyResult, SearchRequest,
                                   SearchResponse, visible_scopes)

ALLOWED = """
    d.is_active and v.is_current and v.ingest_status = 'DONE'
    and v.view_scope = any(:scopes)
    and (cast(:cat as text) is null or d.category_code = cast(:cat as text) or d.category_code is null)
"""

HITS_SQL = text(f"""
    select c.id, c.version_id, c.unit_key, c.chunk_type, c.part,
           1 - (e.embedding <=> cast(:q as vector)) as score
    from document_chunk_embeddings e
    join document_chunks c on c.id = e.chunk_id
    join document_versions v on v.id = c.version_id
    join knowledge_documents d on d.id = v.document_id
    where e.model = :model and {ALLOWED}
    order by e.embedding <=> cast(:q as vector)
    limit :n
""")

PIECES_SQL = text(f"""
    select c.id, c.unit_key, c.chunk_type, c.part, c.content, c.heading_path, c.location, c.meta,
           d.doc_code, d.title, d.category_code, v.version, v.view_scope, v.transfer_policy
    from document_chunks c
    join document_versions v on v.id = c.version_id
    join knowledge_documents d on d.id = v.document_id
    where c.version_id = :vid and c.unit_key = :uk and {ALLOWED}
    order by c.part
""")

LEGACY_SQL = text("""
    select li.id, li.legacy_no, it.code as type_code, li.title, coalesce(le.source_text, '') as source_text,
           coalesce(li.root_cause, '') as root_cause, coalesce(li.resolution, '') as resolution, li.resolved_at,
           li.view_scope, li.transfer_policy, 1 - (le.embedding <=> cast(:q as vector)) as score
    from legacy_inquiry_embeddings le
    join legacy_inquiries li on li.id = le.legacy_inquiry_id
    left join inquiry_types it on it.id = li.inquiry_type_id
    where le.model = :model and li.view_scope = any(:scopes)
      and (cast(:cat as text) is null or it.category_code = cast(:cat as text))
    order by le.embedding <=> cast(:q as vector)
    limit :n
""")


def vector_literal(vec) -> str:
    return '[' + ','.join(f'{x:.7f}' for x in vec) + ']'


def search(session: Session, request: SearchRequest, embedder, threshold: float = DEFAULT_THRESHOLD) -> SearchResponse:
    """질문 → 가이드·과거 사례 검색 결과. embedder 는 서버가 시작할 때 한 번 연 Embedder 를 넘긴다."""
    t0 = time.perf_counter()
    scopes = list(visible_scopes(request.service_role))
    q = vector_literal(embedder.embed_query(request.query))
    params = {'q': q, 'model': embedder.model_id, 'scopes': scopes, 'cat': request.category_code}
    documents, legacy = (), ()
    if scopes and 'DOCUMENT' in request.sources:
        documents = _documents(session, request, params, f'cosine:{embedder.model_id}')
    if scopes and 'LEGACY' in request.sources:
        legacy = _legacy(session, request, params, f'cosine:{embedder.model_id}')
    return SearchResponse(query=request.query, model=embedder.model_id, threshold=threshold, documents=documents,
                          legacy=legacy, took_ms=int((time.perf_counter() - t0) * 1000))


def _documents(session, request, params, score_type) -> tuple[DocumentResult, ...]:
    k = request.top_k
    units = []
    for n in (k * 3, k * 6):                                       # 4. 모자라면 한 번 더 넓게
        hits = session.execute(HITS_SQL, {**params, 'n': n}).mappings().all()
        units = _merge(_restore(session, hits, params), request.category_code)
        if len(units) >= k:
            break
    return tuple(_to_result(u, request.query, score_type) for u in units[:k])


def _restore(session, hits, params):
    """2. 단위 복원. 맞은 청크를 (버전, unit_key) 로 묶고 조각을 붙인다."""
    groups = {}
    for h in hits:
        g = groups.setdefault((h['version_id'], h['unit_key']), {'scores': {}, 'type': h['chunk_type']})
        g['scores'][h['id']] = max(float(h['score']), g['scores'].get(h['id'], -1))
    units = []
    for (vid, uk), g in groups.items():
        pieces = session.execute(PIECES_SQL, {**params, 'vid': vid, 'uk': uk}).mappings().all()
        if g['type'] == 'CHAPTER':                                 # 장은 맞은 조각과 앞뒤만
            parts = {p['part'] for p in pieces if p['id'] in g['scores']}
            pieces = [p for p in pieces if any(abs(p['part'] - x) <= 1 for x in parts)]
        if not pieces:
            continue
        units.append({'pieces': pieces, 'scores': g['scores'], 'best': max(g['scores'].values())})
    return sorted(units, key=lambda u: -u['best'])


def _merge(units, category):
    """3. 중복 묶기. 본문 지문 + transfer_policy 가 같으면 하나로, 나머지는 also_in."""
    groups = {}
    for u in units:
        body = '\n'.join(p['content'] for p in u['pieces'])
        key = (hashlib.sha1(body.encode('utf-8')).hexdigest(), u['pieces'][0]['transfer_policy'])
        groups.setdefault(key, []).append(u)
    merged = []
    for same in groups.values():
        same.sort(key=lambda u: (u['pieces'][0]['category_code'] != category or category is None,
                                 u['pieces'][0]['category_code'] is not None, -u['best']))
        rep = same[0]
        rep['also_in'] = tuple(x['pieces'][0]['unit_key'] for x in same[1:])
        rep['best'] = max(x['best'] for x in same)
        merged.append(rep)
    return sorted(merged, key=lambda u: -u['best'])


def _to_result(u, query, score_type) -> DocumentResult:
    first = u['pieces'][0]
    hit_meta = next((p['meta'] for p in u['pieces'] if p['id'] in u['scores']), first['meta']) or {}
    body = '\n'.join(p['content'] for p in u['pieces'])
    text_ = f"{first['title']} > {first['heading_path'] or ''}\n{body}".strip()
    return DocumentResult(
        unit_key=first['unit_key'], chunk_type=first['chunk_type'], doc_code=first['doc_code'], title=first['title'],
        version=first['version'], location=first['location'] or '', heading_path=first['heading_path'] or '',
        text=text_, chunks=tuple(ChunkHit(p['id'], p['part'], u['scores'].get(p['id'])) for p in u['pieces']),
        unit_score=round(u['best'], 4), score_type=score_type, view_scope=first['view_scope'],
        transfer_policy=first['transfer_policy'], evidence=pick_evidence(query, body),
        inquiry_type_codes=tuple(hit_meta.get('inquiry_type_codes') or ()), handling=hit_meta.get('handling') or '',
        also_in=u.get('also_in', ()))


def _legacy(session, request, params, score_type) -> tuple[LegacyResult, ...]:
    rows = session.execute(LEGACY_SQL, {**params, 'n': request.top_k}).mappings().all()
    out = []
    for r in rows:
        txt = r['source_text'] or f"{r['title'] or ''}\n{r['root_cause']}\n{r['resolution']}"
        out.append(LegacyResult(
            legacy_inquiry_id=r['id'], legacy_no=r['legacy_no'], inquiry_type_code=r['type_code'],
            title=r['title'] or '', text=txt, root_cause=r['root_cause'], resolution=r['resolution'],
            resolved_at=r['resolved_at'].strftime('%Y-%m-%d %H:%M') if r['resolved_at'] else None,
            score=round(float(r['score']), 4), score_type=score_type, view_scope=r['view_scope'],
            transfer_policy=r['transfer_policy'], evidence=pick_evidence(request.query, txt)))
    return tuple(out)
