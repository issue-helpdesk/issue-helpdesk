"""콘텐츠 사양(content_*.py) → docx 페이지 배치.

장 번호는 팀 템플릿(NET·HW 문서)과 같다.
  사용자 가이드: 1 개요 / 2 먼저 확인할 사항 / 3 증상별 조치 방법(3.x 블록) / 4 자주 묻는 질문 / 5 주의사항 / 6 문의처 / 부록
  담당자 매뉴얼: 1 개요 / 2 접수·분류 기준 / 3 증상별 처리 절차(3.x 블록) / 4 대형 장애 대응 / 5 처리 기록 기준 / 부록
"""
import os
from docx.shared import Cm
from build import Builder, BODY_W, LEVEL

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.normpath(os.path.join(HERE, '..', 'images'))
UI_NOTE = '※ 화면은 가상 예시이며 실제 프로그램 버전에 따라 다를 수 있습니다.'


def img(name):
    return os.path.join(IMG, name)


LEVEL_LEGEND = [
    ['red', '보안 사고 가능성이 있어 정보보안팀에 바로 신고·이관합니다. 혼자 해결하려고 하지 않습니다.'],
    ['yellow', '조건에 따라 담당자 확인이나 팀장·정보보안팀 승인이 필요합니다.'],
    ['green', '안내에 따라 직접 조치할 수 있습니다. ITssue 챗봇이 절차를 안내합니다.'],
]


def guide(D, toc=None):
    m = D['meta']
    b = Builder(m)
    b.toc_pages = toc or {}
    crumb3 = '03. 증상별 조치 방법'

    b.cover()
    b.info_page(D['info'], D.get('info_note'))
    b.contents([
        ('1. 개요', 'c1'), ('2. 먼저 확인할 사항', 'c2'), ('3. 증상별 조치 방법', 'c3'),
        ('4. 자주 묻는 질문', 'c4'), ('5. 주의사항', 'c5'), ('6. 문의처', 'c6'), ('부록', 'c7')])

    # 1. 개요
    b.divider('01', '개요', 'c1')
    b.page_header('개요', '01. 개요')
    o = D['overview']
    b.cards([('목적', o['purpose']), ('적용 대상', o['scope']), ('적용 환경', o['env'])], height=Cm(6.2))
    b.label('처리 구분 표시', before=2)
    b.table(['처리 구분', '뜻'], LEVEL_LEGEND, [6.5, 23.6], level_col=0, first_col_fill=False)

    # 2. 먼저 확인할 사항
    b.divider('02', '먼저 확인할 사항', 'c2')
    b.page_header('먼저 확인할 사항', '02. 먼저 확인할 사항')
    b.label('조치하기 전에 확인합니다')
    b.bullets(D['precheck'])
    if D.get('precheck_warn'):
        b.spacer(2)
        b.callout(D['precheck_warn'], 'warn')
    if D.get('check_table'):
        lab, heads, rows_, widths = D['check_table']
        b.page_header('먼저 확인할 사항', '02. 먼저 확인할 사항')
        b.label(lab)
        b.table(heads, rows_, widths)
    b.page_header('먼저 확인할 사항', '02. 먼저 확인할 사항')
    b.label('증상별 바로가기')
    b.table(['겪고 있는 증상', '볼 곳', '처리 구분'], D['quickmap'], [17.5, 6.5, 6.1], center_cols=(1,), level_col=2)

    # 3. 증상별 조치 방법
    b.divider('03', '증상별 조치 방법', 'c3')
    b.page_header('증상별 조치 방법', crumb3)
    b.label('항목 목록')
    rows = [[x['no'], x['title'], x['scenario'], x['actor'], x['level'], x['team']] for x in D['blocks']]
    b.table(['번호', '제목', '문의 유형', '처리 주체', '처리 구분', '담당 부서'], rows,
            [1.8, 12.6, 2.6, 4.3, 5.0, 3.8], center_cols=(0, 2), level_col=4)
    for x in D['blocks']:
        _guide_block(b, x, crumb3)

    # 4. 자주 묻는 질문
    b.divider('04', '자주 묻는 질문', 'c4')
    b.page_header('자주 묻는 질문', '04. 자주 묻는 질문')
    b.table(['질문', '답변'], [[q, a] for q, a in D['faq']], [10.5, 19.6])

    # 5. 주의사항
    b.divider('05', '주의사항', 'c5')
    b.page_header('주의사항', '05. 주의사항')
    b.callout(['★ 꼭 지켜 주세요'] + D['cautions_star'], 'warn')
    b.bullets(D['cautions'])

    # 6. 문의처
    b.divider('06', '문의처', 'c6')
    b.page_header('문의처', '06. 문의처')
    b.table(['창구', '연락처', '이용 기준'], D['contacts'], [6.0, 9.5, 14.6])
    if D.get('contacts_note'):
        b.spacer(2)
        b.callout(D['contacts_note'], 'note')

    # 부록
    b.divider('부록', '관련 문서 · 용어 · 개정 이력', 'c7')
    b.page_header('부록', '부록')
    b.label('관련 문서')
    b.table(['문서 번호', '문서명', '이럴 때 봅니다'], D['related'], [4.6, 11.0, 14.5], center_cols=(0,))
    b.page_header('부록', '부록')
    b.label('용어')
    b.table(['용어', '설명'], D['terms'], [6.5, 23.6])
    b.page_header('부록', '부록')
    b.label('개정 이력')
    b.table(['버전', '개정일', '작성자', '변경 내용'], D['history'], [3, 4, 5, 18.1], center_cols=(0, 1, 2))
    return b


