"""FAQ 게시판 표(faqs)와 시드가 서로 맞는지 DB 없이 검사한다."""
import importlib.util
import os

import pytest

from app.models.knowledge import Faq, KnowledgeDocument

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def load_seed():
    spec = importlib.util.spec_from_file_location('seed', os.path.join(ROOT, 'db', 'seed.py'))
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    return seed


@pytest.fixture(scope='module')
def plan():
    p = load_seed().build()
    assert not p.problems, p.problems
    return p


def test_seed_makes_40_faqs(plan):
    rows = plan.rows['faqs']
    assert len(rows) == 40
    assert len({r['faq_code'] for r in rows}) == 40                     # 번호가 겹치지 않는다


def test_faq_rows_fit_model(plan):
    cols = {c.name for c in Faq.__table__.columns}
    required = {c.name for c in Faq.__table__.columns                    # 값을 꼭 넣어야 하는 칸
                if not c.nullable and c.server_default is None and not c.primary_key}
    for r in plan.rows['faqs']:
        assert set(r) <= cols and required <= set(r)
        assert r['question'] and r['answer'] and isinstance(r['keywords'], list)


def test_faq_categories_exist(plan):
    codes = {c['code'] for c in plan.rows['categories']}
    assert {r['category_code'] for r in plan.rows['faqs']} <= codes


def test_faq_not_in_knowledge(plan):
    """FAQ는 Knowledge(검색 대상)에 넣지 않는다 (설계서 결정 사항 8)."""
    assert 'knowledge_documents' not in plan.rows
    doc_type = next(c for c in KnowledgeDocument.__table__.constraints if c.name and c.name.endswith('doc_type'))
    assert "'FAQ'" not in str(doc_type.sqltext)