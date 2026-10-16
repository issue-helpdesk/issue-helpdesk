"""직접 작성하는 문서(SW·ACS·공통 기준·정책)의 공통 틀.

ACC·SEC·HW·NET·SYS 변환본과 같은 장 구성을 만든다.
  임직원용 가이드: 1 개요 / 2 먼저 확인할 사항 / 3 항목별 안내 / 4 자주 묻는 질문 / 5 주의사항 / 6 문의처 / 부록
  담당자용 매뉴얼: 1 개요 / 2 접수·분류 기준 / 3 항목별 처리 절차 / 4 대형 장애 대응 / 5 처리 기록 기준 / 6 연락처
"""
from model import *

RECORDS = [
    ['원인', '확인된 원인 한 줄'],
    ['조치 내용', '실제로 한 조치. 안내만으로 끝낸 건은 앞에 [즉시 처리]'],
    ['재발 방지', '같은 문의를 줄이기 위한 조치 (없으면 빈칸)'],
    ['관련 FAQ', '안내에 쓴 FAQ 번호'],
    ['가이드 반영', '임직원용 가이드에 추가·수정이 필요한지 (필요 / 불필요)'],
]
METHODS = [
    '즉시 처리: 안내만으로 끝낸 건. 티켓 없이 상담 기록만 남긴다.',
    '티켓: 담당자 조치가 필요한 건. 담당 팀에 배정하고 상태를 RDY → IP → FIN → CLS 로 관리한다. FIN은 담당자 처리 완료, CLS는 문의자가 해결을 확인한 최종 종료다.',
]


def gsec(no, title, scen, handling, team, cases=(), causes=(), steps=(), steps_title='조치 방법',
         figs=(), resolved=(), unresolved=(), info=(), extra=(), before=(), faq='', period=None):
    """임직원용 가이드의 항목 하나."""
    items = list(before)
    if cases:
        items += [h('이런 경우' if steps_title == '조치 방법' else '이럴 때 신청합니다'), ul(cases)]
    if causes:
        items += [h('원인'), ul(causes)]
    if steps:
        items += [h(steps_title), ol(steps)]
    items += list(figs)
    items += list(extra)
    cs = []
    if resolved:
        cs.append(('해결 확인' if steps_title == '조치 방법' else '처리 기간과 결과 확인', list(resolved)))
    if unresolved:
        cs.append(('해결되지 않으면' if steps_title == '조치 방법' else '반려·보완되는 경우', list(unresolved)))
    if info:
        cs.append(('문의 시 알려 주실 정보', list(info)))
    if cs:
        items.append(cols(*cs))
    if faq:
        items.append(p('관련 FAQ: ' + faq))
    props = [['문의 유형', scen], ['처리 구분', handling], ['담당 부서', team]]
    if period:
        props.append(['처리 기간', period])
    return section(no, title, props, items)


def guide(meta, purpose, scope, env, ch2_items, sections, faq, cautions_star, cautions, related, terms,
          ch2_title='먼저 확인할 사항', ch3_title='증상별 조치 방법'):
    idx = [[s['no'], s['title'], dict(s['props'])['문의 유형'], dict(s['props'])['처리 구분'], dict(s['props'])['담당 부서']]
           for s in sections]
    chs = [
        chapter('1', '개요', [cols(('목적', purpose), ('적용 대상', scope), ('적용 환경', env))]),
        chapter('2', ch2_title, ch2_items),
        chapter('3', ch3_title, [table(['번호', '제목', '문의 유형', '처리 구분', '담당 부서'], idx, [1, 7, 1.6, 2.4, 2], badge_col=3)], sections),
        chapter('4', '자주 묻는 질문', [qa(faq)]),
        chapter('5', '주의사항', [note('star', '꼭 지켜 주세요', cautions_star), ul(cautions)]),
        chapter('6', '문의처', []),
        chapter('부록', '관련 문서 · 용어', [h('관련 문서'), table(['문서 번호', '문서명', '이럴 때 봅니다'], related, [2, 4.5, 5.5]),
                                         h('용어'), table(['용어', '설명'], terms, [3, 9])]),
    ]
    meta = dict(meta)
    meta.setdefault('doc_type', 'guide')
    meta.setdefault('access', ACCESS_PUBLIC)
    meta.setdefault('target', '전 임직원')
    return {'meta': meta, 'chapters': chs}


def msec(no, title, scen, urgency, first, method, to, questions, criteria, procedure, reply,
         prevention=('없음',), handover=('없음',), extra=(), figs=(), warn=None):
    items = [cols(('접수 시 확인 질문', list(questions)), ('판단 기준', list(criteria))), h('처리 절차'), ol(procedure)]
    items += list(figs)
    items += list(extra)
    items += [h('처리 후 안내 문구'), quote(reply), cols(('재발 방지', list(prevention)), ('이관 시 전달 정보', list(handover)))]
    if warn:
        items.append(note('star', warn[0], warn[1:]))
    return section(no, title, [['문의 유형', scen], ['기본 긴급도', urgency], ['1차 처리', first], ['처리 방식', method], ['이관 대상', to]], items)


def manual(meta, purpose, scope, urgency_rules, sections, major, contacts, extra2=(), records=RECORDS, methods=METHODS):
    idx = [[s['no'], dict(s['props'])['문의 유형'], s['title'], dict(s['props'])['기본 긴급도'], dict(s['props'])['1차 처리'],
            dict(s['props'])['처리 방식'], dict(s['props'])['이관 대상']] for s in sections]
    chs = [
        chapter('1', '개요', [h('목적'), p(purpose), h('담당 범위'), kv(scope)]),
        chapter('2', '접수·분류 기준', [p('임직원용 가이드의 항목별 기본값입니다. 긴급도 기준은 IT-STD-001 IT 서비스 운영 기준을 따릅니다.'),
                                   table(['번호', '문의 유형', '증상·요청', '기본 긴급도', '1차 처리', '처리 방식', '이관 대상'], idx,
                                         [0.8, 1.3, 4.6, 1.2, 1.7, 2.6, 2]),
                                   h('처리 방식'), ul(methods), h('긴급도 조정 조건'), ul(urgency_rules)] + list(extra2)),
        chapter('3', '증상별 처리 절차', [], sections),
        chapter('4', '대형 장애 대응', [ul(major)]),
        chapter('5', '처리 기록 기준', [p('티켓을 종료(FIN)할 때 아래 항목을 남깁니다.'), table(['항목', '적는 내용'], records, [2.5, 9])]),
        chapter('6', '연락처', [table(['담당', '연락처', '이럴 때'], contacts, [3, 3, 6])]),
    ]
    meta = dict(meta)
    meta.setdefault('doc_type', 'manual')
    meta.setdefault('access', ACCESS_RESTRICTED)
    return {'meta': meta, 'chapters': chs}


def hist(owner, first='2026-10-06', note_='최초 작성'):
    return [['v1.0', first, owner, note_]]
