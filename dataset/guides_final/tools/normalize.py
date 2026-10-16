"""모든 원천 JSON에 공통 기준을 적용한다. 여러 번 실행해도 결과가 같다.

기준은 IT-STD-002 가이드 분류·작성·열람 기준에 적었다.
  1. 시연·가상 표시 문구를 지운다 ('(가상)', '화면 예시', '교육용 가상 문서' 등)
  2. 회사명·버전·시행일·열람 등급·개정 이력을 맞춘다
  3. '처리 주체'를 '처리 구분' 4가지 값으로 통일한다
  4. 임직원용 가이드의 문의처를 같은 표로 맞춘다
  5. 매뉴얼의 '처리 후 안내 문구'를 인용 상자로 바꾼다
"""
import re
import sys

from model import *

TEXT_RULES = [
    (r'\s*\(가상 명칭\)', ''),
    (r'\s*\(가상\)', ''),
    (r',\s*가상\)', ')'),
    (r'\(가상:\s*', '('),
    (r'\s*\[가상 기준\]', ''),
    (r'한화시스템\s*\(가칭\)', COMPANY),
    (r'HanwhaSystems\s*\(가칭\)', COMPANY),
    (r'HanwhaSystems\s*\(한화시스템\)', COMPANY),
    (r'화면 예시', '화면'),
    (r'예시 화면', '화면'),
    (r'가상 화면', '화면'),
    (r'(현황|\(블루스크린\)) 예시', r'\1'),
    (r'\s*\(그림의 경로는 예시입니다\.?\)', ''),
    (r'IT 서비스 운영 기준\(IT-STD-001\)', 'IT-STD-001 IT 서비스 운영 기준'),
    (r'헬프데스크\(내선 1000\)', 'IT 헬프데스크(내선 1000)'),
    (r'IT IT 헬프데스크', 'IT 헬프데스크'),
    (r'SW 실행·업데이트 오류 가이드', '업무용 SW 실행·오류 대응 가이드'),
    (r'개발서버 접근권한 가이드', '개발·검증 서버 접근권한 가이드'),
    (r'RDY\s*→\s*WIP\s*→\s*FIN(?!\s*→)', 'RDY → IP → FIN → CLS'),
    (r'(?<![A-Za-z])WIP(?![A-Za-z])', 'IP'),
    (r'  +', ' '),
]
DROP_SENTENCE = [
    re.compile(r'[^.]*교육 프로젝트용 가상[^.]*\.\s*'),
    re.compile(r'[^.]*교육용 가상[^.]*\.\s*'),
]

ACTOR = {'신청 후 처리': APPLY, '신청·승인 후 처리': APPLY, '사용자 직접 조치': SELF, 'IT 담당자 처리': STAFF,
         '즉시 신고·이관': REPORT}
# 기본 긴급도가 P1인 시나리오 (전사·대량 장애) → 즉시 신고·이관
P1_SCEN = {'ACC-04', 'NET-03', 'SYS-03', 'SYS-09', 'SYS-16', 'SEC-04'}

GUIDE_CONTACTS = [
    ['ITssue 챗봇', '사내 IT 포털(hanwha-admin) 상단 [챗봇 문의]', '24시간. 모든 IT 문의의 기본 창구입니다. 챗봇이 해결하지 못하면 확인을 거쳐 담당 팀에 티켓으로 접수합니다.'],
    ['IT 헬프데스크 (서비스데스크)', '내선 1000 (평일 09:00~18:00)', 'PC나 챗봇을 쓸 수 없을 때, 여러 사람이 함께 업무를 못 할 때, 본인 확인이 필요한 처리'],
    ['정보보안팀', '내선 1119', '링크 클릭·비밀번호 입력·감염 의심·계정 도용·장비 분실처럼 바로 알려야 할 보안 문제'],
    ['메신저', '#it-helpdesk 채널', '일반 IT 문의 (챗봇을 쓸 수 없을 때)'],
    ['메일', 'it-helpdesk@hanwha-ict.example', '일반 IT 문의. 비밀번호·인증번호는 메일로 보내지 않습니다.'],
    ['처리 상황 알림', '사내 메신저 알림', '접수·담당자 배정·처리 완료를 알려 드립니다. 진행 상황은 [내 요청 현황]에서도 봅니다.'],
]

HISTORY_V2 = '7개 분류 통합 정리본. 문서 양식·열람 등급·용어·연락처를 통일하고 분류 사이의 중복 내용을 한 문서로 정리'


# 번호 끝자리를 읽는 소리에 받침이 있는지 (0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔)
JONG = set('013678M')
PARTICLES = [('을', '를'), ('은', '는'), ('이', '가'), ('과', '와')]


def fix_particles(s):
    """'IT-NET-002 3.7를'처럼 번호 뒤 조사를 받침에 맞춘다."""
    def rep(m):
        num, part = m.group(1), m.group(2)
        last = num[-1]
        for a, b in PARTICLES:
            if part in (a, b):
                return num + (a if last in JONG else b)
        if part in ('으로', '로'):
            return num + ('로' if last in '1278' or last not in JONG else '으로')
        return m.group(0)
    return re.sub(r'((?:IT-[A-Z]+-\d{3}(?:-M)?)(?: \d+\.\d+)?)(으로|을|를|은|는|이|가|과|와|로)(?![가-힣])', rep, s)


def clean(s):
    if not isinstance(s, str):
        return s
    for rx in DROP_SENTENCE:
        s = rx.sub('', s)
    for a, b in TEXT_RULES:
        s = re.sub(a, b, s)
    s = fix_particles(s)
    return s.strip() if s.strip() != s and not s.endswith('\n') else s


