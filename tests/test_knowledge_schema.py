"""Knowledge 표(마이그레이션·모델)와 청커가 서로 맞는지 DB 없이 검사한다."""
import json
import os
import re
import subprocess
import sys

import pytest

from app.models.knowledge import DocumentChunk, DocumentVersion, KnowledgeDocument
from app.rag.chunker import chunk_document, chunk_row, document_row
from app.rag.parser import parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FINAL = os.path.join(ROOT, 'dataset', 'guides_final')


def allowed(table, name):
    """모델 CHECK 제약 'x in ('A', 'B')' 의 허용 값."""
    ck = next(c for c in table.constraints if c.name and c.name.endswith(name) and hasattr(c, 'sqltext'))
    return set(re.findall(r"'([A-Z_]+)'", str(ck.sqltext)))


@pytest.fixture(scope='module')
def guide_rows():
    with open(os.path.join(FINAL, 'manifest.json'), encoding='utf-8') as f:
        manifest = [d for d in json.load(f) if d.get('rag_target') is not False]
    docs, chunks = [], []
    for d in manifest:
        doc = parse(os.path.join(FINAL, d['files']['md']))
        docs.append(document_row(doc))
        chunks.append(chunk_document(doc))
    return docs, chunks


def test_chunk_row_matches_model_columns():
    """청커가 내는 행의 키 = document_chunks 칸 (DB가 채우는 id·version_id 제외). 한쪽만 바뀌면 걸린다."""
    cols = {c.name for c in DocumentChunk.__table__.columns} - {'id', 'version_id'}
    doc = parse(os.path.join(FINAL, 'SW', 'guide', 'IT-SW-003_업무용 SW 실행·오류 대응 가이드.md'))
    assert set(chunk_row(chunk_document(doc)[0])) == cols


def test_guide_values_fit_constraints(guide_rows):
    docs, chunks = guide_rows
    assert {d['doc_type'] for d in docs} <= allowed(KnowledgeDocument.__table__, 'doc_type')
    rows = [chunk_row(c) for cs in chunks for c in cs]
    assert {r['chunk_type'] for r in rows} <= allowed(DocumentChunk.__table__, 'chunk_type')
    assert all(r['part'] >= 1 and r['unit_key'] for r in rows)
    for cs in chunks:                                   # UNIQUE(version_id, seq), UNIQUE(version_id, unit_key, part)
        assert len({c.seq for c in cs}) == len(cs)
        assert len({(c.unit_key, c.part) for c in cs}) == len(cs)


def test_current_rule_in_model():
    names = {c.name for c in DocumentVersion.__table__.constraints} | {i.name for i in DocumentVersion.__table__.indexes}
    assert 'ck_document_versions_current_needs_done' in names and 'uq_document_versions_one_current' in names


def test_migration_sql_offline():
    """DB 없이 마이그레이션 SQL을 만든다: 칸 추가 → 채울 수 있는 행인지 검사 → 기존 행 채우기 → 검사 → 제약 순서,
    한 트랜잭션."""
    env = {**os.environ, 'DATABASE_URL': 'postgresql://u:p@localhost/offline', 'PYTHONIOENCODING': 'utf-8'}
    out = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', '2793dd581cae:head', '--sql'],
                         cwd=os.path.join(ROOT, 'backend'), env=env, capture_output=True, text=True,
                         encoding='utf-8', check=True).stdout
    steps = ['ADD COLUMN seq INTEGER', 'FAQ가 아닌 문서의 청크', "chunk_type = 'FAQ'", '현행 버전이 둘 이상',
             'ALTER COLUMN seq SET NOT NULL', 'uq_document_versions_one_current',
             'ck_document_versions_current_needs_done', 'COMMIT']
    pos = [out.find(s) for s in steps]
    assert all(i >= 0 for i in pos) and pos == sorted(pos), dict(zip(steps, pos))
