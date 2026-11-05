"""가이드 상황 목록 (WBS M4-3-1). 1차 판단(검색 전)이 문의가 어느 상황인지 정하거나 되물을 때 고르는 선택지.

현행 가이드(manifest doc_type=guide, 외부 전송 ALLOWED)의 3.x 절 제목만 모은다 (IT-STD-002 5장: 3.x = 증상별 상황).
매뉴얼은 외부 전송 BLOCKED 라 넣지 않는다 (docs/10).

서버 이미지에는 dataset 이 없어서 목록을 situations.txt 로 만들어 두고 읽는다.
가이드를 바꾸면 backend 폴더에서 다시 만든다:  uv run python -m app.agent.llm.situations
tests/test_situations.py 가 파일이 가이드와 같은지 확인한다.
"""
import json
import re
from pathlib import Path

FILE = Path(__file__).with_name('situations.txt')
GUIDES = Path(__file__).resolve().parents[4] / 'dataset' / 'guides'
HEADING = re.compile(r'^### (3\.\d+) (.+?)\s*$', re.M)


def build(guides_dir: Path = GUIDES) -> str:
    """'문서번호 제목' 줄 아래에 '  3.x 상황 제목' 줄. 문서번호 순."""
    manifest = json.loads((guides_dir / 'manifest.json').read_text(encoding='utf-8'))
    lines = []
    for d in sorted(manifest, key=lambda d: d['doc_no']):
        if d['doc_type'] != 'guide' or not d['rag_target'] or d['transfer_policy'] != 'ALLOWED':
            continue
        text = (guides_dir / d['files']['md']).read_text(encoding='utf-8')
        lines.append(f"{d['doc_no']} {d['title']}")
        lines += [f'  {no} {title}' for no, title in HEADING.findall(text)]
    return '\n'.join(lines) + '\n'


def load() -> str:
    return FILE.read_text(encoding='utf-8')


if __name__ == '__main__':
    FILE.write_text(build(), encoding='utf-8', newline='\n')
    print(f'{FILE} ({len(load()):,}자)')