def _guide_block(b, x, crumb):
    tag = f"[{x['platform']}] " if x.get('platform') else ''
    # A: 상황·원인·조치 + 화면
    b.page_header(f'{tag}증상별 조치 방법', crumb, UI_NOTE if x.get('fig') else None)
    b.h2(f"{x['no']} {x['title']}")
    b.badges([('문의 유형', x['scenario']), ('처리 주체', x['actor']), ('담당 부서', x['team']), ('처리 구분', x['level'])])
    if x.get('fig'):
        L, R = b.two_col(x.get('fig_w', 15.0))
        b.figure(img(x['fig']), x.get('fig_w', 15.0), L, x.get('fig_caption'))
        target = R
    else:
        target = None
    b.label('이런 경우', target, before=0)
    b.bullets(x['cases'], target, size=10.5)
    if x.get('message'):
        b.line(f"화면 메시지: {x['message']}", target, size=10, color='5B6573', indent=0.2)
    b.label('원인', target)
    b.bullets(x['causes'], target, size=10.5)
    b.label('조치 방법', target)
    b.steps(x['steps'], target, size=10.5)
    # B: 확인·문의
    b.page_header(f'{tag}증상별 조치 방법', crumb)
    b.h2(f"{x['no']} {x['title']} — 확인과 문의")
    b.cards([('해결 확인', [x['resolved']]), ('해결되지 않으면', x['unresolved']), ('문의 시 알려 주실 정보', x['info'])],
            size=10.5, height=Cm(5.2))
    if x.get('warn'):
        b.callout(x['warn'], 'warn', size=10.5)
    if x.get('note'):
        b.callout(x['note'], 'note', size=10.5)
    if x.get('faq'):
        b.line(f"관련 FAQ: {x['faq']}", size=10, color='5B6573')


