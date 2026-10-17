"""가이드 문서 공통 파서 (WBS M2-1-1).

PPTX·PDF·DOCX·MD·TXT를 읽어 같은 모양(ParsedDocument)으로 돌려준다:
제목(수준·경로), 문단, 목록, 표, 그림, 위치(쪽·슬라이드), 문서 메타데이터, 항목 머리 정보(props).
기준 문서는 dataset/guides_final (원천 JSON 하나에서 네 형식을 만든 정리본)이다.

    from app.rag.parser import parse, ParseError
    try:
        doc = parse(path)
    except ParseError as e:
        e.reason, e.message      # 'encrypted', '암호가 걸린 문서입니다. …'

안전장치
- 파일 점검: 없음·빈 파일·지원하지 않는 형식(hwp·doc·ppt 등은 변환 안내)·손상·암호 → ParseError
- 누락 감지: 파일의 원래 글자와 결과를 비교한다(quality.py: 포함률·빠진 문단·빠진 숫자·코드·제외량).
  문제가 있으면 제목 띠·꼬리말 글자도 버리지 않는 보수 모드(safe)로 다시 읽고, 내용을 더 잘 지킨 쪽을 쓴다.
  결과는 doc.quality 와 로그에 남는다.
- 쪽·슬라이드 하나가 깨져도 나머지는 읽고, 그 쪽은 글자만 추출한다 (doc.warnings).
- 글자를 하나도 얻지 못하면(스캔 PDF 등) ParseError('no_text').
"""
from __future__ import annotations

import logging
import os
import time
import zipfile

from .errors import CONVERT_HINT, ParseError
from .models import Element, ParsedDocument

log = logging.getLogger(__name__)

PARSER_VERSION = '1.0'          # 결과가 바뀌는 수정을 하면 올린다 (가이드 버전 표 parser_version)
SUPPORTED = ('.docx', '.pptx', '.pdf', '.md', '.txt')
OLE_MAGIC = b'\xd0\xcf\x11\xe0'   # 암호 걸린 OOXML 또는 구형(doc·ppt) 파일


def parse(path: str, safe: bool | None = None) -> ParsedDocument:
    """문서를 읽는다. safe=None 이면 자동(누락이 감지될 때만 보수 모드), True/False 면 그 모드로만 읽는다."""
    t0 = time.time()
    ext = os.path.splitext(path)[1].lower()
    try:
        _check_file(path, ext)
        doc = _parse_checked(path, ext, safe)
    except ParseError as e:
        log.warning('파싱 실패 %s: %s', os.path.basename(path), e)
        raise
    q = doc.quality
    log.info('파싱 %s: %s %s모드 포함률=%.3f 요소=%d 쪽=%s %dms%s', os.path.basename(path), doc.format,
             q.get('mode', '-'), q.get('coverage', 1.0), len(doc.elements), doc.properties.get('pages', '-'),
             int((time.time() - t0) * 1000), (' 경고=' + '; '.join(doc.warnings)) if doc.warnings else '')
    return doc


def _check_file(path: str, ext: str) -> None:
    if ext not in SUPPORTED:
        raise ParseError('unsupported', path, ext, CONVERT_HINT.get(ext, '지원 형식: ' + ', '.join(SUPPORTED)))
    if not os.path.isfile(path):
        raise ParseError('not_found', path)
    if os.path.getsize(path) == 0:
        raise ParseError('empty', path)
    with open(path, 'rb') as f:
        head = f.read(1024)
    if ext in ('.docx', '.pptx'):
        if head.startswith(OLE_MAGIC):
            raise ParseError('encrypted', path, 'OLE 컨테이너 (암호 걸린 문서 또는 구형 doc·ppt를 확장자만 바꾼 파일)')
        if not zipfile.is_zipfile(path):
            raise ParseError('corrupt', path, 'zip 형식이 아님')
    if ext == '.pdf':
        if b'%PDF' not in head:
            raise ParseError('corrupt', path, 'PDF 머리(%PDF)가 없음')
        from pypdf import PdfReader
        try:
            encrypted = PdfReader(path).is_encrypted
        except Exception as ex:
            raise ParseError('corrupt', path, f'{type(ex).__name__}: {ex}') from ex
        if encrypted:
            raise ParseError('encrypted', path)


def _reader(ext: str):
    if ext == '.docx':
        from .docx_parser import parse_docx
        return parse_docx
    if ext == '.pptx':
        from .pptx_parser import parse_pptx
        return parse_pptx
    if ext == '.pdf':
        from .pdf_parser import parse_pdf
        return parse_pdf
    from .md_parser import parse_md
    return parse_md


def _run(reader, path: str, safe: bool) -> ParsedDocument:
    try:
        return reader(path, safe)
    except ParseError:
        raise
    except (zipfile.BadZipFile, KeyError) as ex:
        raise ParseError('corrupt', path, f'{type(ex).__name__}: {ex}') from ex
    except Exception as ex:
        log.exception('파서 내부 오류 %s', path)
        raise ParseError('failed', path, f'{type(ex).__name__}: {ex}') from ex


def _score(q: dict) -> tuple:
    """두 결과 중 무엇이 내용을 더 잘 지켰는지: 빠진 문단·값이 적고 포함률이 높은 쪽."""
    return (-len(q['long_missing']) - len(q['missing_values']), q['coverage'])


def _parse_checked(path: str, ext: str, safe: bool | None) -> ParsedDocument:
    from .quality import assess, problems, raw_pieces

    reader = _reader(ext)
    doc = _run(reader, path, bool(safe))
    pieces = raw_pieces(path, doc.format)
    q = assess(doc, pieces)
    mode = 'safe' if safe else 'layout'
    if safe is None and not q['ok']:
        alt = _run(reader, path, True)
        alt_q = assess(alt, pieces)
        log.warning('누락 감지 %s: %s → 보수 모드로 다시 읽음 (포함률 %.3f → %.3f)',
                    os.path.basename(path), '; '.join(problems(q)), q['coverage'], alt_q['coverage'])
        if _score(alt_q) > _score(q):
            alt.warnings.append('배치 규칙으로 읽으면 내용이 빠져 보수 모드로 읽음 (구조 정보가 적을 수 있음): '
                                + '; '.join(problems(q)))
            doc, q, mode = alt, alt_q, 'safe'
    doc.warnings += [p + ' — 빠진 내용이 있을 수 있음' for p in problems(q)]
    doc.quality = {'mode': mode, **q}
    if not any(e.text.strip() or e.rows for e in doc.elements if e.kind != 'image'):
        detail = '; '.join(doc.warnings) or '글자 없음'
        raise ParseError('no_text', path, detail, 'PDF라면 스캔본일 수 있으니 글자가 있는 원본을 올려 주세요.')
    return doc


__all__ = ['parse', 'ParseError', 'Element', 'ParsedDocument', 'SUPPORTED', 'PARSER_VERSION']
