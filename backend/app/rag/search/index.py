"""과거 사례 임베딩 만들기 (M3-3-1 준비). 과거 이력은 시드로 한 번만 들어오고 읽기 전용이라 여기서 한 번 임베딩한다.

    python -m app.rag.search.index legacy --model kure-v1      # backend 폴더에서. DATABASE_URL 의 DB 에 넣는다

임베딩 글은 제목·증상·원인·해결을 이어 붙인 것이다 (테이블 설계서 legacy_inquiry_embeddings.source_text).
이미 같은 모델·같은 글로 만든 행은 건너뛴다. 가이드 청크 임베딩은 적재 스크립트(M2-2-1)가 만든다.
"""
import argparse
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.search.service import vector_literal

ROWS_SQL = text("""
    select li.id, li.title, li.description, li.root_cause, li.resolution, le.source_text as old_text
    from legacy_inquiries li
    left join legacy_inquiry_embeddings le on le.legacy_inquiry_id = li.id and le.model = :model
    order by li.id
""")

UPSERT_SQL = text("""
    insert into legacy_inquiry_embeddings (legacy_inquiry_id, model, embedding, source_text)
    values (:id, :model, cast(:vec as vector), :src)
    on conflict (legacy_inquiry_id, model) do update
    set embedding = excluded.embedding, source_text = excluded.source_text, created_at = now()
""")


def legacy_source_text(title, description, root_cause, resolution) -> str:
    """과거 사례 한 건의 임베딩 글. 사람을 가리키는 칸(요청자·담당자)은 넣지 않는다."""
    parts = [('제목', title), ('증상', description), ('원인', root_cause), ('해결', resolution)]
    return '\n'.join(f'{k}: {v.strip()}' for k, v in parts if v and v.strip())


def embed_legacy(session: Session, embedder, batch_size: int = 32) -> int:
    """임베딩이 없거나 글이 바뀐 과거 사례만 임베딩한다. 넣은 건수를 돌려준다. 커밋은 호출하는 쪽이 한다."""
    rows = session.execute(ROWS_SQL, {'model': embedder.model_id}).mappings().all()
    todo = []
    for r in rows:
        src = legacy_source_text(r['title'], r['description'], r['root_cause'], r['resolution'])
        if src and src != r['old_text']:
            todo.append((r['id'], src))
    for i in range(0, len(todo), batch_size):
        part = todo[i:i + batch_size]
        vecs = embedder.embed_documents([src for _, src in part])
        session.execute(UPSERT_SQL, [{'id': lid, 'model': embedder.model_id, 'vec': vector_literal(v), 'src': src}
                                     for (lid, src), v in zip(part, vecs)])
    return len(todo)


def main() -> int:
    from app.db.session import get_engine
    from app.rag.embedding import DEFAULT_MODEL, MODELS, Embedder

    ap = argparse.ArgumentParser(description='과거 사례 임베딩 만들기')
    ap.add_argument('target', choices=['legacy'])
    ap.add_argument('--model', choices=list(MODELS), default=DEFAULT_MODEL)
    args = ap.parse_args()
    with Session(get_engine()) as session:
        n = embed_legacy(session, Embedder(args.model))
        session.commit()
    print(f'과거 사례 임베딩 {n}건 ({args.model})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