def manual(D, toc=None):
    m = D['meta']
    b = Builder(m)
    b.toc_pages = toc or {}
    crumb3 = '03. 증상별 처리 절차'
    b.cover()
    b.info_page(D['info'], '※ 이 문서는 IT운영·보안 조직 내부 문서입니다. 사용자에게 문서 자체를 전달하지 않습니다.')
    b.contents([
        ('1. 개요', 'c1'), ('2. 접수·분류 기준', 'c2'), ('3. 증상별 처리 절차', 'c3'),
        ('4. 대형 장애 대응', 'c4'), ('5. 처리 기록 기준', 'c5'), ('부록', 'c6')])

    b.divider('01', '개요', 'c1')
    b.page_header('개요', '01. 개요')
    b.label('목적')
    b.line(D['purpose'], size=11)
    b.label('담당 범위')
    b.table(['구분', '내용'], D['scope'], [5.0, 25.1])

    b.divider('02', '접수·분류 기준', 'c2')
    b.page_header('접수·분류 기준', '02. 접수·분류 기준')
    b.line('사용자 가이드의 블록별 기본값이다. 긴급도 기준은 IT 서비스 운영 기준(IT-STD-001)을 따른다.', size=10.5, color='5B6573')
    rows = [[x['no'], x['scenario'], x['title'], x['urgency'], x['first'], x['method'], x['to']] for x in D['blocks']]
    b.table(['번호', '문의 유형', '증상·요청', '기본 긴급도', '1차 처리', '처리 방식', '이관 대상'], rows,
            [1.7, 2.4, 10.6, 2.6, 3.4, 5.4, 4.0], center_cols=(0, 1, 3), size=9.5)
    b.page_header('접수·분류 기준', '02. 접수·분류 기준')
    b.cards([('처리 방식', D['methods']), ('긴급도 조정 조건', D['urgency_rules'])], size=10.5, height=Cm(9))
    if D.get('flow_fig'):
        b.page_header('접수·분류 기준', '02. 접수·분류 기준', UI_NOTE)
        b.label('처리 흐름')
        b.figure(img(D['flow_fig']), 26, caption=D.get('flow_caption'))

    b.divider('03', '증상별 처리 절차', 'c3')
    for x in D['blocks']:
        _manual_block(b, x, crumb3)

    b.divider('04', '대형 장애 대응', 'c4')
    b.page_header('대형 장애 대응', '04. 대형 장애 대응')
    b.bullets(D['major'], mark='·')
    if D.get('major_warn'):
        b.spacer(2)
        b.callout(D['major_warn'], 'warn')

    b.divider('05', '처리 기록 기준', 'c5')
    b.page_header('처리 기록 기준', '05. 처리 기록 기준')
    b.line('처리 완료(FIN) 시 티켓에 아래 항목을 남긴다. 반복되는 건은 사용자 가이드 반영 여부를 검토한다.', size=10.5)
    b.table(['항목', '기록 내용'], D['records'], [6.0, 24.1])

    b.divider('부록', '내부 연락처 · 개정 이력', 'c6')
    b.page_header('부록', '부록')
    b.label('내부 연락처')
    b.table(['담당', '연락처', '비고'], D['contacts'], [7.0, 7.0, 16.1])
    b.label('개정 이력')
    b.table(['버전', '개정일', '작성자', '변경 내용'], D['history'], [3, 4, 5, 18.1], center_cols=(0, 1, 2))
    return b


def _manual_block(b, x, crumb):
    b.page_header('증상별 처리 절차', crumb)
    b.h2(f"{x['no']} {x['title']}")
    b.badges([('문의 유형', x['scenario']), ('기본 긴급도', x['urgency']), ('1차 처리', x['first']), ('이관 대상', x['to'])])
    b.cards([('접수 시 확인 질문', x['questions']), ('판단 기준', x['criteria'])], size=10.5, height=Cm(9.2))
    b.page_header('증상별 처리 절차', crumb, UI_NOTE if x.get('fig') else None)
    b.h2(f"{x['no']} {x['title']} — 처리 절차")
    if x.get('fig'):
        L, R = b.two_col(x.get('fig_w', 14.5))
        b.figure(img(x['fig']), x.get('fig_w', 14.5), L, x.get('fig_caption'))
        b.steps(x['procedure'], R, size=10.5)
    else:
        b.steps(x['procedure'], size=10.5)
    b.page_header('증상별 처리 절차', crumb)
    b.h2(f"{x['no']} {x['title']} — 안내·기록")
    b.label('처리 후 안내 문구', before=0)
    b.callout([x['reply']], 'ok', size=10.5)
    b.cards([('재발 방지', x['prevention']), ('이관 시 전달 정보', x['handover'])], size=10.5, height=Cm(5))
    if x.get('warn'):
        b.callout(x['warn'], 'warn', size=10.5)
    if x.get('table'):
        lab, heads, rows, widths = x['table']
        b.page_header('증상별 처리 절차', crumb)
        b.h2(f"{x['no']} {x['title']} — {lab}")
        b.table(heads, rows, widths, size=9.5)
