"""ACC 가이드·매뉴얼 그림 생성. python figs.py → ../images/*.png

원본(계정로그인 v1.1)의 화면 구성을 따르되 값은 저장소 기준으로 그린다.
모든 화면은 설명용 가상 화면이다. 주소·사번·번호는 모두 가상 값이다.
"""
import os
from figlib import Canvas, flow, font, NAVY, TEXT, GREY, LIGHT, LINE, RED, ORANGE, WHITE, BG, BLUE, GREEN, AMBER, PINK

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'images'))
os.makedirs(OUT, exist_ok=True)
FIGS = {}
EMP = 'EMP-0000'
DOM = 'hanwha-ict.example'
OKBG, OKLN = (227, 242, 232), (181, 214, 192)


def fig(name):
    def deco(fn):
        FIGS[name] = fn
        return fn
    return deco


def P(name):
    return os.path.join(OUT, name)


# ---------------- 부품 ----------------
def browser(c, box, url, title='웹 브라우저'):
    x0, y0, x1, y1 = c.window(box, title)
    addr = (x0, y0, x1, y0 + 44)
    c.rect(addr, BG, LINE, 2, 20)
    c.text((x0 + 20, y0 + 22), url, 19, GREY, False, 'lm')
    return (x0, y0 + 64, x1, y1), addr


def card(c, cx, y0, w, h, title, sub=None):
    box = (cx - w / 2, y0, cx + w / 2, y0 + h)
    c.rect(box, WHITE, LINE, 2, 12)
    c.text((box[0] + 28, y0 + 40), title, 26, NAVY, True, 'lm')
    if sub:
        c.text((box[0] + 28, y0 + 76), sub, 18, GREY, False, 'lm')
    return box


def login_card(c, cx, y0, w=520, pw='●●●●●●●●●●●●', banner=None, kind='warn'):
    box = card(c, cx, y0, w, 470 if banner else 400, '통합 로그인 (SSO)', '그룹웨어 · ERP · 메일 · VPN · 메신저')
    x = box[0] + 28
    c.text((x, y0 + 120), '사번', 18, GREY, False, 'lm')
    f1 = (x, y0 + 138, box[2] - 28, y0 + 182); c.rect(f1, WHITE, LINE, 2, 6); c.text((x + 14, y0 + 160), EMP, 19, TEXT, False, 'lm')
    c.text((x, y0 + 206), '비밀번호', 18, GREY, False, 'lm')
    f2 = (x, y0 + 224, box[2] - 28, y0 + 268); c.rect(f2, WHITE, LINE, 2, 6); c.text((x + 14, y0 + 246), pw, 19, TEXT, False, 'lm')
    y = y0 + 288
    bn = None
    if banner:
        bn = (x, y, box[2] - 28, y + 74)
        c.banner(bn, banner, kind, 18)
        y += 90
    b = c.button((x, y), '로그인', 'primary', 21)
    b = (x, b[1], box[2] - 28, b[3])
    return {'id': f1, 'pw': f2, 'banner': bn, 'login': b, 'box': box}


def status_card(c, cx, y0, title, lines, buttons, color=RED, w=600):
    h = 160 + 34 * len(lines) + 70 * len(buttons)
    box = (cx - w / 2, y0, cx + w / 2, y0 + h)
    c.rect(box, WHITE, LINE, 2, 12)
    c.text((cx, y0 + 50), title, 26, color, True, 'mm')
    y = y0 + 100
    for ln in lines:
        c.text((cx, y), ln, 19, TEXT, False, 'mm'); y += 34
    res = []
    y += 16
    for label, kind in buttons:
        b = c.button((box[0] + 40, y), label, kind, 21)
        b = (box[0] + 40, b[1], box[2] - 40, b[3])
        c.rect(b, NAVY if kind == 'primary' else WHITE, NAVY, 2, 8)
        c.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), label, 21, WHITE if kind == 'primary' else NAVY, True, 'mm')
        res.append(b)
        y = b[3] + 16
    return box, res


def console(c, box, title, menu, active):
    x0, y0, x1, y1 = c.window(box, title)
    c.rect((x0, y0, x0 + 210, y1), LIGHT, LIGHT, 1, 6)
    for i, m in enumerate(menu):
        on = (i == active)
        if on:
            c.rect((x0 + 8, y0 + 12 + i * 50, x0 + 202, y0 + 52 + i * 50), WHITE, NAVY, 2, 6)
        c.text((x0 + 22, y0 + 32 + i * 50), m, 19, NAVY if on else GREY, on, 'lm')
    return (x0 + 236, y0, x1, y1)


def checkline(c, x, y, ok, label, size=19):
    col = GREEN if ok else RED
    if ok:
        c.d.line([(x, y + 2), (x + 7, y + 10), (x + 18, y - 6)], fill=col, width=4)
    else:
        c.d.line([(x, y - 6), (x + 16, y + 10)], fill=col, width=4); c.d.line([(x + 16, y - 6), (x, y + 10)], fill=col, width=4)
    c.text((x + 30, y + 2), label, size, col, not ok, 'lm')


