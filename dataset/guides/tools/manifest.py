"""guides/manifest.json: RAG 등록·백엔드 열람 등급 적용에 쓰는 문서 목록."""
import json
import os

from model import *
from build import out_dir, base_name

# 외부 모델 전송 정책 (M4-1-3, README "외부 전송 정책"). 열람 등급과 따로 정한다 (IT-STD-002). 모르는 종류는 BLOCKED
TRANSFER_POLICY = {'guide': 'ALLOWED', 'standard': 'ALLOWED', 'manual': 'BLOCKED', 'policy': 'BLOCKED'}


def main():
    rows = []
    for p_ in all_sources():
        m = load(p_)['meta']
        base = os.path.relpath(os.path.join(out_dir(m), base_name(m)), ROOT).replace(os.sep, '/')
        rows.append({
            'doc_no': m['doc_no'], 'title': m['title'], 'category': m['category'], 'doc_type': m['doc_type'],
            'access_level': m['access'], 'audience': m.get('audience', ''), 'owner': m['owner'],
            'version': m['version'], 'effective_date': m['date'], 'pair': m.get('pair', ''),
            'scenarios': m.get('scenarios', []),
            'rag_target': m['doc_type'] in ('guide', 'manual', 'standard'),
            'transfer_policy': TRANSFER_POLICY.get(m['doc_type'], 'BLOCKED'),
            'files': {e: f'{base}.{e}' for e in ('pdf', 'pptx', 'docx', 'md')},
        })
    with open(os.path.join(ROOT, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(len(rows), 'docs')


if __name__ == '__main__':
    main()
