"""SEC 가이드·매뉴얼 그림 생성. python figs.py → ../images/*.png

모든 화면은 설명용 가상 화면이다. 주소·이름·번호는 모두 가상 값이다.
"""
import os
from figlib import (Canvas, flow, font, NAVY, TEXT, GREY, LIGHT, LINE, RED, ORANGE, WHITE, BG, BLUE,
                    GREEN, AMBER, PINK)

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'images'))
os.makedirs(OUT, exist_ok=True)
FIGS = {}


def fig(name):
    def deco(fn):
        FIGS[name] = fn
        return fn
    return deco


def P(name):
    return os.path.join(OUT, name)


# ---------------- 공통 부품 ----------------
def mail_window(c, box, subject, sender, addr, when, body_lines, toolbar=('답장', '전달', '삭제', '피싱 신고'), title='그룹웨어 메일'):
    x0, y0, x1, y1 = c.window(box, title)
    # 폴더
    c.rect((x0, y0, x0 + 190, y1), LIGHT, LIGHT, 1, 6)
    for i, f in enumerate(['받은편지함', '보낸편지함', '스팸(격리)함', '휴지통']):
        c.text((x0 + 18, y0 + 30 + i * 46), f, 19, NAVY if i == 0 else GREY, i == 0, 'lm')
    mx = x0 + 214
    # 도구 모음
    bx = mx
    boxes = {}
    for t in toolbar:
        kind = 'danger' if t == '피싱 신고' else 'plain'
        b = c.button((bx, y0), t, kind, 18, (16, 8))
        boxes[t] = b
        bx = b[2] + 10
    c.text((mx, y0 + 76), subject, 24, TEXT, True, 'lm')
    c.text((mx, y0 + 116), '보낸 사람', 18, GREY, False, 'lm')
    c.text((mx + 96, y0 + 116), f'{sender} <{addr}>', 19, TEXT, False, 'lm')
    sb = (mx + 96 + c.d.textlength(f'{sender} <', font=font(19)), y0 + 102,
          mx + 96 + c.d.textlength(f'{sender} <{addr}', font=font(19)), y0 + 130)
    boxes['addr'] = sb
    c.text((mx, y0 + 150), '받은 시각', 18, GREY, False, 'lm')
    c.text((mx + 96, y0 + 150), when, 19, TEXT, False, 'lm')
    c.d.line((mx, y0 + 176, x1, y0 + 176), fill=LINE, width=2)
    y = y0 + 200
    for ln in body_lines:
        if isinstance(ln, tuple) and ln[0] == 'button':
            b = c.button((mx, y), ln[1], 'primary', 20)
            boxes['link'] = b
            y = b[3] + 18
        elif isinstance(ln, tuple) and ln[0] == 'attach':
            b = (mx, y, mx + 420, y + 50)
            c.rect(b, BG, LINE, 2, 6)
            c.text((mx + 16, y + 25), '[첨부] ' + ln[1], 19, TEXT, False, 'lm')
            boxes['attach'] = b
            y = b[3] + 18
        else:
            y_start = y
            y = c.wrap((mx, y), ln, x1 - mx - 10, 20, TEXT) + 6
            boxes.setdefault('lines', []).append((mx, y_start - 4, mx + c.d.textlength(ln, font=font(20)), y - 8))
    boxes['body_end'] = y
    boxes['mx'] = mx
    return boxes


def console(c, box, title, menu, active):
    x0, y0, x1, y1 = c.window(box, title)
    c.rect((x0, y0, x0 + 210, y1), LIGHT, LIGHT, 1, 6)
    for i, m in enumerate(menu):
        on = (i == active)
        if on:
            c.rect((x0 + 8, y0 + 12 + i * 50, x0 + 202, y0 + 52 + i * 50), WHITE, NAVY, 2, 6)
        c.text((x0 + 22, y0 + 32 + i * 50), m, 19, NAVY if on else GREY, on, 'lm')
    return (x0 + 236, y0, x1, y1)


