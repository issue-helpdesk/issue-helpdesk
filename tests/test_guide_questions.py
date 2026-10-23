"""가이드 검색 질문(시험지) 점검. 가이드를 고친 PR에서 정답 단위가 깨지면 여기서 실패한다.

dataset/guide_review/{분류}_질문.csv 마다 `python -m app.rag.review check` 와 같은 검사를 한다:
정답 단위가 지금 가이드에 있는지, 문서마다 질문 3개 이상, 평가셋과 같거나 비슷한 질문 없음.
실패하면 해당 csv의 정답 단위를 검증 시트(`{분류}_검증시트.md`)의 단위 칸에 맞춰 고친다.
"""
import glob
import os

import pytest

from app.rag.review import EvalSet, all_units, check_questions, load_manifest, read_questions, sheet_docs

REVIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dataset', 'guide_review')
FILES = sorted(glob.glob(os.path.join(REVIEW, '*_질문.csv')))


@pytest.fixture(scope='module')
def ctx():
    manifest = load_manifest()
    return manifest, EvalSet(), all_units(manifest)


@pytest.mark.skipif(not FILES, reason='dataset/guide_review 질문 파일 없음')
@pytest.mark.parametrize('path', FILES, ids=[os.path.basename(p) for p in FILES])
def test_guide_questions_still_valid(ctx, path):
    manifest, evalset, units = ctx
    sheet = path.replace('_질문.csv', '_검증시트.md')
    targets = sheet_docs(sheet) if os.path.exists(sheet) else None
    errors, warnings = check_questions(read_questions(path), manifest, evalset, units, targets)
    assert errors == [], '\n'.join(errors)
    assert warnings == [], '\n'.join(warnings)     # 평가셋과 비슷한 질문·다른 문서 정답도 막는다
