"""ACC·SEC 원본(dataset/guides/{ACC,SEC}/tools/content_00x.py)을 공통 모델로 옮긴다.

한 번만 실행하는 변환 스크립트다. 결과 JSON은 tools/source/ 에 쓰고, 이후 수정은 JSON에서 한다.
"""
import importlib
import os
import shutil
import sys

from model import *

SRC_ROOT = os.path.join(os.path.dirname(ROOT), 'guides')
LEVEL = {'red': REPORT}


def handling(actor, level):
    if level == 'red':
        return REPORT
    return {'신청 후 처리': APPLY, '신청·승인 후 처리': APPLY}.get(actor, actor)


def info_dict(rows):
    return {k: v for k, v in rows}


def split_list(s):
    return [x.strip() for x in s.split(',') if x.strip()] if s else []


def copy_fig(cat, name):
    if not name:
        return None
    src = os.path.join(SRC_ROOT, cat, 'images', name)
    dst_dir = os.path.join(ROOT, cat, 'images')
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dst_dir, name))
    return name


def guide_doc(cat, G):
    info = info_dict(G['info'])
    m = G['meta']
    meta = {
        'doc_no': m['doc_no'], 'title': m['title'], 'category': cat, 'doc_type': 'guide',
        'access': ACCESS_PUBLIC, 'owner': m['owner'], 'approver': info.get('승인자', ''),
        'pair': info.get('담당자 매뉴얼', ''), 'doc_kind': info.get('문서 유형', ''),
        'target': info.get('대상', '전 임직원'),
        'scenarios': split_list(info.get('포함 시나리오', '')),
        'keywords': split_list(info.get('키워드', '')),
        'history': G['history'],
    }
    ov = G['overview']
    ch1 = chapter('1', '개요', [cols(('목적', ov['purpose']), ('적용 대상', ov['scope']), ('적용 환경', ov['env']))])
    if G.get('info_note'):
        ch1['items'].append(note('info', G['info_note'].lstrip('※ ').strip()))

    items2 = [h('조치하기 전에 확인합니다'), ul(G['precheck'])]
    if G.get('precheck_warn'):
        w = G['precheck_warn']
        items2.append(note('star', w[0].lstrip('★ ').strip(), w[1:]))
    if G.get('check_table'):
        title, head, rows = G['check_table'][:3]
        items2 += [h(title), table(head, rows)]
    qm = [[a, b, handling('', c) if c == 'red' else {'green': SELF, 'yellow': APPLY}.get(c, c)] for a, b, c in G['quickmap']]
    items2 += [h('증상별 바로가기'), table(['겪고 있는 증상', '볼 곳', '처리 구분'], qm, [6, 2, 2.6], badge_col=2)]
    ch2 = chapter('2', '먼저 확인할 사항', items2)

    idx_rows, secs = [], []
    for b in G['blocks']:
        hd = handling(b['actor'], b.get('level'))
        idx_rows.append([b['no'], b['title'], b['scenario'], hd, b['team']])
        items = [h('이런 경우'), ul(b['cases']), h('원인'), ul(b['causes']), h('조치 방법'), ol(b['steps'])]
        if b.get('fig'):
            items.append(fig(copy_fig(cat, b['fig']), strip_caption_no(b.get('fig_caption', ''))))
        items.append(cols(('해결 확인', [b['resolved']] if isinstance(b['resolved'], str) else b['resolved']),
                          ('해결되지 않으면', b['unresolved']), ('문의 시 알려 주실 정보', b['info'])))
        for w in [b.get('warn')] if b.get('warn') else []:
            items.append(note('star', w[0].lstrip('★ ').strip(), w[1:]))
        for n in b.get('note') or []:
            items.append(note('info', n.lstrip('※ ').strip()))
        if b.get('faq'):
            items.append(p('관련 FAQ: ' + b['faq']))
        secs.append(section(b['no'], b['title'], [['문의 유형', b['scenario']], ['처리 구분', hd], ['담당 부서', b['team']]], items))
    ch3 = chapter('3', '증상별 조치 방법', [table(['번호', '제목', '문의 유형', '처리 구분', '담당 부서'], idx_rows, [1, 7, 1.6, 2.4, 2], badge_col=3)], secs)

    ch4 = chapter('4', '자주 묻는 질문', [qa(G['faq'])])
    items5 = []
    if G.get('cautions_star'):
        items5.append(note('star', '꼭 지켜 주세요', G['cautions_star']))
    items5.append(ul(G.get('cautions', [])))
    ch5 = chapter('5', '주의사항', items5)
    ch6 = chapter('6', '문의처', [table(['창구', '연락처', '이용 기준'], G['contacts'], [2.4, 3, 6])])
    app = chapter('부록', '관련 문서 · 용어 · 개정 이력', [
        h('관련 문서'), table(['문서 번호', '문서명', '이럴 때 봅니다'], G['related'], [2, 4.5, 5.5]),
        h('용어'), table(['용어', '설명'], G['terms'], [3, 9]),
    ])
    return {'meta': meta, 'chapters': [ch1, ch2, ch3, ch4, ch5, ch6, app]}