def dialog(c, box, title, lines, buttons):
    x0, y0, x1, y1 = box
    c.d.rounded_rectangle((x0 + 8, y0 + 10, x1 + 8, y1 + 10), 12, fill=(200, 205, 212))
    c.rect(box, WHITE, NAVY, 3, 12)
    c.text((x0 + 26, y0 + 40), title, 23, NAVY, True, 'lm')
    y = y0 + 76
    for ln in lines:
        y = c.wrap((x0 + 26, y), ln, x1 - x0 - 52, 19, TEXT) + 4
    bx = x1 - 26
    res = {}
    for label, kind in reversed(buttons):
        w = c.d.textlength(label, font=font(20, True)) + 44
        b = c.button((bx - w, y1 - 70), label, kind, 20)
        res[label] = b
        bx = b[0] - 12
    return res


# ---------------- IT-SEC-001 ----------------
@fig('sec001_31_report.png')
def _():
    c = Canvas(1400, 860)
    bx = mail_window(c, (30, 30, 1370, 830), '[급여명세서 확인] 10월 급여명세서가 도착했습니다', '급여 담당',
                     'payroll@hanvva-ict.example', '2026-10-15 09:12',
                     ['10월 급여명세서가 발급되었습니다. 아래 버튼을 눌러 본인 확인 후 명세서를 확인하세요.',
                      '확인하지 않으면 명세서가 오늘 18:00에 자동 삭제됩니다.', ('button', '명세서 확인하기')])
    c.mark(bx['addr'], 1, 'right', 4)
    c.mark(bx['피싱 신고'], 2, 'right')
    d = dialog(c, (760, 470, 1340, 760), '피싱 신고', ['이 메일을 정보보안팀에 신고합니다.', '신고한 메일은 받은편지함에서 사라집니다.'],
               [('취소', 'plain'), ('신고', 'danger')])
    c.mark(d['신고'], 3, 'top')
    c.save(P('sec001_31_report.png'))


@fig('sec001_32_bec.png')
def _():
    c = Canvas(1400, 860)
    bx = mail_window(c, (30, 30, 1370, 830), '급히 부탁드립니다', '대표이사', 'ceo.office@freemail.example', '2026-10-15 13:40',
                     ['회의 중이라 전화를 받기 어렵습니다.', '거래처 선물용으로 기프트카드 10장을 구매해 카드 번호를 이 메일로 회신해 주세요.',
                      '다른 사람에게는 말하지 말고 오늘 안에 처리 부탁합니다.'])
    c.mark(bx['addr'], 1, 'right', 4)
    l1, l2 = bx['lines'][1], bx['lines'][2]
    c.mark((l1[0], l1[1], max(l1[2], l2[2]), l2[3]), 2, 'right')
    c.banner((bx['mx'], 560, 1340, 650), '확인 방법: 메일에 회신하지 말고, 사내 메신저나 그룹웨어 조직도의 번호로 요청한 본인에게 직접 확인합니다.', 'info', 20)
    c.save(P('sec001_32_bec.png'))