def walk(o):
    if isinstance(o, dict):
        if o.get('t') == 'code':
            return o
        return {k: walk(v) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v) for v in o]
    return clean(o)


def norm_meta(doc):
    m = doc['meta']
    m['version'] = VERSION
    m['date'] = DATE
    m['audience'] = AUDIENCE[m['access']]
    if m['doc_type'] == 'manual':
        m['doc_kind'] = '처리 매뉴얼'
    elif m['doc_type'] == 'guide' and not m.get('doc_kind'):
        m['doc_kind'] = '장애 대응'
    hist = [r for r in m.get('history', []) if r]
    if not any(r[0] == VERSION for r in hist):
        hist.append([VERSION, DATE, m['owner'], HISTORY_V2])
    m['history'] = hist


def norm_handling(doc):
    m = doc['meta']
    for ch in doc['chapters']:
        for s in ch['sections']:
            scen = ''
            for r in s['props']:
                if r[0] == '문의 유형':
                    scen = r[1]
                if r[0] in ('처리 주체', '처리 구분'):
                    r[0] = '처리 구분'
                    r[1] = ACTOR.get(r[1], r[1])
                    if m['doc_type'] == 'guide' and any(x.strip() in P1_SCEN for x in scen.split(',')):
                        r[1] = REPORT
        for it in ch['items']:
            if it['t'] == 'table' and ('처리 주체' in it['head'] or '처리 구분' in it['head']):
                c = it['head'].index('처리 주체') if '처리 주체' in it['head'] else it['head'].index('처리 구분')
                it['head'][c] = '처리 구분'
                it['badge_col'] = c
                sc = it['head'].index('문의 유형') if '문의 유형' in it['head'] else None
                for r in it['rows']:
                    r[c] = ACTOR.get(r[c], r[c])
                    if m['doc_type'] == 'guide' and sc is not None and any(x.strip() in P1_SCEN for x in r[sc].split(',')):
                        r[c] = REPORT


def norm_contacts(doc):
    if doc['meta']['doc_type'] != 'guide':
        return
    for ch in doc['chapters']:
        if ch['title'] in ('문의처', '문의 방법') or ch['title'].startswith('문의처'):
            ch['title'] = '문의처'
            extra = [it for it in ch['items'] if it['t'] in ('p', 'note', 'ul')]
            ch['items'] = [table(['창구', '연락처', '이용 기준'], GUIDE_CONTACTS, [2.4, 3.6, 6])] + extra


def norm_quotes(doc):
    for ch in doc['chapters']:
        for s in ch['sections']:
            its = s['items']
            for i in range(len(its) - 1):
                if its[i]['t'] == 'h' and its[i]['text'] == '처리 후 안내 문구' and its[i + 1]['t'] == 'p':
                    its[i + 1] = quote(its[i + 1]['text'].strip().strip('"“”'))


def faq_to_props(doc):
    """항목 끝의 '관련 FAQ: …' 한 줄을 항목 머리 정보로 옮긴다."""
    for ch in doc['chapters']:
        for s in ch['sections']:
            keep = []
            for it in s['items']:
                if it['t'] == 'p' and it['text'].startswith('관련 FAQ:'):
                    v = it['text'].split(':', 1)[1].strip()
                    if v and v != '없음' and not any(k == '관련 FAQ' for k, _ in s['props']):
                        s['props'].append(['관련 FAQ', v])
                    continue
                keep.append(it)
            s['items'] = keep


def norm_appendix(doc):
    for ch in doc['chapters']:
        if ch['no'] == '부록':
            ch['title'] = '관련 문서 · 용어'


def section_index(docs):
    """{(문서 번호, 항목 번호): 처리 구분}"""
    idx = {}
    for doc in docs:
        for ch in doc['chapters']:
            for s in ch['sections']:
                for k, v in s['props']:
                    if k == '처리 구분':
                        idx[(doc['meta']['doc_no'], s['no'])] = v
    return idx


def sync_titles(doc, titles):
    """'관련 문서' 표의 문서명을 실제 문서명과 맞춘다."""
    for ch in doc['chapters']:
        for it in ch['items']:
            if it['t'] == 'table' and it['head'][:2] == ['문서 번호', '문서명']:
                for r in it['rows']:
                    if r[0] in titles:
                        r[1] = titles[r[0]]


def sync_quickmap(doc, idx):
    """'증상별 바로가기' 표의 처리 구분을 가리키는 항목의 값과 맞춘다."""
    me = doc['meta']['doc_no']
    for ch in doc['chapters']:
        for it in ch['items']:
            if it['t'] != 'table' or '볼 곳' not in it['head'] or '처리 구분' not in it['head']:
                continue
            a, c = it['head'].index('볼 곳'), it['head'].index('처리 구분')
            for r in it['rows']:
                ref = r[a].strip()
                m = re.match(r'^(IT-[A-Z]+-\d+(?:-M)?)?\s*(\d+\.\d+)?$', ref)
                if not m:
                    continue
                key = (m.group(1) or me, m.group(2))
                if key[1] and key in idx:
                    r[c] = idx[key]


def run(path):
    doc = walk(load(path))
    norm_meta(doc)
    norm_handling(doc)
    norm_contacts(doc)
    norm_quotes(doc)
    norm_appendix(doc)
    faq_to_props(doc)
    save(doc)


if __name__ == '__main__':
    paths = sys.argv[1:] or all_sources()
    for p_ in paths:
        run(p_)
    docs = [load(p_) for p_ in all_sources()]
    idx = section_index(docs)
    titles = {d['meta']['doc_no']: d['meta']['title'] for d in docs}
    for doc in docs:
        sync_quickmap(doc, idx)
        sync_titles(doc, titles)
        save(doc)
    print(len(paths), 'normalized')
