"""가이드 공통 데이터 모델.

문서 하나 = JSON 하나 (tools/source/{분류}/{문서 번호}.json).
렌더러(render_md, render_docx, render_slides)는 이 구조만 읽는다.

doc = {
  "meta": {...},                       # 문서 정보 (아래 META_KEYS)
  "chapters": [
    {"no": "1", "title": "개요", "items": [...], "sections": [
        {"no": "3.1", "title": "...", "props": [[키, 값], ...], "items": [...]}
    ]}
  ]
}

items 의 각 요소는 {"t": 종류, ...} 형태다.
  h      소제목                       {"t":"h","text"}
  p      문단 (**굵게** 지원)          {"t":"p","text"}
  ul/ol  목록                         {"t":"ul","items":[...]}
  table  표                           {"t":"table","head":[...],"rows":[[...]],"widths":[비율],"badge_col":열 번호}
  kv     키-값 표                      {"t":"kv","rows":[[키, 값]]}
  cols   카드 여러 칸                  {"t":"cols","cols":[{"title","items":[...]}]}
  note   강조 상자 (star|info)         {"t":"note","kind","title","lines":[...]}
  fig    그림                         {"t":"fig","src","caption","points":[...],"note"}
  quote  안내 문구                     {"t":"quote","text"}
  code   명령어                        {"t":"code","text"}
  flow   단계 흐름                     {"t":"flow","steps":[{"title","desc"}]}
  qa     질문·답변                     {"t":"qa","items":[[질문, 답변]]}
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dataset/guides_final
SOURCE = os.path.join(ROOT, 'tools', 'source')

COMPANY = '가상 ICT 기업'
COPYRIGHT = '© 가상 ICT 기업'
VERSION = 'v2.0'
DATE = '2026-10-16'

CATEGORIES = {
    'ACC': '계정·로그인', 'ACS': '접근권한', 'NET': 'VPN·네트워크', 'SW': 'SW·라이선스',
    'HW': 'HW·업무 PC', 'SYS': '사내 시스템', 'SEC': '정보보안', 'STD': '공통 기준', 'AI': 'AI 응대 정책',
}

# 열람 등급
ACCESS_PUBLIC = '사내 일반'
ACCESS_RESTRICTED = '사내 제한'
AUDIENCE = {
    ACCESS_PUBLIC: '전 임직원',
    ACCESS_RESTRICTED: 'IT 운영 담당자·관리자',
}

# 처리 구분 (블록 단위)
SELF = '사용자 직접 조치'
APPLY = '신청·승인 후 처리'
STAFF = 'IT 담당자 처리'
REPORT = '즉시 신고·이관'
HANDLING = [SELF, APPLY, STAFF, REPORT]
HANDLING_DESC = {
    SELF: '안내에 따라 직접 해결합니다. ITssue 챗봇이 절차를 안내합니다.',
    APPLY: '신청서를 내고 팀장 등의 승인을 받은 뒤 담당자가 처리합니다.',
    STAFF: '담당자의 확인이나 작업이 필요합니다. ITssue 챗봇으로 접수합니다.',
    REPORT: '보안 사고나 여러 사람에게 영향이 있는 장애입니다. 혼자 해결하려 하지 말고 바로 알립니다.',
}


def save(doc):
    m = doc['meta']
    d = os.path.join(SOURCE, m['category'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, m['doc_no'] + '.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return p


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def all_sources():
    out = []
    for dp, _, fs in os.walk(SOURCE):
        for f in fs:
            if f.endswith('.json'):
                out.append(os.path.join(dp, f))
    return sorted(out, key=doc_sort_key)


def doc_sort_key(path):
    n = os.path.basename(path)[:-5]
    order = ['STD', 'ACC', 'ACS', 'NET', 'SW', 'HW', 'SYS', 'SEC', 'AI']
    parts = n.split('-')
    cat = parts[1]
    return (order.index(cat) if cat in order else 99, n)


# 간단한 생성 함수
def h(text): return {'t': 'h', 'text': text}
def p(text): return {'t': 'p', 'text': text}
def ul(items): return {'t': 'ul', 'items': list(items)}
def ol(items): return {'t': 'ol', 'items': list(items)}
def kv(rows): return {'t': 'kv', 'rows': [list(r) for r in rows]}
def quote(text): return {'t': 'quote', 'text': text}
def code(text): return {'t': 'code', 'text': text}
def qa(items): return {'t': 'qa', 'items': [list(r) for r in items]}


def table(head, rows, widths=None, badge_col=None):
    d = {'t': 'table', 'head': list(head), 'rows': [list(r) for r in rows]}
    if widths:
        d['widths'] = list(widths)
    if badge_col is not None:
        d['badge_col'] = badge_col
    return d


def cols(*cs):
    return {'t': 'cols', 'cols': [{'title': t, 'items': list(i)} for t, i in cs if i]}


def note(kind, title, lines=()):
    return {'t': 'note', 'kind': kind, 'title': title, 'lines': list(lines)}


def fig(src, caption='', points=(), note_=''):
    d = {'t': 'fig', 'src': src, 'caption': caption}
    if points:
        d['points'] = list(points)
    if note_:
        d['note'] = note_
    return d


def flow(steps):
    return {'t': 'flow', 'steps': [{'title': a, 'desc': b} for a, b in steps]}


def chapter(no, title, items=(), sections=()):
    return {'no': no, 'title': title, 'items': list(items), 'sections': list(sections)}


def section(no, title, props, items):
    return {'no': no, 'title': title, 'props': [list(r) for r in props], 'items': list(items)}


SERIES = {'guide': '임직원 IT 안내', 'manual': 'IT 담당자 매뉴얼', 'standard': 'IT 서비스 기준', 'policy': 'ITssue 운영 정책'}
RESTRICTED_NOTE = {
    'manual': 'IT운영·보안 조직 내부 문서입니다. 사용자에게 문서 자체를 전달하지 않고, 안내는 짝이 되는 임직원용 가이드를 기준으로 합니다.',
    'policy': 'ITssue 서비스 운영 문서입니다. 시스템 프롬프트·응대 정책 관리용이며 임직원 답변용 검색 대상(RAG)에 넣지 않습니다.',
}


def series(m):
    return f"{COMPANY} {SERIES[m['doc_type']]} · {CATEGORIES.get(m['category'], '')}"


CAPTION_PREFIX = re.compile(r'^\s*그림\s*[0-9A-Za-z.\-]+\.?\s*')


def strip_caption_no(c):
    return CAPTION_PREFIX.sub('', c or '').strip()
