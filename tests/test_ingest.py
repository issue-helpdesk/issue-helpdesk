"""가이드 적재(app.rag.ingest)의 준비·검증을 DB 없이 검사한다. DB 교체는 test_ingest_db.py."""
import math

import pytest

from app.rag.ingest import (FakeEmbedder, IngestError, Report, check_files, check_reference, check_vectors, connect,
                            embed, is_local, load_baseline, load_manifest, prepare, run)


@pytest.fixture(scope='module')
def prepared():
    return prepare(load_manifest())


def test_all_guides_pass(prepared):
    """검색 대상 56종, 청크 712개. 파서 경고·validate·기준표·manifest 값 모두 통과."""
    assert len(prepared) == 56 and 'IT-AI-001' not in {p.doc_code for p in prepared}
    assert sum(len(p.chunks) for p in prepared) == 712
    report = Report()
    check_files(prepared, load_baseline(), report)
    assert report.problems == [] and report.warnings == []


def test_transfer_policy_from_manifest(prepared):
    """D 결정(PR #70): 가이드·공통 기준 ALLOWED, 매뉴얼 BLOCKED. 적재는 manifest 값을 그대로 쓴다."""
    for p in prepared:
        assert p.version['transfer_policy'] == p.entry['transfer_policy']
        assert p.version['transfer_policy'] == ('BLOCKED' if p.entry['doc_type'] == 'manual' else 'ALLOWED')


def test_missing_transfer_policy_warns_and_blocks():
    entry = {k: v for k, v in load_manifest(docs=['IT-SW-003'])[0].items() if k != 'transfer_policy'}
    [p] = prepare([entry])
    report = Report()
    check_files([p], load_baseline(), report)
    assert p.version['transfer_policy'] == 'BLOCKED'
    assert report.problems == [] and any('BLOCKED' in w for w in report.warnings)


def test_baseline_mismatch_stops_before_db():
    base = load_baseline()
    base['IT-SW-003'] = {**base['IT-SW-003'], 'chunks': base['IT-SW-003']['chunks'] + 1}
    with pytest.raises(IngestError) as ex:
        run(None, [FakeEmbedder()], docs=['IT-SW-003'], base=base)
    assert any('기준표' in x for x in ex.value.problems)


def test_unknown_inquiry_code_and_owner(prepared):
    report = Report()
    check_reference(prepared, codes=set(), groups={}, report=report)
    assert any('문의 유형 코드' in x for x in report.problems)
    assert any('관리 부서' in x for x in report.problems)


def test_missing_embedding_detected():
    [p] = prepare(load_manifest(docs=['IT-SW-003']))

    class Short(FakeEmbedder):                             # 마지막 글의 벡터를 빼먹는 임베딩기
        def embed_documents(self, texts, batch_size=16):
            return super().embed_documents(texts)[:-1]

    report = Report()
    embed([p], [FakeEmbedder('kure-v1'), Short('bge-m3')], {}, report)
    check_vectors([p], ['fake-kure-v1@0000000/v1', 'fake-bge-m3@0000000/v1'], report)
    assert len(report.problems) == 1 and 'bge-m3' in report.problems[0]


def test_fake_embedder_is_deterministic_unit_vector():
    a, b = FakeEmbedder('kure-v1'), FakeEmbedder('bge-m3')
    v = a.embed_documents(['노트북이 안 켜져요'])[0]
    assert len(v) == 1024 and math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-9)
    assert v == a.embed_query('노트북이 안 켜져요') and v != b.embed_query('노트북이 안 켜져요')
    assert a.model_id != b.model_id and a.model_id.startswith('fake-')


def test_reuse_cache_skips_embedding():
    [p] = prepare(load_manifest(docs=['IT-SW-003']))
    emb = FakeEmbedder()
    cache = {(emb.model_id, t): emb.embed_query(t) for t in p.texts[1:]}
    emb.calls = 0
    report = Report()
    embed([p], [emb], cache, report)
    assert emb.calls == 1 and report.embedded[emb.model_id] == {'new': 1, 'reused': len(p.texts) - 1}


def test_bad_vectors_detected():
    """0벡터처럼 길이가 1이 아닌 벡터는 통과시키지 않는다 (검수 #7)."""
    [p] = prepare(load_manifest(docs=['IT-SW-003']))
    p.vectors['m'] = [[0.0] * 1024 for _ in p.chunks]
    report = Report()
    check_vectors([p], ['m'], report)
    assert report.problems and '단위 벡터' in report.problems[0]


@pytest.mark.parametrize('models', [[], ['kure-v1', 'kure-v1']])
def test_no_or_duplicate_models_rejected(models):
    """모델이 없거나 겹치면 임베딩 없이 DONE 이 되지 않게 쓰기 전에 멈춘다 (검수 #1)."""
    with pytest.raises(IngestError):
        run(None, [FakeEmbedder(k) for k in models], docs=['IT-SW-003'])


@pytest.mark.parametrize('url, local', [
    ('postgresql://postgres:verify@localhost:55433/ingest', True),
    ('postgresql://u@127.0.0.1/x', True),
    ('postgresql://u@localhost:55433/x?host=review.invalid', False),           # 주소 뒤 host 가 실제 접속 대상
    ('postgresql://u@localhost/x?hostaddr=10.0.0.1', False),
    ('postgresql://u@localhost,db.example.com/x', False),                     # 여러 호스트
    ('postgresql://u@db.supabase.co:5432/postgres', False),
    ('postgresql://u@localhost/x?service=prod', False),
])
def test_is_local(url, local):
    """공유 DB 보호: libpq 가 해석한 접속 대상으로 판단한다 (검수 #4). 실제로 접속하지 않는다."""
    assert is_local(url) is local


def test_remote_url_refused_without_flag(monkeypatch):
    import app.rag.ingest.__main__ as cli
    reached = []
    monkeypatch.setattr(cli, 'run', lambda *a, **k: reached.append(a))
    url = 'postgresql://postgres:verify@localhost:55433/postgres?host=review.invalid'
    assert cli.main(['--database-url', url, '--embedder', 'fake', '--dry-run']) == 2 and not reached
    with pytest.raises(ValueError, match='allow_remote'):
        connect(url)                                       # 공개 함수도 같은 보호 (접속 전에 거절)
