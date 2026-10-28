"""임베딩 모델 준비(M3-1-2) 테스트.

모델 없이 도는 테스트와, 모델 파일이 있고 RUN_MODEL_TESTS=1 일 때만 도는 테스트로 나뉜다.
모델 테스트는 모델을 실제로 열어 30초 안팎 걸린다:  RUN_MODEL_TESTS=1 pytest tests/test_embedding.py
"""
import os

import pytest

from app.rag.embedding import MAX_SEQ_LENGTH, MODELS, Embedder, check_files, model_dir, model_id


def test_model_ids_pin_revision():
    """임베딩 이름 = 이름@리비전 앞 7자/입력 처리 (청크_메타데이터.md 5장)."""
    assert model_id('kure-v1') == 'kure-v1@8b418a5/v1'
    assert model_id('bge-m3') == 'bge-m3@5617a9f/v1'


def test_default_model_is_bge_m3():
    """M3-2-1 비교로 정한 기본 모델 (search/모델_비교_결과.md). 바꾸면 DB 임베딩 model 값도 같이 맞춰야 한다."""
    from app.rag.embedding import DEFAULT_MODEL
    assert DEFAULT_MODEL == 'bge-m3' and model_id(DEFAULT_MODEL) == 'bge-m3@5617a9f/v1'


def test_both_models_fit_vector_column():
    """두 모델 모두 document_chunk_embeddings.embedding vector(1024) 에 들어간다."""
    assert {spec['dim'] for spec in MODELS.values()} == {1024}
    assert all(len(spec['revision']) == 40 for spec in MODELS.values())


def test_max_seq_length_covers_chunks():
    """가이드 청크 최장 818토큰보다 길어야 잘리지 않는다."""
    assert MAX_SEQ_LENGTH >= 818


def test_model_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv('EMBEDDING_MODEL_DIR', str(tmp_path))
    assert model_dir() == tmp_path.resolve()


def test_missing_files_reported(tmp_path):
    problems = check_files('kure-v1', tmp_path)
    assert problems and all('없음' in p for p in problems)


def test_embedder_explains_missing_model(tmp_path):
    with pytest.raises(FileNotFoundError, match='download'):
        Embedder('kure-v1', base=tmp_path)
    with pytest.raises(ValueError):
        Embedder('openai')


RUN = os.environ.get('RUN_MODEL_TESTS') == '1'


@pytest.mark.skipif(not RUN, reason='RUN_MODEL_TESTS=1 일 때만 모델을 연다')
@pytest.mark.parametrize('key', list(MODELS))
def test_embed_with_local_model(key):
    if check_files(key):
        pytest.skip(f'{key} 모델 파일이 없습니다')
    import numpy as np
    emb = Embedder(key)
    docs = np.array(emb.embed_documents(['프린터 인쇄가 대기열에서 멈춰요. 인쇄 스풀러를 다시 시작합니다.',
                                         '노트북을 켜면 복구 키를 입력하라는 화면이 나옵니다.']))
    q = np.array(emb.embed_query('복구 키 입력 화면이 떠요'))
    assert docs.shape == (2, 1024) and q.shape == (1024,)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-3)
    assert (docs @ q).argmax() == 1          # 복구 키 문장이 더 가깝다