def toggle(c, x, y, on=True):
    c.d.rounded_rectangle((x, y, x + 70, y + 38), 19, fill=GREEN if on else (200, 205, 212))
    cx = x + 51 if on else x + 19
    c.d.ellipse((cx - 15, y + 4, cx + 15, y + 34), fill=WHITE)
    return (x, y, x + 70, y + 38)


AUTH_APP = '인증 앱 (가상)'
IAM_MENU = ['사용자 조회', '잠금 현황', '로그인 기록', 'MFA 기기 관리', '감사 로그']


# ---------------- IT-ACC-001 ----------------
@fig('acc001_31_error.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 1370, 830), f'https://sso.{DOM}')
    r = login_card(c, (x0 + x1) / 2, y0 + 20, 600, '', '아이디 또는 비밀번호가 일치하지 않습니다. (AUTH-101) 남은 시도 3회 · 5회 실패 시 10분간 잠김')
    c.mark(r['id'], 1, 'right')
    c.mark(r['banner'], 2, 'right')
    c.banner((x0, y1 - 90, x1, y1 - 10), 'ID는 이메일이 아니라 사번입니다. Caps Lock·한/영 전환을 확인합니다.', 'info', 19)
    c.save(P('acc001_31_error.png'))


@fig('acc001_32_lock.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 760, 830), f'https://sso.{DOM}/locked')
    box, bs = status_card(c, (x0 + x1) / 2, y0 + 30, '계정이 잠겼습니다 (AUTH-102)',
                          ['비밀번호를 5회 연속 잘못 입력했습니다.', '10분 뒤 자동으로 풀립니다. (남은 시간 7분)'],
                          [('지금 잠금 해제 (본인 인증)', 'primary'), ('비밀번호 초기화', 'plain')], w=560)
    c.mark(bs[0], 1, 'right', 4)
    wx0, wy0, wx1, wy1 = c.window((790, 30, 1370, 830), '자격 증명 관리자 (Windows)')
    c.text((wx0, wy0 + 10), 'Windows 자격 증명', 21, NAVY, True, 'lm')
    rows = [('\\\\fileserver01 (공유 드라이브)', '2026-06-02 저장', True), ('sso.' + DOM, '2026-10-14 저장', False), ('mail.' + DOM, '2026-10-14 저장', False)]
    y = wy0 + 40
    for t, d, old in rows:
        b = (wx0, y, wx1, y + 70)
        c.rect(b, PINK if old else WHITE, LINE, 2, 6)
        c.text((wx0 + 14, y + 22), t, 18, TEXT, old, 'lm'); c.text((wx0 + 14, y + 50), d, 16, GREY, False, 'lm')
        if old:
            rb = c.button((wx1 - 90, y + 16), '제거', 'plain', 17, (14, 6))
            c.mark(rb, 2, 'bottom', 3)
        y += 80
    c.wrap((wx0, y + 30), '비밀번호를 바꾼 뒤 잠김이 반복되면 예전 비밀번호로 저장된 항목(공유 드라이브·휴대폰 메일 앱)을 지우고 다시 연결합니다.', wx1 - wx0, 18, TEXT)
    c.save(P('acc001_32_lock.png'))


@fig('acc001_33_sso.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 760, 830), f'https://sso.{DOM}')
    box = card(c, (x0 + x1) / 2, y0 + 30, 560, 300, '통합 로그인 (SSO)')
    cx, cy = (x0 + x1) / 2, y0 + 190
    c.d.arc((cx - 40, cy - 40, cx + 40, cy + 40), 20, 300, fill=NAVY, width=8)
    c.text((cx, cy + 80), '로그인 중… (화면이 넘어가지 않음)', 19, GREY, False, 'mm')
    c.mark((box[0], box[1], box[2], box[3]), 1, 'bottom', 4)
    c.banner((x0, y0 + 420, x1, y0 + 560), '옆자리 동료도 같은 증상이면 개인 조치를 멈추고 IT 헬프데스크(내선 1000)에 알립니다. 회사 전체 장애일 수 있습니다.', 'warn', 19)
    wx0, wy0, wx1, wy1 = c.window((790, 30, 1370, 830), '인터넷 사용 기록 삭제')
    c.text((wx0, wy0 + 20), '기간', 19, GREY, False, 'lm')
    c.rect((wx0, wy0 + 40, wx1, wy0 + 84), WHITE, LINE, 2, 6); c.text((wx0 + 14, wy0 + 62), '전체 기간', 19, TEXT, False, 'lm')
    items = [('방문 기록', False), ('쿠키 및 기타 사이트 데이터', True), ('캐시된 이미지 및 파일', True), ('저장된 비밀번호', False)]
    y = wy0 + 120
    for t, on in items:
        b = (wx0, y, wx0 + 26, y + 26)
        c.rect(b, NAVY if on else WHITE, NAVY, 2, 4)
        if on:
            c.d.line([(wx0 + 6, y + 13), (wx0 + 11, y + 19), (wx0 + 20, y + 7)], fill=WHITE, width=4)
        c.text((wx0 + 40, y + 13), t, 19, TEXT, False, 'lm')
        y += 50
    c.mark((wx0, wy0 + 166, wx1 - 40, wy0 + 246), 2, 'right', 4)
    b = c.button((wx1 - 120, y + 20), '삭제', 'primary', 20)
    c.mark(b, 3, 'left')
    c.save(P('acc001_33_sso.png'))


@fig('acc001_34_dormant.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 1370, 830), f'https://sso.{DOM}/dormant')
    box, bs = status_card(c, (x0 + x1) / 2, y0 + 30, '휴면 처리된 계정입니다 (AUTH-103)',
                          ['마지막 로그인: 2026-05-02', '90일 이상 로그인하지 않아 휴면 처리되었습니다.'],
                          [('휴면 해제하기 (본인 인증)', 'primary')], color=NAVY, w=640)
    c.mark(bs[0], 1, 'right')
    c.banner((box[0], box[3] + 30, box[2], box[3] + 130), '본인 인증 뒤 바로 쓸 수 있습니다. 180일 이상이면 셀프 해제가 되지 않아 IT 헬프데스크에 문의합니다.', 'info', 19)
    c.save(P('acc001_34_dormant.png'))


@fig('acc001_35_suspended.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 1370, 830), f'https://sso.{DOM}')
    box, bs = status_card(c, (x0 + x1) / 2, y0 + 30, '사용이 중지된 계정입니다 (AUTH-105)',
                          ['휴직·퇴사 처리 또는 관리자 정지 상태입니다.', '셀프 해제할 수 없습니다.'], [('IT 헬프데스크 문의 (내선 1000)', 'plain')], w=640)
    c.mark((box[0] + 20, box[1] + 20, box[2] - 20, box[1] + 80), 1, 'right', 2)
    c.banner((box[0], box[3] + 30, box[2], box[3] + 130), '복직했다면 인사 시스템에 복직 처리가 됐는지 먼저 확인합니다. 다른 사람이 대신 요청할 수 없습니다.', 'info', 19)
    c.save(P('acc001_35_suspended.png'))


@fig('acc001_36_session.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 760, 830), f'https://gw.{DOM}')
    box, bs = status_card(c, (x0 + x1) / 2, y0 + 30, '세션이 만료되었습니다', ['30분 동안 사용하지 않아 로그아웃되었습니다.', '작성 중인 내용은 임시 저장되었습니다.'],
                          [('다시 로그인', 'primary')], color=NAVY, w=600)
    c.banner((box[0], box[3] + 24, box[2], box[3] + 130), '다른 곳에서 로그인하지 않았는데 "다른 기기에서 로그인되어 종료"가 나오면 정보보안팀에 알립니다.', 'amber', 18)
    (gx0, gy0, gx1, gy1), _a = browser(c, (790, 30, 1370, 830), f'https://gw.{DOM}', '그룹웨어')
    nm = (gx1 - 180, gy0, gx1, gy0 + 46)
    c.rect(nm, LIGHT, LINE, 2, 8); c.text((nm[0] + 20, gy0 + 23), '홍길동  v', 19, NAVY, True, 'lm')
    c.mark(nm, 1, 'left')
    menu = (gx1 - 260, gy0 + 60, gx1, gy0 + 230)
    c.rect(menu, WHITE, LINE, 2, 8)
    c.text((menu[0] + 20, gy0 + 90), '내 정보', 19, TEXT, False, 'lm'); c.text((menu[0] + 20, gy0 + 140), '환경 설정', 19, TEXT, False, 'lm')
    lo = (menu[0] + 10, gy0 + 170, menu[2] - 10, gy0 + 216)
    c.rect(lo, PINK, PINK, 1, 6); c.text((lo[0] + 10, gy0 + 193), '로그아웃', 19, RED, True, 'lm')
    c.mark(lo, 2, 'left')
    c.wrap((gx0, gy0 + 280), '[로그아웃]을 누르면 SSO로 연결된 모든 시스템에서 함께 로그아웃됩니다. 공용 PC면 브라우저도 닫습니다.', gx1 - gx0, 18, TEXT)
    c.save(P('acc001_36_session.png'))


# ---------------- IT-ACC-002 ----------------
def portal(c, box, path, title):
    (x0, y0, x1, y1), addr = browser(c, box, f'https://password.{DOM}{path}', '셀프 비밀번호 재설정 포털 (가상)')
    c.text((x0 + 10, y0 + 20), title, 27, NAVY, True, 'lm')
    return x0, y0 + 50, x1, y1


@fig('acc002_31_rules.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = portal(c, (30, 30, 1370, 830), '/change', '비밀번호 변경')
    for i, (lab, val) in enumerate([('현재 비밀번호', '●●●●●●●●●●●●'), ('새 비밀번호', '●●●●●●●●'), ('새 비밀번호 확인', '●●●●●●●●')]):
        c.field((x0 + 10, y0 + 20 + i * 66), 380, lab, val, 19, 170)
    c.mark((x0 + 180, y0 + 86, x0 + 560, y0 + 130), 1, 'right')
    rb = (x0 + 720, y0 + 20, x1 - 20, y0 + 300)
    c.rect(rb, BG, LINE, 2, 8)
    c.text((rb[0] + 20, rb[1] + 30), '비밀번호 규칙', 21, NAVY, True, 'lm')
    rules = [(False, '12자 이상'), (False, '대문자·소문자·숫자·특수문자 모두 포함'), (True, '사번·이름·생년월일 미포함'), (True, '최근 사용한 5개와 다름')]
    for i, (ok, t) in enumerate(rules):
        checkline(c, rb[0] + 24, rb[1] + 80 + i * 48, ok, t)
    c.mark((rb[0] + 14, rb[1] + 60, rb[2] - 14, rb[1] + 150), 2, 'bottom', 2)
    c.button((x0 + 180, y0 + 230), '변경', 'primary', 21, (40, 12))
    c.banner((x0 + 10, y0 + 380, x1 - 20, y0 + 470), '빨간 항목이 남아 있으면 [변경]이 되지 않습니다. 예: 1234, Password1 → 사용 불가', 'warn', 19)
    c.save(P('acc002_31_rules.png'))


@fig('acc002_32_change.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = portal(c, (30, 30, 1370, 830), '/change', '비밀번호 변경 완료')
    c.banner((x0 + 10, y0 + 10, x1 - 20, y0 + 80), '비밀번호가 변경되었습니다. SSO로 연결된 모든 시스템에 바로 적용됩니다.', 'ok', 20)
    c.text((x0 + 10, y0 + 120), '예전 비밀번호가 저장된 곳도 바꿔 주세요', 22, NAVY, True, 'lm')
    rows = [['휴대폰 메일 앱', '메일 앱 계정 설정에서 비밀번호 수정'], ['PC 자격 증명 관리자', '공유 드라이브 등 저장 항목 제거 후 다시 연결'],
            ['VPN 클라이언트', '다시 로그인'], ['사내 메신저 (PC·모바일)', '다시 로그인']]
    boxes = c.table((x0 + 10, y0 + 150), x1 - x0 - 30, ['저장된 곳', '바꾸는 방법'], rows, [380, 700], 19)
    c.mark((boxes[0][0], boxes[0][1], boxes[1][2], boxes[1][3]), 1, 'right', 2)
    c.banner((x0 + 10, y0 + 420, x1 - 20, y0 + 500), '가장 흔한 반복 잠김 원인은 휴대폰 메일 앱과 공유 드라이브에 남은 예전 비밀번호입니다.', 'amber', 19)
    c.save(P('acc002_32_change.png'))


@fig('acc002_33_expired.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 1370, 830), f'https://sso.{DOM}/expired')
    box, bs = status_card(c, (x0 + x1) / 2, y0 + 30, '비밀번호가 만료되었습니다 (AUTH-104)',
                          ['비밀번호 사용 기간(90일)이 지났습니다.', '새 비밀번호로 바꿔야 로그인할 수 있습니다.'],
                          [('지금 변경', 'primary'), ('비밀번호가 기억나지 않나요?', 'plain')], color=NAVY, w=640)
    c.mark(bs[0], 1, 'right')
    c.mark(bs[1], 2, 'right')
    c.save(P('acc002_33_expired.png'))


@fig('acc002_34_reset.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = portal(c, (30, 30, 1370, 830), '/reset', '비밀번호 초기화 (잊었을 때)')
    steps = [('1. 사번 입력', EMP), ('2. 본인 인증', '등록 휴대폰 인증번호 (3분)'), ('3. 새 비밀번호', '12자 이상 · 4종 모두 포함')]
    w = (x1 - x0 - 60) / 3
    for i, (t, v) in enumerate(steps):
        b = (x0 + 10 + i * (w + 20), y0 + 20, x0 + 10 + i * (w + 20) + w, y0 + 200)
        c.rect(b, WHITE, LINE, 2, 10); c.d.rectangle((b[0], b[1], b[2], b[1] + 8), fill=NAVY)
        c.text((b[0] + 20, b[1] + 50), t, 22, NAVY, True, 'lm')
        c.rect((b[0] + 20, b[1] + 90, b[2] - 20, b[1] + 134), WHITE, LINE, 2, 6); c.text((b[0] + 34, b[1] + 112), v, 18, TEXT, False, 'lm')
        c.badge((b[2] - 30, b[1] + 50), i + 1)
    c.highlight((x0 + 10 + w + 20, y0 + 20, x0 + 10 + 2 * w + 20, y0 + 200))
    c.banner((x0 + 10, y0 + 240, x1 - 20, y0 + 330), '회사는 예전 비밀번호를 저장하지 않아 찾아 줄 수 없습니다. 본인 인증 뒤 새 비밀번호로 바꿉니다. 계정이 잠겨 있었다면 함께 풀립니다.', 'info', 19)
    c.banner((x0 + 10, y0 + 350, x1 - 20, y0 + 430), '휴대폰 번호가 바뀌어 인증번호를 받을 수 없으면 3.5를 따릅니다.', 'amber', 19)
    c.save(P('acc002_34_reset.png'))


@fig('acc002_35_helpdesk.png')
def _():
    c = Canvas(1400, 860)
    cx0, cy0, cx1, cy1 = c.window((30, 30, 860, 830), 'ITssue 챗봇')
    b1 = (cx0 + 120, cy0 + 10, cx1, cy0 + 120)
    c.rect(b1, LIGHT, LIGHT, 1, 14)
    c.wrap((b1[0] + 16, b1[1] + 14), '휴대폰 번호가 바뀌어서 비밀번호 초기화 인증번호를 못 받아요.', b1[2] - b1[0] - 32, 19, TEXT)
    b2 = (cx0, cy0 + 150, cx1 - 120, cy0 + 380)
    c.rect(b2, WHITE, LINE, 2, 14)
    c.wrap((b2[0] + 16, b2[1] + 14), '셀프 초기화를 할 수 없는 경우입니다. 서비스데스크가 본인 확인(화상 또는 대면) 후 임시 비밀번호를 발급합니다. 담당자에게 요청서(티켓)를 넘겼습니다.\n※ 비밀번호와 인증번호는 묻지 않습니다.', b2[2] - b2[0] - 32, 19, TEXT)
    c.mark(b2, 1, 'right')
    px0, py0, px1, py1 = c.phone((930, 20, 1370, 840), '문자 메시지')
    m = (px0, py0 + 20, px1, py0 + 250)
    c.rect(m, LIGHT, LIGHT, 1, 14)
    c.wrap((m[0] + 14, m[1] + 14), '[IT 헬프데스크] 임시 비밀번호가 발급되었습니다. 24시간 안에 로그인해 새 비밀번호로 바꾸세요.', m[2] - m[0] - 28, 18, TEXT)
    c.mark(m, 2, 'bottom', 4)
    c.banner((px0, py1 - 230, px1, py1 - 30), '임시 비밀번호는 등록 휴대폰 문자로만 받습니다. 메일·메신저로 보내 달라는 요청은 처리하지 않습니다.', 'info', 17)
    c.save(P('acc002_35_helpdesk.png'))


# ---------------- IT-ACC-003 ----------------
@fig('acc003_31_register.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 900, 830), f'https://password.{DOM}/mfa', '셀프 비밀번호 재설정 포털 (가상)')
    c.text((x0 + 10, y0 + 20), '인증 기기 등록', 27, NAVY, True, 'lm')
    q = (x0 + 30, y0 + 70, x0 + 290, y0 + 330)
    c.rect(q, WHITE, LINE, 2, 4)
    import random
    random.seed(7)
    s = 20
    for i in range(12):
        for j in range(12):
            if random.random() < 0.45 or (i < 3 and j < 3) or (i < 3 and j > 8) or (i > 8 and j < 3):
                c.d.rectangle((q[0] + 10 + j * s, q[1] + 10 + i * s, q[0] + 10 + j * s + s, q[1] + 10 + i * s + s), fill=TEXT)
    c.mark(q, 1, 'right')
    c.field((x0 + 30, y0 + 360), 260, '앱에 나온 6자리', '', 19, 170)
    b = c.button((x0 + 200, y0 + 430), '등록 완료', 'primary', 21)
    c.mark(b, 3, 'right')
    px0, py0, px1, py1 = c.phone((950, 20, 1370, 840), AUTH_APP)
    sc = (px0 + 20, py0 + 20, px1 - 20, py0 + 300)
    c.rect(sc, (40, 44, 52), (40, 44, 52), 1, 10)
    c.d.rectangle((sc[0] + 70, sc[1] + 50, sc[2] - 70, sc[3] - 50), outline=WHITE, width=4)
    c.text(((sc[0] + sc[2]) / 2, sc[3] + 30), 'QR 스캔', 21, NAVY, True, 'mm')
    c.text(((px0 + px1) / 2, py0 + 400), '482 913', 40, NAVY, True, 'mm')
    c.mark((px0 + 60, py0 + 370, px1 - 60, py0 + 430), 2, 'bottom', 4)
    c.save(P('acc003_31_register.png'))


@fig('acc003_32_push.png')
def _():
    c = Canvas(1400, 860)
    px0, py0, px1, py1 = c.phone((80, 20, 520, 840), '설정 › 알림')
    c.text((px0, py0 + 10), AUTH_APP, 22, TEXT, True, 'lm')
    rows = [('알림 허용', True), ('잠금 화면에 표시', True), ('배너', True)]
    y = py0 + 60
    for i, (t, on) in enumerate(rows):
        c.text((px0, y + 19), t, 20, TEXT, False, 'lm')
        tb = toggle(c, px1 - 80, y, on)
        if i == 0:
            c.mark(tb, 1, 'bottom', 4)
        y += 80
    c.text((px0, y + 40), '배터리 › 제한 없음 (Android)', 19, GREY, False, 'lm')
    qx0, qy0, qx1, qy1 = c.phone((600, 20, 1040, 840), AUTH_APP)
    rq = (qx0, qy0 + 40, qx1, qy0 + 260)
    c.rect(rq, LIGHT, LIGHT, 1, 12)
    c.text((qx0 + 20, qy0 + 76), '로그인 승인 요청', 22, NAVY, True, 'lm')
    c.text((qx0 + 20, qy0 + 120), '서비스: 통합 로그인', 19, TEXT, False, 'lm')
    c.text((qx0 + 20, qy0 + 156), '위치: 서울 · 방금', 19, TEXT, False, 'lm')
    c.mark(rq, 2, 'bottom', 4)
    c.button((qx0, qy0 + 300), ' 거부 ', 'plain', 22, (30, 14)); c.button((qx0 + 200, qy0 + 300), ' 승인 ', 'primary', 22, (30, 14))
    c.banner((1080, 120, 1380, 420), '알림이 안 와도 앱을 직접 열면 승인 요청이 와 있는 경우가 있습니다. 급하면 [다른 방법으로 인증] › 앱 인증번호(OTP)를 씁니다.', 'info', 19)
    c.save(P('acc003_32_push.png'))


@fig('acc003_33_otp.png')
def _():
    c = Canvas(1400, 860)
    px0, py0, px1, py1 = c.phone((80, 20, 520, 840), AUTH_APP)
    c.text(((px0 + px1) / 2, py0 + 30), f'HanwhaSystems · {EMP}', 19, GREY, False, 'mm')
    c.text(((px0 + px1) / 2, py0 + 110), '482 913', 46, NAVY, True, 'mm')
    c.d.arc(((px0 + px1) / 2 - 50, py0 + 170, (px0 + px1) / 2 + 50, py0 + 270), -90, 160, fill=GREEN, width=10)
    c.text(((px0 + px1) / 2, py0 + 220), '21초', 22, TEXT, True, 'mm')
    c.mark((px0 + 40, py0 + 70, px1 - 40, py0 + 280), 1, 'bottom', 4)
    c.wrap((px0, py0 + 340), '30초마다 새 번호로 바뀝니다. 남은 시간이 5초 이하면 다음 번호를 씁니다.', px1 - px0, 18, TEXT)
    qx0, qy0, qx1, qy1 = c.phone((600, 20, 1040, 840), '설정 › 날짜 및 시간')
    c.text((qx0, qy0 + 30), '자동으로 설정', 21, TEXT, False, 'lm')
    tb = toggle(c, qx1 - 80, qy0 + 12, True)
    c.mark(tb, 2, 'bottom', 4)
    c.text((qx0, qy0 + 130), '시간대: 서울 (GMT+9)', 19, GREY, False, 'lm')
    c.banner((1080, 120, 1380, 440), '인증번호는 시간으로 만들어집니다. 휴대폰 시간이 수동 설정이면 번호가 틀립니다. 3회 연속 틀리면 10분간 제한됩니다.', 'warn', 19)
    c.save(P('acc003_33_otp.png'))


@fig('acc003_34_loop.png')
def _():
    c = Canvas(1400, 860)
    px0, py0, px1, py1 = c.phone((80, 20, 520, 840), AUTH_APP)
    c.text(((px0 + px1) / 2, py0 + 30), '앱 다시 로그인', 22, NAVY, True, 'mm')
    b = (px0, py0 + 70, px1, py0 + 240)
    c.banner(b, '추가 인증이 필요합니다. 인증 앱에서 요청을 승인하세요.', 'warn', 19)
    c.mark(b, 1, 'bottom', 4)
    c.arrow((px1 - 60, py0 + 330), (px0 + 60, py0 + 330), RED, 6)
    c.text(((px0 + px1) / 2, py0 + 380), '같은 앱으로 다시 돌아옴 (반복)', 19, RED, True, 'mm')
    cx0, cy0, cx1, cy1 = c.window((600, 30, 1370, 830), 'ITssue 챗봇')
    m = (cx0 + 80, cy0 + 10, cx1, cy0 + 120)
    c.rect(m, LIGHT, LIGHT, 1, 14)
    c.wrap((m[0] + 14, m[1] + 14), '인증 앱에 다시 로그인하려는데 그 앱으로 인증하라고 해서 계속 반복돼요.', m[2] - m[0] - 28, 19, TEXT)
    r = (cx0, cy0 + 150, cx1 - 80, cy0 + 360)
    c.rect(r, WHITE, LINE, 2, 14)
    c.wrap((r[0] + 14, r[1] + 14), '인증 앱 세션이 만료되어 반복되는 경우입니다. 혼자 해결할 수 없어 서비스데스크가 본인 확인 후 인증 기기를 초기화하고 다시 등록하도록 안내합니다.', r[2] - r[0] - 28, 19, TEXT)
    c.mark(r, 2, 'right')
    c.save(P('acc003_34_loop.png'))


@fig('acc003_35_change.png')
def _():
    c = Canvas(1400, 860)
    (x0, y0, x1, y1), addr = browser(c, (30, 30, 900, 830), f'https://password.{DOM}/mfa/change', '셀프 비밀번호 재설정 포털 (가상)')
    c.text((x0 + 10, y0 + 20), '인증 기기 변경', 27, NAVY, True, 'lm')
    steps = ['예전 휴대폰으로 로그인 승인', '새 휴대폰에 인증 앱 설치', '새 휴대폰으로 QR 스캔', '6자리 번호 입력 → 등록 완료']
    for i, t in enumerate(steps):
        c.badge((x0 + 40, y0 + 90 + i * 70), i + 1)
        c.text((x0 + 80, y0 + 90 + i * 70), t, 21, TEXT, i == 0, 'lm')
    c.highlight((x0 + 14, y0 + 64, x0 + 460, y0 + 116))
    c.banner((x0 + 10, y0 + 380, x1 - 20, y0 + 480), '예전 휴대폰을 초기화하거나 반납하기 전에 해야 합니다. 등록하면 예전 휴대폰의 인증 앱은 쓸 수 없습니다.', 'warn', 19)
    rx0, ry0, rx1, ry1 = c.window((930, 30, 1370, 830), '예전 휴대폰이 없으면')
    y = ry0
    for t in ['등록 번호가 같으면: [다른 방법으로 인증] › 문자 인증번호로 로그인한 뒤 변경합니다.',
              '번호도 바뀌었거나 잃어버렸으면: 서비스데스크가 본인 확인 후 인증 기기를 초기화합니다.',
              '잃어버렸으면 먼저 분실 신고를 합니다 (IT-SEC-003 3.6).']:
        y = c.wrap((rx0, y), '· ' + t, rx1 - rx0, 19, TEXT) + 22
    c.save(P('acc003_35_change.png'))


# ---------------- 담당자 매뉴얼 ----------------
@fig('m_iam_user.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '계정 관리 콘솔 (가상) — 관리자 전용 · 사내망', IAM_MENU, 0)
    c.field((x0, y0 + 4), 520, '사번', EMP, 19, 60)
    c.text((x0, y0 + 80), '사용자 정보', 22, NAVY, True, 'lm')
    st = (x0 + 140, y0 + 64, x0 + 250, y0 + 96)
    c.rect(st, PINK, (231, 179, 166), 2, 6); c.text((st[0] + 12, y0 + 80), 'LOCKED', 17, RED, True, 'lm')
    info = [('부서', '재무팀'), ('인사 상태', '재직'), ('잠금 사유', '비밀번호 5회 실패'), ('자동 해제', '10분 뒤'),
            ('비밀번호 변경일', '2026-10-15 (1일 전)'), ('MFA 기기', 'Android · 2025-03-02 등록')]
    for i, (k, v) in enumerate(info):
        xx = x0 + (i % 2) * 520; yy = y0 + 130 + (i // 2) * 44
        c.text((xx, yy), k, 18, GREY, False, 'lm'); c.text((xx + 170, yy), v, 19, TEXT, False, 'lm')
    c.mark((x0 + 520, y0 + 196, x0 + 1000, y0 + 216 + 4), 1, 'right', 6)
    bx = x0
    bs = []
    for label, kind in [('잠금 해제', 'primary'), ('임시 비밀번호 발급', 'plain'), ('MFA 기기 초기화', 'plain'), ('세션 강제 종료', 'plain'), ('보안 이관', 'danger')]:
        b = c.button((bx, y0 + 290), label, kind, 18, (16, 10)); bs.append(b); bx = b[2] + 12
    c.mark(bs[0], 2, 'bottom')
    c.banner((x0, y0 + 400, x1, y0 + 500), '모든 작업은 감사 로그에 처리자·티켓 번호가 남는다. 티켓 없이 작업하지 않는다. 본인 확인 수준은 2장 표를 따른다.', 'info', 19)
    c.save(P('m_iam_user.png'))


@fig('m_iam_fail.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '계정 관리 콘솔 (가상) — 로그인 실패 기록', IAM_MENU, 2)
    rows = [['13:54:01', '모바일 메일 앱', '사내 Wi-Fi', '비밀번호 불일치'], ['13:55:00', '모바일 메일 앱', '사내 Wi-Fi', '비밀번호 불일치'],
            ['13:56:00', '공유 드라이브 (PC)', '사내망', '비밀번호 불일치'], ['13:57:01', '모바일 메일 앱', '사내 Wi-Fi', '비밀번호 불일치'],
            ['13:58:02', '공유 드라이브 (PC)', '사내망', ('계정 잠김', RED, True)]]
    boxes = c.table((x0, y0), x1 - x0, ['시각', '접속 경로', '위치', '결과'], rows, [180, 300, 220, 300], 19)
    c.mark((boxes[0][0], boxes[0][1], boxes[-1][2], boxes[-1][3]), 1, 'right', 2)
    c.banner((x0, y0 + 330, x1, y0 + 430), '같은 기기·사내망에서 1분 간격으로 실패 = 저장된 예전 비밀번호. 해외·여러 IP에서 실패 = 도용 의심 → 정보보안팀 (IT-SEC-003-M 3.4).', 'info', 19)
    c.save(P('m_iam_fail.png'))


@fig('m_iam_mfa.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '계정 관리 콘솔 (가상) — MFA 기기 관리', IAM_MENU, 3)
    rows = [['Android (SM-****)', '2025-03-02', '2026-10-10 18:22', ('세션 만료 반복', AMBER, True)]]
    boxes = c.table((x0, y0), x1 - x0, ['기기', '등록일', '마지막 사용', '상태'], rows, [300, 200, 260, 260], 19)
    c.mark(boxes[0], 1, 'bottom', 2)
    b1 = c.button((x0, y0 + 150), '기기 등록 해제', 'danger', 20)
    b2 = c.button((b1[2] + 14, y0 + 150), '재등록 링크 발송', 'primary', 20)
    b3 = c.button((b2[2] + 14, y0 + 150), '일회용 우회 코드 (팀장 승인)', 'plain', 20)
    c.mark((b1[0], b1[1], b2[2], b2[3]), 2, 'bottom')
    c.text((x0, y0 + 290), '본인 확인: L2 (화상 확인 완료) · 확인자 기록 · 티켓 번호 기록', 19, TEXT, False, 'lm')
    c.banner((x0, y0 + 340, x1, y0 + 440), '우회 코드는 8자리·12시간·1회. 대면 또는 새로 확인된 휴대폰 문자로만 전달하고, 새 기기 등록 뒤 바로 폐기한다.', 'warn', 19)
    c.save(P('m_iam_mfa.png'))


@fig('m_sso_status.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'SSO 서비스 상태 (가상) — 시스템인프라팀', ['서비스 상태', '인증서', '배포 기록', '세션 설정'], 0)
    tiles = [('인증 성공률 (10분)', '12%', RED), ('로그인 실패 문의', '7건 / 10분', RED), ('서버 인증서 만료', '오늘 08:55', RED), ('마지막 배포', '어제 22:10', AMBER)]
    w = (x1 - x0 - 60) / 4
    for i, (k, v, col) in enumerate(tiles):
        b = (x0 + i * (w + 20), y0, x0 + i * (w + 20) + w, y0 + 140)
        c.rect(b, WHITE, LINE, 2, 10)
        c.text((b[0] + 18, b[1] + 34), k, 17, GREY, False, 'lm'); c.text((b[0] + 18, b[1] + 92), v, 28, col, True, 'lm')
    c.mark((x0, y0, x0 + 2 * w + 20, y0 + 140), 1, 'bottom', 4)
    c.mark((x0 + 2 * (w + 20), y0, x1 - 20, y0 + 140), 2, 'bottom', 4)
    c.banner((x0, y0 + 220, x1, y0 + 330), '여러 사용자가 동시에 로그인하지 못하면 개별 처리를 멈추고 ACC-04(P1) 대표 티켓을 만든다. 인증서 갱신 또는 직전 배포 롤백을 먼저 확인한다.', 'warn', 19)
    c.save(P('m_sso_status.png'))


@fig('m001_flow.png')
def _():
    flow(P('m001_flow.png'), [
        ('접수', '오류 코드(AUTH-1xx)와 화면, 주변 동료도 같은지 먼저 묻는다.'),
        ('여러 명?', '같은 증상이 여러 명이면 ACC-04 대형 장애로 바로 전환한다 (3.3).'),
        ('분류', '불일치 3.1 · 잠김 3.2 · 로그인 자체 불가 3.3 · 휴면 3.4 · 중지 3.5 · 세션 3.6'),
        ('본인 확인·처리', '셀프 안내 우선. 콘솔 작업은 본인 확인 수준에 맞춰 한다.'),
        ('확인·종결', '실제 로그인을 확인하고 FIN. 처리 기록 5장 항목을 남긴다.'),
    ], colors=[NAVY, (192, 57, 43), NAVY, ORANGE, GREEN])


@fig('m002_flow.png')
def _():
    flow(P('m002_flow.png'), [
        ('접수', '변경·만료·분실 중 무엇인지, 화면 메시지를 확인한다. 비밀번호 값은 묻지 않는다.'),
        ('셀프 안내', '규칙 안내, 셀프 포털 변경·초기화 안내로 끝나면 즉시 처리로 종결한다.'),
        ('셀프 불가', '등록 휴대폰을 쓸 수 없으면 본인 확인 L2 후 임시 비밀번호를 발급한다.'),
        ('기기 갱신', '휴대폰 메일 앱·자격 증명 관리자 등 저장된 비밀번호 갱신을 안내한다.'),
        ('확인·종결', '새 비밀번호 로그인을 확인하고 FIN.'),
    ], colors=[NAVY, GREEN, ORANGE, NAVY, GREEN])


@fig('m003_flow.png')
def _():
    flow(P('m003_flow.png'), [
        ('접수', '알림 안 옴·OTP 틀림·반복·기기 교체 중 무엇인지 확인한다.'),
        ('도용 신호 확인', '요청하지 않은 알림·실수 승인은 정보보안팀으로 (IT-SEC-003-M 3.2).'),
        ('셀프 안내', '알림 권한, 시간 자동 설정, 셀프 기기 변경을 안내한다.'),
        ('기기 초기화', '셀프가 안 되면 본인 확인 L2 후 기기 등록 해제·재등록 링크를 보낸다.'),
        ('확인·종결', '새 기기로 인증되는지 확인하고 FIN.'),
    ], colors=[NAVY, (192, 57, 43), GREEN, ORANGE, GREEN])


if __name__ == '__main__':
    import sys
    only = sys.argv[1:]
    for name, fn in FIGS.items():
        if not only or any(name.startswith(o) for o in only):
            fn()
            print('fig', name)
