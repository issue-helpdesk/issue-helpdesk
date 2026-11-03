"""가이드 그림 사본 dataset/guide_images 가 원본·청크와 맞는지 (청크_메타데이터.md 5장 그림).
원본 dataset/guides/{분류}/images 를 고치고 사본·index.csv 를 같이 고치지 않으면 여기서 걸린다."""
import csv
import filecmp
import os
import re
from collections import Counter

import pytest

from app.rag.chunker import chunk_document, chunk_row
from app.rag.parser import parse
from test_parser import manifest

DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dataset')
GUIDES, COPY = os.path.join(DATASET, 'guides'), os.path.join(DATASET, 'guide_images')
SUFFIXES = ('.png', '.jpg', '.jpeg')
KEY_RE = re.compile(r'^[A-Z]+/[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g)$')


def _images(root, pattern):
    """{'분류/파일 이름': 경로}. pattern: 분류 폴더 아래 그림 폴더 (원본 'images', 사본 '')."""
    out = {}
    for cat in sorted(os.listdir(root)):
        folder = os.path.join(root, cat, pattern)
        if os.path.isdir(folder):
            out.update({f'{cat}/{n}': os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(SUFFIXES)})
    return out


@pytest.fixture(scope='module')
def uses():
    """청크가 쓰는 그림: 그림을 쓰는 곳마다 (이름표, 문서 번호, 위치, 설명)."""
    out = []
    for doc_no, m in manifest().items():
        if m.get('rag_target') is not True:
            continue
        for c in chunk_document(parse(os.path.join(GUIDES, m['files']['md']))):
            out += [(im['key'], doc_no, chunk_row(c)['location'], im['caption']) for im in c.images]
    return out


def test_copy_matches_source():
    src, dst = _images(GUIDES, 'images'), _images(COPY, '')
    assert sorted(dst) == sorted(src), '원본과 사본의 그림 목록이 다르다'
    assert [k for k in src if not filecmp.cmp(src[k], dst[k], shallow=False)] == [], '내용이 다른 그림'
    names = Counter(k.split('/')[1] for k in src)
    assert [n for n, c in names.items() if c > 1] == [], '분류가 달라도 파일 이름이 겹치면 안 된다'
    assert [k for k in src if not KEY_RE.match(k)] == []


def test_chunk_keys_exist_in_copy(uses):
    """md 의 그림은 모두 청크 이름표로 들어가고 (364곳), 이름표마다 사본 파일이 있다. 안 쓰는 그림도 없다."""
    md_refs = sum(len(re.findall(r'^!\[.*\]\([^()]+\)\s*$', open(os.path.join(GUIDES, m['files']['md']), encoding='utf-8').read(), re.M))
                  for m in manifest().values() if m.get('rag_target') is True)
    assert len(uses) == md_refs == 364
    keys = {u[0] for u in uses}
    assert keys == set(_images(COPY, ''))
    for key, doc_no, *_ in uses:
        assert key.split('/')[0] == manifest()[doc_no]['category']


def test_index_matches_chunks(uses):
    with open(os.path.join(COPY, 'index.csv'), encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert [(r['이름표'], r['문서 번호'], r['위치'], r['그림 설명']) for r in rows] == uses
    for r in rows:
        cat, name = r['이름표'].split('/')
        assert (r['파일 이름'], r['분류']) == (name, cat)
        assert r['원본 경로'] == f'dataset/guides/{cat}/images/{name}' and r['상대 경로'] == f'guide_images/{r["이름표"]}'
        assert r['열람 등급'] == manifest()[r['문서 번호']]['access_level']