@fig('sec001_33_link.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 930, 830), '웹 브라우저')
    addr = (x0, y0, x1, y0 + 46)
    c.rect(addr, BG, LINE, 2, 20)
    c.text((x0 + 20, y0 + 23), '[주의 요함]   hanwha-ict-login.example.top/sso/verify', 19, RED, False, 'lm')
    c.mark(addr, 1, 'bottom', 4)
    c.rect((x0 + 150, y0 + 150, x1 - 150, y1 - 60), WHITE, LINE, 2, 10)
    c.text(((x0 + x1) / 2, y0 + 210), '통합 로그인', 30, NAVY, True, 'mm')
    c.text(((x0 + x1) / 2, y0 + 254), '명세서를 보려면 다시 로그인하세요', 19, GREY, False, 'mm')
    c.field((x0 + 190, y0 + 300), 340, '사번', '', 19, 110)
    c.field((x0 + 190, y0 + 364), 340, '비밀번호', '', 19, 110)
    c.button((x0 + 300, y0 + 440), '로그인', 'primary')
    c.d.line((x0 + 170, y0 + 170, x1 - 170, y1 - 80), fill=RED, width=6)
    c.d.line((x1 - 170, y0 + 170, x0 + 170, y1 - 80), fill=RED, width=6)
    c.banner((x0 + 160, y1 - 120, x1 - 160, y1 - 40), '입력하지 말고 창을 닫습니다', 'warn', 22)
    # 네트워크 끊기
    qx0, qy0, qx1, qy1 = c.window((970, 30, 1370, 400), '빠른 설정')
    w = c.button((qx0, qy0 + 10), 'Wi-Fi  켬', 'primary', 22, (30, 18))
    c.mark(w, 2, 'right')
    c.wrap((qx0, qy0 + 110), '첨부파일을 열었거나 "콘텐츠 사용"을 눌렀다면 Wi-Fi를 끄거나 랜선을 뽑습니다.', qx1 - qx0, 19, TEXT)
    c.banner((qx0, qy0 + 200, qx1, qy0 + 260), 'PC 전원은 끄지 않습니다', 'amber', 20)
    c.banner((970, 430, 1370, 560), '정보보안팀 내선 1119 (가상)에 바로 연락합니다. 누른 시각과 한 일을 알려 주세요.', 'info', 20)
    c.save(P('sec001_33_link.png'))


@fig('sec001_34_reset.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '비밀번호 재설정 포털 (password.hanwha-ict.example, 가상)')
    c.text((x0 + 20, y0 + 30), '비밀번호 변경', 28, NAVY, True, 'lm')
    c.field((x0 + 20, y0 + 90), 420, '사번', 'EMP-0000', 20)
    c.field((x0 + 20, y0 + 156), 300, '휴대폰 인증', '인증 완료', 20)
    nb = c.field((x0 + 20, y0 + 222), 420, '새 비밀번호', '●●●●●●●●●●●●●', 20)
    c.field((x0 + 20, y0 + 288), 420, '새 비밀번호 확인', '●●●●●●●●●●●●●', 20)
    c.mark(nb, 1, 'right')
    rules = ['· 12자 이상', '· 대문자·소문자·숫자·특수문자 모두 포함', '· 최근 사용한 5개와 다름']
    c.rect((x0 + 720, y0 + 90, x1 - 20, y0 + 330), BG, LINE, 2, 8)
    c.text((x0 + 744, y0 + 122), '비밀번호 규칙', 21, NAVY, True, 'lm')
    for i, r in enumerate(rules):
        c.text((x0 + 744, y0 + 170 + i * 46), r, 20, GREEN, False, 'lm')
    b = c.button((x0 + 190, y0 + 380), '변경', 'primary', 22, (40, 12))
    c.mark(b, 2, 'right')
    c.banner((x0 + 20, y0 + 480, x1 - 20, y0 + 570), '같은 비밀번호를 쓰는 다른 사이트도 모두 바꿉니다. 바꾼 뒤 정보보안팀 내선 1119 (가상)에 입력한 시각을 알려 주세요.', 'info', 20)
    c.save(P('sec001_34_reset.png'))


@fig('sec001_35_mass.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '그룹웨어 메일 — 받은편지함')
    bn = (x0, y0, x1, y0 + 74)
    c.banner(bn, '[전사 공지] 인사팀을 사칭한 메일이 들어오고 있습니다. 열지 말고 [피싱 신고]를 눌러 주세요.', 'warn', 21)
    c.mark(bn, 2, 'bottom', 2)
    rows = [('[인사팀] 연말정산 서류 제출', 'hr-notice@hanvva-ict.example', '10:21', True),
            ('주간 회의 자료 공유', '김OO', '10:15', False),
            ('[인사팀] 연말정산 서류 제출', 'hr-notice@hanvva-ict.example', '10:20', True),
            ('고객사 미팅 일정 확인', '이OO', '09:58', False),
            ('[인사팀] 연말정산 서류 제출', 'hr-notice@hanvva-ict.example', '10:20', True)]
    y = y0 + 160
    c.text((x0 + 10, y - 30), '제목', 19, GREY, True, 'lm'); c.text((x0 + 640, y - 30), '보낸 사람', 19, GREY, True, 'lm'); c.text((x1 - 90, y - 30), '시각', 19, GREY, True, 'lm')
    hl = []
    for s, f, t, bad in rows:
        box = (x0, y, x1, y + 62)
        c.rect(box, PINK if bad else WHITE, LINE, 2, 4)
        c.text((x0 + 16, y + 31), ('[첨부] ' if bad else '') + s, 20, TEXT, bad, 'lm')
        c.text((x0 + 640, y + 31), f, 19, TEXT, False, 'lm')
        c.text((x1 - 90, y + 31), t, 19, GREY, False, 'lm')
        if bad:
            hl.append(box)
        y += 76
    c.highlight((hl[0][0], hl[0][1], hl[0][2], hl[-1][3]), 8)
    c.badge((x1 - 10, hl[0][1] + 10), 1)
    c.banner((x0, y + 10, x1, y + 90), '동료에게는 메일을 전달하지 말고 메신저로 제목만 알립니다. 팀에서 한 사람이 정보보안팀(내선 1119, 가상)에 받은 사람 수를 알립니다.', 'info', 20)
    c.save(P('sec001_35_mass.png'))


@fig('sec001_36_smish.png')
def _():
    c = Canvas(1400, 860)
    inner = c.phone((80, 20, 520, 840), '문자 메시지')
    x0, y0, x1, y1 = inner
    c.text((x0, y0 + 10), '+82 10-0000-0000', 18, GREY, False, 'lm')
    b = (x0, y0 + 40, x1, y0 + 330)
    c.rect(b, LIGHT, LIGHT, 1, 16)
    yy = c.wrap((x0 + 16, y0 + 58), '[IT헬프데스크] 계정 보안 점검 대상입니다. 오늘 안에 아래 링크에서 인증번호를 입력하지 않으면 계정이 잠깁니다.', x1 - x0 - 32, 19, TEXT)
    lk = (x0 + 16, yy + 4, x0 + 330, yy + 34)
    c.text((x0 + 16, yy + 19), 'http://it-check.example.xyz', 19, BLUE, False, 'lm')
    c.mark(lk, 1, 'bottom', 4)
    c.banner((x0, y1 - 150, x1, y1 - 20), '링크를 누르지 않습니다. 인증번호는 누구에게도 알려 주지 않습니다.', 'warn', 19)
    inner = c.phone((600, 20, 1040, 840), '통화')
    x0, y0, x1, y1 = inner
    c.text(((x0 + x1) / 2, y0 + 60), '02-000-0000', 30, TEXT, True, 'mm')
    c.wrap((x0 + 10, y0 + 120), '"IT 헬프데스크입니다. 보안 점검 중이니 방금 받은 인증번호를 불러 주세요."', x1 - x0 - 20, 20, TEXT)
    eb = (x0 + 110, y1 - 140, x1 - 110, y1 - 60)
    c.d.ellipse((((x0 + x1) / 2) - 45, y1 - 150, ((x0 + x1) / 2) + 45, y1 - 60), fill=RED)
    c.text(((x0 + x1) / 2, y1 - 105), '끊기', 20, WHITE, True, 'mm')
    c.mark((((x0 + x1) / 2) - 45, y1 - 150, ((x0 + x1) / 2) + 45, y1 - 60), 2, 'top')
    c.banner((1080, 120, 1380, 400), '공식 번호로 다시 걸어 확인합니다.\n\nIT 헬프데스크 내선 1000\n정보보안팀 내선 1119 (가상)', 'info', 21)
    c.banner((1080, 440, 1380, 600), '헬프데스크·정보보안팀·챗봇은 비밀번호와 인증번호를 묻지 않습니다.', 'warn', 20)
    c.save(P('sec001_36_smish.png'))


# ---------------- 담당자 매뉴얼 공통 콘솔 ----------------
MAILSEC_MENU = ['신고 메일', '메일 검색', '차단 정책', '일괄 삭제 기록', '통계']


@fig('m_mailsec_search.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '메일 보안 콘솔 (가상)', MAILSEC_MENU, 1)
    c.field((x0, y0 + 4), 520, '제목', '[인사팀] 연말정산 서류 제출', 19, 80)
    c.button((x0 + 620, y0), '검색', 'primary', 19, (20, 10))
    c.text((x0, y0 + 80), '발신: hr-notice@hanvva-ict.example   ·   수신 128명   ·   첨부 해시 3f9a…c21', 19, TEXT, True, 'lm')
    rows = [['기획팀 김OO', '미열람', '—'], ['영업1팀 이OO', '열람', '—'], [('개발2팀 박OO', RED, True), ('열람', RED, True), ('첨부 열기', RED, True)],
            ['재무팀 최OO', '미열람', '—'], [('연구소 정OO', RED, True), ('열람', RED, True), ('링크 클릭', RED, True)], ['인사팀 한OO', '신고함', '—']]
    boxes = c.table((x0, y0 + 120), x1 - x0, ['받는 사람', '상태', '행동'], rows, [380, 300, 300])
    c.mark((boxes[2][0], boxes[2][1], boxes[2][2], boxes[4][3]), 3, 'right', 2)
    b1 = c.button((x0, y1 - 70), '발신 도메인 차단', 'danger', 20)
    b2 = c.button((b1[2] + 16, y1 - 70), '첨부 해시 차단', 'danger', 20)
    b3 = c.button((b2[2] + 16, y1 - 70), '전사 메일함 일괄 삭제', 'primary', 20)
    c.mark((b1[0], b1[1], b2[2], b2[3]), 1, 'top')
    c.mark(b3, 2, 'top')
    c.save(P('m_mailsec_search.png'))


@fig('m_mailsec_block.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '메일 보안 콘솔 (가상)', MAILSEC_MENU, 0)
    rows = [['10-15 13:41', '급히 부탁드립니다', 'ceo.office@freemail.example', '사칭(BEC)'],
            ['10-15 09:13', '[급여명세서 확인] 10월 …', 'payroll@hanvva-ict.example', '피싱 링크'],
            ['10-14 17:02', '택배 배송 조회 안내', 'delivery@track.example.top', '피싱 링크']]
    boxes = c.table((x0, y0), x1 - x0, ['신고 시각', '제목', '보낸 사람', '판정'], rows, [170, 300, 410, 200], 18)
    c.mark(boxes[0], 1, 'right', 2)
    d = dialog(c, (x0 + 60, y0 + 260, x1 - 60, y1 - 20), '발신 주소 차단',
               ['차단 대상: ceo.office@freemail.example', '범위: 회사 전체 수신 차단 · 이미 받은 메일 검색 후 삭제',
                '사유: 임원 사칭(BEC) — 티켓 번호를 함께 기록합니다.'], [('취소', 'plain'), ('차단', 'danger')])
    c.mark(d['차단'], 2, 'top')
    c.save(P('m_mailsec_block.png'))


EDR_MENU = ['장치 목록', '탐지 알림', '격리 파일', '예외 관리', '정책']


@fig('m_edr_device.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'EDR 관리 콘솔 (가상)', EDR_MENU, 0)
    c.text((x0, y0 + 20), 'PC-DEV2-0412  ·  개발2팀 박OO  ·  Windows 11', 23, TEXT, True, 'lm')
    st = (x0, y0 + 50, x0 + 360, y0 + 92)
    c.rect(st, PINK, (231, 179, 166), 2, 6); c.text((x0 + 16, y0 + 71), '상태: 위협 탐지 1건 · 온라인', 19, RED, True, 'lm')
    rows = [['10:24:11', '문서 프로그램이 스크립트 실행', ('높음', RED, True)], ['10:24:15', '외부 주소 연결 시도', ('높음', RED, True)], ['10:25:02', '실행 파일 생성 (임시 폴더)', ('중간', AMBER, True)]]
    c.table((x0, y0 + 120), x1 - x0, ['시각', '탐지 내용', '위험도'], rows, [180, 640, 200], 19)
    b1 = c.button((x0, y0 + 330), '네트워크 격리', 'danger', 21)
    b2 = c.button((b1[2] + 16, y0 + 330), '전체 검사', 'primary', 21)
    b3 = c.button((b2[2] + 16, y0 + 330), '프로세스 목록', 'plain', 21)
    c.mark(b1, 1, 'bottom')
    c.mark(b2, 2, 'bottom')
    c.banner((x0, y0 + 470, x1, y1 - 20), '네트워크 격리 중에도 EDR 관리 통신은 유지됩니다. 검사·분석이 끝나면 [격리 해제]로 되돌리고 티켓에 결과를 남깁니다.', 'info', 20)
    c.save(P('m_edr_device.png'))


SSO_MENU = ['사용자 조회', '로그인 기록', '세션 관리', '해외 접속 예외', 'MFA 기기']


@fig('m_sso_history.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'SSO 접속 기록 조회 (가상)', SSO_MENU, 1)
    c.field((x0, y0 + 4), 240, '사번', 'EMP-0000', 19, 60)
    c.field((x0 + 340, y0 + 4), 280, '기간', '최근 7일', 19, 60)
    rows = [['10-15 08:51', '사내망', '서울', 'PC 브라우저', ('성공', GREEN, True)],
            [('10-15 10:32', RED, True), ('해외 IP', RED, True), ('해외', RED, True), ('알 수 없는 기기', RED, True), ('성공', RED, True)],
            ['10-15 10:33', '해외 IP', '해외', '알 수 없는 기기', ('MFA 거부', AMBER, True)],
            ['10-15 11:02', 'VPN', '서울', '업무 노트북', ('성공', GREEN, True)]]
    boxes = c.table((x0, y0 + 80), x1 - x0, ['시각', '접속 위치', '지역', '기기', '결과'], rows, [180, 200, 140, 300, 200], 19)
    c.mark(boxes[1], 1, 'right', 2)
    b1 = c.button((x0, y0 + 360), '세션 강제 종료', 'danger', 21)
    b2 = c.button((b1[2] + 16, y0 + 360), '비밀번호 초기화 요청', 'primary', 21)
    b3 = c.button((b2[2] + 16, y0 + 360), 'MFA 재등록', 'plain', 21)
    c.mark(b1, 2, 'bottom')
    c.mark((b2[0], b2[1], b3[2], b3[3]), 3, 'bottom')
    c.banner((x0, y0 + 500, x1, y1 - 20), '본인 확인(사번 + 휴대폰 인증) 없이 비밀번호·MFA를 바꾸지 않습니다. 세션 강제 종료는 보안 조치라 먼저 실행할 수 있습니다.', 'info', 20)
    c.save(P('m_sso_history.png'))


@fig('m001_flow.png')
def _():
    flow(P('m001_flow.png'), [
        ('접수', 'ITssue 챗봇·전화·메신저로 접수. [피싱 신고] 버튼 신고는 정보보안팀에 바로 들어온다.'),
        ('클릭·입력 확인', '링크를 눌렀는지, 첨부를 열었는지, 계정 정보를 입력했는지 먼저 묻는다.'),
        ('분류', '열기만 함 3.1 · 사칭 요청 3.2 · 클릭 3.3 · 입력 3.4 · 여러 명 3.5 · 메일 외 3.6'),
        ('정보보안팀 조치', '발신 차단·일괄 삭제, PC 격리·검사, 세션 종료·비밀번호 초기화'),
        ('회신·종결', '결과와 사용자가 할 일을 안내하고 FIN. 처리 기록 5장 항목을 남긴다.'),
    ], colors=[NAVY, ORANGE, NAVY, (192, 57, 43), GREEN])


if __name__ == '__main__':
    import sys
    import figs2  # IT-SEC-002~004 그림 (figs 모듈의 FIGS에 등록됨)
    import figs as _mod
    only = sys.argv[1:]
    for name, fn in {**FIGS, **_mod.FIGS}.items():
        if not only or any(name.startswith(o) for o in only):
            fn()
            print('fig', name)
