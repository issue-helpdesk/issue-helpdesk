"""guides/manifest.json: RAG 등록·백엔드 열람 등급 적용에 쓰는 문서 목록."""
import json
import os

from model import *
from build import out_dir, base_name


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
            'files': {e: f'{base}.{e}' for e in ('pdf', 'pptx', 'docx', 'md')},
        })
    with open(os.path.join(ROOT, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(len(rows), 'docs')


if __name__ == '__main__':
    main()