def manual_doc(cat, M):
    info = info_dict(M['info'])
    m = M['meta']
    meta = {
        'doc_no': m['doc_no'], 'title': m['title'], 'category': cat, 'doc_type': 'manual',
        'access': ACCESS_RESTRICTED, 'owner': m['owner'], 'approver': info.get('승인자', ''),
        'pair': info.get('대상 사용자 가이드', ''), 'readers': info.get('열람 대상', ''),
        'scenarios': split_list(info.get('포함 시나리오', '')),
        'faqs': split_list(info.get('관련 FAQ', '')),
        'history': M['history'],
    }
    ch1 = chapter('1', '개요', [h('목적'), p(M['purpose']), h('담당 범위'), kv(M['scope'])])
    idx = [[b['no'], b['scenario'], b['title'], b['urgency'], b['first'], b['method'], b['to']] for b in M['blocks']]
    items2 = [p('사용자 가이드의 항목별 기본값입니다. 긴급도 기준은 IT-STD-001 IT 서비스 운영 기준을 따릅니다.'),
              table(['번호', '문의 유형', '증상·요청', '기본 긴급도', '1차 처리', '처리 방식', '이관 대상'], idx, [0.8, 1.3, 4.6, 1.2, 1.7, 2.6, 2]),
              h('처리 방식'), ul(M['methods']), h('긴급도 조정 조건'), ul(M['urgency_rules'])]
    for ex in M.get('extra2', []) or []:
        title, head, rows = ex[0], ex[1], ex[2]
        items2 += [h(title), table(head, rows)]
    if M.get('flow_fig'):
        items2 += [h('처리 흐름'), fig(copy_fig(cat, M['flow_fig']), strip_caption_no(M.get('flow_caption', '')))]
    ch2 = chapter('2', '접수·분류 기준', items2)
    secs = []
    for b in M['blocks']:
        items = [cols(('접수 시 확인 질문', b['questions']), ('판단 기준', b['criteria'])), h('처리 절차'), ol(b['procedure'])]
        if b.get('table'):
            t = b['table']
            items += [h(t[0]), table(t[1], t[2])]
        if b.get('fig'):
            items.append(fig(copy_fig(cat, b['fig']), strip_caption_no(b.get('fig_caption', ''))))
        items += [h('처리 후 안내 문구'), quote(b['reply']), cols(('재발 방지', b['prevention']), ('이관 시 전달 정보', b['handover']))]
        if b.get('warn'):
            w = b['warn']
            items.append(note('star', w[0].lstrip('★ ').strip(), w[1:]))
        secs.append(section(b['no'], b['title'], [['문의 유형', b['scenario']], ['기본 긴급도', b['urgency']], ['1차 처리', b['first']],
                                                   ['처리 방식', b['method']], ['이관 대상', b['to']]], items))
    ch3 = chapter('3', '증상별 처리 절차', [], secs)
    items4 = [ul(M['major'])]
    if M.get('major_warn'):
        w = M['major_warn']
        items4.append(note('star', w[0].lstrip('★ ').strip(), w[1:]))
    ch4 = chapter('4', '대형 장애 대응', items4)
    ch5 = chapter('5', '처리 기록 기준', [p('티켓을 종료할 때 아래 항목을 남깁니다.'), table(['항목', '적는 내용'], M['records'], [2.5, 9])])
    ch6 = chapter('6', '연락처', [table(['담당', '연락처', '이럴 때'], M['contacts'], [3, 3, 6])])
    return {'meta': meta, 'chapters': [ch1, ch2, ch3, ch4, ch5, ch6]}


def main():
    for cat, nums in [('ACC', ['001', '002', '003']), ('SEC', ['001', '002', '003', '004'])]:
        tools = os.path.join(SRC_ROOT, cat, 'tools')
        sys.path.insert(0, tools)
        for n in nums:
            for mod in ('common', f'content_{n}'):
                sys.modules.pop(mod, None)
            c = importlib.import_module(f'content_{n}')
            print(save(guide_doc(cat, c.GUIDE)))
            print(save(manual_doc(cat, c.MANUAL)))
        sys.path.remove(tools)


if __name__ == '__main__':
    main()
