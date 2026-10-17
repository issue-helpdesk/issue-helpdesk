"""파서 출력 모델. 형식(docx·pptx·pdf·md)과 상관없이 같은 모양으로 돌려준다."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Element:
    """문서 안의 요소 하나. 읽는 순서대로 나열한다.

    kind    : heading / paragraph / list_item / table / image
    level   : heading 일 때만. 0 문서 제목, 1 장(1. 개요), 2 항목(3.1 …), 3 소제목(이런 경우·카드 제목)
    page    : pdf 쪽 번호 또는 pptx 슬라이드 번호 (1부터). docx·md 는 None
    section : 이 요소가 속한 제목 경로. 파싱 마지막에 채운다
    meta    : 형식별 부가 정보. 항목 제목의 meta['props'] = [[문의 유형, SW-02], …]
    """
    kind: str
    text: str = ''
    level: int | None = None
    rows: list[list[str]] | None = None
    page: int | None = None
    order: int = 0
    section: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    path: str
    format: str                                     # docx / pptx / pdf / md
    title: str = ''
    properties: dict = field(default_factory=dict)  # 파일 속성(제목·작성자 등)
    info: dict = field(default_factory=dict)        # 문서 정보 표의 원래 항목 이름 그대로
    meta: dict = field(default_factory=dict)        # 정규화한 메타데이터 (doc_no·version·access_level·scenarios …)
    elements: list[Element] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality: dict = field(default_factory=dict)     # {'mode': 'layout'|'safe', 'coverage': 0~1, 'missing': [...]}
    dropped: list = field(default_factory=list)     # 본문에서 뺀 글자 [[이유, 글자, 쪽], …] (목차·쪽 제목·꼬리말·장 번호)

    def headings(self, max_level: int = 3) -> list[Element]:
        return [e for e in self.elements if e.kind == 'heading' and e.level is not None and e.level <= max_level]

    def tables(self) -> list[Element]:
        return [e for e in self.elements if e.kind == 'table']

    def outline(self) -> list[tuple[int, str]]:
        return [(e.level, e.text) for e in self.headings()]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        """사람이 파싱 결과를 확인하기 위한 미리보기."""
        out = [f'<!-- {self.format} · {self.path} -->']
        if self.meta:
            out.append('| 메타데이터 | 값 |\n|---|---|')
            out.extend(f'| {k} | {", ".join(v) if isinstance(v, list) else v} |' for k, v in self.meta.items())
            out.append('')
        for e in self.elements:
            loc = f' <sub>p.{e.page}</sub>' if e.page else ''
            if e.kind == 'heading':
                out.append('\n' + '#' * min((e.level or 0) + 1, 6) + ' ' + e.text + loc)
                if e.meta.get('props'):
                    out.append('<!-- props: ' + ' · '.join(f'{k}={v}' for k, v in e.meta['props']) + ' -->')
            elif e.kind == 'list_item':
                out.append(f'- {e.text}{loc}')
            elif e.kind == 'table':
                rows = e.rows or []
                if not rows:
                    continue
                n = max(len(r) for r in rows)
                norm = [[c.replace('\n', '<br>').replace('|', '\\|') for c in r] + [''] * (n - len(r)) for r in rows]
                out.append('')
                out.append('| ' + ' | '.join(norm[0]) + ' |' + loc)
                out.append('|' + '---|' * n)
                out.extend('| ' + ' | '.join(r) + ' |' for r in norm[1:])
                out.append('')
            elif e.kind == 'image':
                out.append(f'[그림: {e.text or e.meta.get("name", "")}]{loc}')
            else:
                out.append(e.text + loc)
        if self.warnings:
            out.append('\n<!-- 경고 -->')
            out.extend(f'<!-- {w} -->' for w in self.warnings)
        return '\n'.join(out) + '\n'
