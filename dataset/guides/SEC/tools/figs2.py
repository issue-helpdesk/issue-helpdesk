"""IT-SEC-002~004 그림. figs.py 의 부품을 쓰고 figs.FIGS 에 등록한다 (python figs.py 로 실행)."""
from figlib import Canvas, flow, NAVY, TEXT, GREY, LIGHT, LINE, RED, ORANGE, WHITE, BG, GREEN, AMBER, PINK
from figs import fig, P, console, dialog, mail_window, EDR_MENU, SSO_MENU

DESK = (214, 222, 233)
OKBG, OKLN = (227, 242, 232), (181, 214, 192)


def agent_window(c, box, active, title='보안 에이전트 (가상)'):
    return console(c, box, title, ['상태', '검사', '격리 파일', '기록'], active)


def checkbox(c, x, y, label):
    c.rect((x, y, x + 26, y + 26), NAVY, NAVY, 2, 4)
    c.d.line([(x + 6, y + 13), (x + 11, y + 19), (x + 20, y + 7)], fill=WHITE, width=4)
    c.text((x + 40, y + 13), label, 20, TEXT, False, 'lm')


def chips(c, x, y, items, w, fill, line, color, size=20, h=64, gap=20):
    for i, t in enumerate(items):
        bb = (x + i * (w + gap), y, x + i * (w + gap) + w, y + h)
        c.rect(bb, fill, line, 2, 8)
        c.text(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), t, size, color, True, 'mm')
    return (x, y, x + len(items) * (w + gap) - gap, y + h)


# ---------------- IT-SEC-002 ----------------
@fig('sec002_31_alert.png')
def _():
    c = Canvas(1400, 860)
    c.rect((30, 30, 1370, 830), DESK, DESK, 1, 10)
    t = (740, 60, 1300, 300)
    c.rect(t, WHITE, LINE, 2, 12)
    c.text((t[0] + 24, t[1] + 34), '보안 에이전트 (가상)', 19, GREY, True, 'lm')
    c.text((t[0] + 24, t[1] + 80), '위협이 탐지되어 격리되었습니다', 24, RED, True, 'lm')
    c.text((t[0] + 24, t[1] + 124), '파일: free_viewer_setup.exe', 19, TEXT, False, 'lm')
    c.text((t[0] + 24, t[1] + 158), '위치: C:\\Users\\(사용자)\\Downloads', 19, TEXT, False, 'lm')
    c.mark((t[0] + 14, t[1] + 104, t[2] - 20, t[1] + 176), 1, 'right')
    b = c.button((t[2] - 150, t[3] - 60), '자세히', 'plain', 19, (18, 8))
    c.mark(b, 2, 'bottom', 4)
    x0, y0, x1, y1 = agent_window(c, (60, 340, 1000, 810), 2)
    rows = [['free_viewer_setup.exe', '애드웨어', ('격리됨', GREEN, True)]]
    boxes = c.table((x0, y0 + 10), x1 - x0, ['파일', '탐지 이름', '상태'], rows, [330, 200, 160], 19)
    c.mark(boxes[0], 3, 'bottom', 2)
    b = c.button((x0, y0 + 200), '전체 검사', 'primary', 19)
    c.mark(b, 4, 'right')
    c.save(P('sec002_31_alert.png'))


@fig('sec002_32_quarantine.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = agent_window(c, (30, 30, 860, 830), 2)
    rows = [['월간_정산_매크로.xlsm', '매크로 행위', ('격리됨', GREEN, True)],
            ['free_viewer_setup.exe', '애드웨어', ('격리됨', GREEN, True)]]
    boxes = c.table((x0, y0 + 10), x1 - x0 - 60, ['파일', '탐지 이름', '상태'], rows, [260, 150, 120], 18)
    c.mark(boxes[0], 1, 'right', 2)
    c.text((x0, y0 + 200), '경로: D:\\업무\\정산\\월간_정산_매크로.xlsm', 18, TEXT, False, 'lm')
    c.text((x0, y0 + 236), '탐지 시각: 2026-10-15 09:41', 18, TEXT, False, 'lm')
    c.banner((x0, y0 + 290, x1, y0 + 390), '격리 해제·예외 추가는 사용자가 할 수 없습니다. 보안 프로그램을 끄거나 지우지 않습니다.', 'warn', 19)
    cx0, cy0, cx1, cy1 = c.window((890, 30, 1370, 830), 'ITssue 챗봇')
    b1 = (cx0 + 50, cy0 + 10, cx1, cy0 + 270)
    c.rect(b1, LIGHT, LIGHT, 1, 14)
    c.wrap((b1[0] + 16, b1[1] + 14), '업무 파일 격리 예외 검토 요청합니다.\n파일: 월간_정산_매크로.xlsm\n경로: D:\\업무\\정산\n용도: 팀 월간 정산 (매월 사용)\n마감: 오늘 17:00',
           b1[2] - b1[0] - 32, 18, TEXT)
    c.mark(b1, 2, 'bottom', 4)
    b2 = (cx0, cy0 + 330, cx1 - 50, cy0 + 470)
    c.rect(b2, WHITE, LINE, 2, 14)
    c.wrap((b2[0] + 16, b2[1] + 14), '정보보안팀 담당자에게 예외 검토 요청(티켓)을 넘겼습니다. 결과는 알림으로 보내 드립니다.', b2[2] - b2[0] - 32, 18, TEXT)
    c.save(P('sec002_32_quarantine.png'))


@fig('sec002_33_tray.png')
def _():
    c = Canvas(1400, 860)
    c.rect((30, 30, 1370, 830), DESK, DESK, 1, 10)
    d = dialog(c, (80, 90, 660, 380), '설치 프로그램', ['설치 중 오류가 발생했습니다. (코드 1603)', '이미 설치된 구성 요소가 있습니다.'], [('닫기', 'plain')])
    c.mark(d['닫기'], 1, 'bottom')
    c.d.rectangle((30, 760, 1370, 830), fill=(32, 36, 44))
    ic = (1160, 772, 1206, 818)
    c.d.rounded_rectangle(ic, 8, fill=GREEN)
    c.text(((ic[0] + ic[2]) / 2, (ic[1] + ic[3]) / 2), '◆', 22, WHITE, True, 'mm')
    c.text((1240, 795), '10:42', 20, WHITE, False, 'lm')
    c.mark(ic, 2, 'left', 6)
    pop = (840, 360, 1340, 680)
    c.rect(pop, WHITE, LINE, 2, 12)
    c.text((pop[0] + 24, pop[1] + 40), '보안 에이전트 (가상)', 21, NAVY, True, 'lm')
    st = (pop[0] + 24, pop[1] + 80, pop[0] + 250, pop[1] + 124)
    c.rect(st, OKBG, OKLN, 2, 8)
    c.text((st[0] + 16, st[1] + 22), '● 보호 중', 21, GREEN, True, 'lm')
    c.mark(st, 3, 'right')
    for i, t in enumerate(['정책: 최신 (오늘 08:30)', '마지막 검사: 어제 12:10', '관리 서버 연결: 정상']):
        c.text((pop[0] + 24, pop[1] + 170 + i * 40), t, 19, TEXT, False, 'lm')
    c.save(P('sec002_33_tray.png'))


@fig('sec002_34_infect.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 930, 830), '파일 탐색기 — D:\\업무')
    rows = [['고객사_제안서.docx.locked', '10:31'], ['월간_보고.xlsx.locked', '10:31'],
            ['회의록_1014.docx.locked', '10:32'], ['README_복구방법.txt', '10:32']]
    boxes = c.table((x0, y0), x1 - x0, ['이름', '수정한 시각'], [[(r[0], RED, True), r[1]] for r in rows], [600, 200], 19)
    c.mark((boxes[0][0], boxes[0][1], boxes[-1][2], boxes[-1][3]), 1, 'bottom', 2)
    c.banner((x0, y0 + 300, x1, y0 + 400), '파일 이름 뒤에 모르는 확장자가 붙고 열리지 않습니다. 안내문의 연락처로 연락하지 않습니다.', 'warn', 20)
    qx0, qy0, qx1, qy1 = c.window((970, 30, 1370, 420), '빠른 설정')
    w = c.button((qx0, qy0 + 10), 'Wi-Fi  끔', 'plain', 22, (30, 18))
    c.mark(w, 2, 'right')
    c.wrap((qx0, qy0 + 100), '랜선도 뽑습니다. 외장 디스크·공유 드라이브 연결도 끊습니다.', qx1 - qx0, 19, TEXT)
    c.banner((qx0, qy0 + 220, qx1, qy0 + 280), 'PC 전원은 끄지 않습니다', 'amber', 20)
    c.banner((970, 450, 1370, 580), '다른 전화로 정보보안팀 내선 1119 (가상)에 바로 연락합니다.', 'info', 20)
    c.save(P('sec002_34_infect.png'))


@fig('m_edr_exception.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'EDR 관리 콘솔 (가상)', EDR_MENU, 3)
    c.text((x0, y0 + 20), '격리 파일 분석: 월간_정산_매크로.xlsm', 23, TEXT, True, 'lm')
    rows = [['해시 (SHA-256)', '7c1e…9a40'], ['평판 조회', ('알려진 악성 아님', GREEN, True)],
            ['격리 환경 실행', '외부 연결 없음 · 파일 생성 없음'], ['판정', ('오탐 (매크로 행위 기반)', GREEN, True)]]
    boxes = c.table((x0, y0 + 60), x1 - x0, ['항목', '결과'], rows, [260, 700], 19)
    c.mark((boxes[1][0], boxes[1][1], boxes[3][2], boxes[3][3]), 1, 'right', 2)
    c.text((x0, y0 + 330), '예외 등록', 22, NAVY, True, 'lm')
    f1 = c.field((x0, y0 + 360), 400, '범위', '이 해시만 (경로 예외 없음)', 19, 110)
    c.field((x0, y0 + 420), 400, '대상', 'PC-FIN-0233 (요청자)', 19, 110)
    c.field((x0, y0 + 480), 400, '티켓', 'INQ-2026-00000', 19, 110)
    b1 = c.button((x0 + 620, y0 + 420), '예외 등록', 'primary', 21)
    b2 = c.button((b1[2] + 16, y0 + 420), '파일 복원', 'ok', 21)
    c.mark((x0 - 4, f1[1], f1[2], f1[3]), 2, 'right', 4)
    c.mark((b1[0], b1[1], b2[2], b2[3]), 3, 'bottom')
    c.save(P('m_edr_exception.png'))


@fig('m_edr_devices.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'EDR 관리 콘솔 (가상)', EDR_MENU, 0)
    c.field((x0, y0 + 4), 300, 'PC 이름', 'PC-SALES-0158', 19, 90)
    rows = [['PC-SALES-0158', '영업2팀 양OO', ('보호 중', GREEN, True), '오늘 10:40', '최신']]
    boxes = c.table((x0, y0 + 80), x1 - x0, ['PC 이름', '사용자', '상태', '마지막 연결', '정책'], rows, [230, 200, 160, 200, 150], 19)
    c.mark(boxes[0], 1, 'bottom', 2)
    c.text((x0, y0 + 260), '설치 기록', 22, NAVY, True, 'lm')
    rows2 = [['10:38', '설치 시작'], ['10:41', '구성 요소 설치 완료'],
             ['10:41', ('설치 프로그램 오류 1603 (이미 설치됨)', AMBER, True)], ['10:42', ('보호 시작', GREEN, True)]]
    b2 = c.table((x0, y0 + 290), x1 - x0, ['시각', '내용'], rows2, [160, 700], 19)
    c.mark(b2[2], 2, 'right', 2)
    c.save(P('m_edr_devices.png'))


@fig('m002_flow.png')
def _():
    flow(P('m002_flow.png'), [
        ('접수', '알림 화면 캡처, 파일 이름·경로, PC 이름을 받는다.'),
        ('감염 신호 확인', '알림 뒤 PC 이상·모르는 프로세스·확장자 변경이 있으면 바로 3.4로 넘긴다.'),
        ('분류', '자동 격리 3.1 · 업무 파일 격리 3.2 · 설치·상태 3.3 · 감염 의심 3.4'),
        ('정보보안팀 조치', '격리 확인·전체 검사, 해시 분석·예외 등록, 원격 격리·제거'),
        ('회신·종결', '결과와 사용자가 할 일을 안내하고 FIN. 예외는 범위·대상을 기록한다.'),
    ], colors=[NAVY, ORANGE, NAVY, (192, 57, 43), GREEN])


# ---------------- IT-SEC-003 ----------------
@fig('sec003_31_loginalert.png')
def _():
    c = Canvas(1400, 860)
    bx = mail_window(c, (30, 30, 1370, 830), '[보안 알림] 새로운 위치에서 로그인했습니다', '통합 로그인 (가상)',
                     'no-reply@hanwha-ict.example', '2026-10-15 03:14',
                     ['회원님의 계정으로 새로운 위치에서 로그인했습니다.', '시각: 2026-10-15 03:12   위치: 해외   기기: 알 수 없는 기기',
                      ('button', '본인이 아니면 여기를 눌러 확인')], toolbar=('답장', '전달', '삭제'))
    c.mark(bx['lines'][1], 1, 'right')
    lb = bx['link']
    c.d.line((lb[0] - 4, lb[1] - 4, lb[2] + 4, lb[3] + 4), fill=RED, width=5)
    c.d.line((lb[2] + 4, lb[1] - 4, lb[0] - 4, lb[3] + 4), fill=RED, width=5)
    c.mark(lb, 2, 'right')
    c.banner((bx['mx'], 560, 1340, 680), '알림 메일의 링크는 누르지 않습니다. 비밀번호 재설정 포털 주소를 직접 입력해 비밀번호를 바꾸고, 정보보안팀 내선 1119 (가상)에 알립니다.', 'info', 20)
    c.save(P('sec003_31_loginalert.png'))


@fig('sec003_32_mfa.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.phone((120, 20, 560, 840), '인증 앱 (가상)')
    c.text(((x0 + x1) / 2, y0 + 30), '로그인 요청을 승인할까요?', 23, TEXT, True, 'mm')
    info = (x0, y0 + 80, x1, y0 + 300)
    c.rect(info, LIGHT, LIGHT, 1, 12)
    for i, (k, v) in enumerate([('시각', '03:12'), ('위치', '해외'), ('기기', '알 수 없는 기기'), ('서비스', '통합 로그인')]):
        c.text((x0 + 20, y0 + 116 + i * 46), k, 19, GREY, False, 'lm')
        c.text((x0 + 120, y0 + 116 + i * 46), v, 20, TEXT, True, 'lm')
    c.mark(info, 1, 'right', 4)
    dn = c.button((x0 + 10, y0 + 360), '  거부  ', 'danger', 24, (36, 16))
    c.button((dn[2] + 30, y0 + 360), '  승인  ', 'plain', 24, (36, 16))
    c.mark(dn, 2, 'bottom')
    c.banner((640, 120, 1340, 300), '내가 로그인하지 않았는데 온 요청은 [거부]합니다. 요청이 반복되면 누군가 비밀번호를 알고 있다는 뜻입니다.', 'warn', 21)
    c.banner((640, 340, 1340, 500), '실수로 [승인]했다면 바로 정보보안팀 내선 1119 (가상)에 전화하고 비밀번호도 바로 바꿉니다.', 'info', 21)
    c.save(P('sec003_32_mfa.png'))


@fig('sec003_33_overseas.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '정보보안 포털 (가상) — 해외 접속 사전 등록')
    f1 = c.field((x0 + 20, y0 + 30), 420, '출장 국가', '(국가 선택)', 20)
    f2 = c.field((x0 + 20, y0 + 96), 420, '기간', '2026-11-02 ~ 2026-11-06', 20)
    c.field((x0 + 20, y0 + 162), 420, '사용 기기', '업무 노트북, 휴대폰', 20)
    c.field((x0 + 20, y0 + 228), 420, '목적', '고객사 현장 지원', 20)
    c.mark((f1[0], f1[1], f2[2], f2[3]), 1, 'right')
    b = c.button((x0 + 190, y0 + 310), '신청', 'primary', 22, (40, 12))
    c.mark(b, 2, 'right')
    c.banner((x0 + 760, y0 + 30, x1 - 20, y0 + 230), '출장 전에 신청합니다. 정보보안팀이 확인한 뒤 등록한 기간 동안 해외 접속을 허용합니다. 기간이 끝나면 예외도 끝납니다.', 'info', 20)
    c.banner((x0 + 20, y0 + 420, x1 - 20, y0 + 510), '출장 중 추가 인증이 계속 나오면 인증 앱의 인증번호(OTP)로 로그인하고, ITssue 챗봇에 신청 번호를 알립니다.', 'amber', 20)
    c.save(P('sec003_33_overseas.png'))


@fig('sec003_34_lock.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 860, 830), '통합 로그인 (가상)')
    c.text(((x0 + x1) / 2, y0 + 50), '통합 로그인', 30, NAVY, True, 'mm')
    bn = (x0 + 40, y0 + 110, x1 - 40, y0 + 210)
    c.banner(bn, '계정이 잠겼습니다. 비밀번호를 5회 잘못 입력했습니다. 10분 뒤 자동으로 풀립니다.', 'warn', 21)
    c.mark(bn, 1, 'bottom', 2)
    c.field((x0 + 60, y0 + 300), 380, '사번', 'EMP-0000', 19, 110)
    c.field((x0 + 60, y0 + 364), 380, '비밀번호', '', 19, 110)
    rx0, ry0, rx1, ry1 = c.window((890, 30, 1370, 830), '먼저 확인')
    y = ry0
    for i, t in enumerate(['최근 비밀번호를 바꿨다면 휴대폰 메일 앱·PC에 저장된 예전 비밀번호부터 확인합니다.',
                           '바꾼 적이 없는데 잠김이 반복되면 도용을 의심합니다.',
                           '내가 바꾸지 않았는데 비밀번호가 바뀌어 있으면 바로 정보보안팀에 알립니다.']):
        c.badge((rx0 + 18, y + 16), i + 2)
        y = c.wrap((rx0 + 48, y), t, rx1 - rx0 - 50, 20, TEXT) + 26
    c.save(P('sec003_34_lock.png'))


@fig('sec003_35_accesslog.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '분석 서버 — 접근 기록 (가상)')
    R = lambda v: (v, RED, True)
    rows = [['10-14 18:02', 'dev_kim', '사내망', '로그인', '—'],
            [R('10-15 02:47'), R('svc_backup2'), R('외부 IP'), R('로그인'), '—'],
            [R('10-15 02:49'), R('svc_backup2'), R('외부 IP'), R('파일 내려받기'), R('분석결과_10월.zip')],
            ['10-15 09:05', 'dev_kim', '사내망', '로그인', '—']]
    boxes = c.table((x0, y0), x1 - x0, ['시각', '계정', '접속 위치', '행동', '대상'], rows, [190, 210, 190, 210, 380], 19)
    c.mark((boxes[1][0], boxes[1][1], boxes[2][2], boxes[2][3]), 1, 'right', 2)
    c.text((x0, y0 + 300), '하지 말 것', 22, RED, True, 'lm')
    chips(c, x0, y0 + 330, ['서버 재시작·로그 삭제', '계정·파일 임의 삭제', '혼자 조사·외부 공유'], 380, PINK, (231, 179, 166), RED)
    c.text((x0, y0 + 450), '할 일', 22, GREEN, True, 'lm')
    box = chips(c, x0, y0 + 480, ['화면·로그 캡처, 발견 시각 기록', '정보보안팀 1119 (가상) 신고', '이미 한 조치도 알리기'], 380, OKBG, OKLN, GREEN, 19)
    c.mark(box, 2, 'bottom', 4)
    c.save(P('sec003_35_accesslog.png'))


def loss_form(c, kind, extra):
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '정보보안 포털 (가상) — 장비 분실 신고')
    c.field((x0 + 20, y0 + 20), 420, '장비 종류', kind, 20)
    f2 = c.field((x0 + 20, y0 + 86), 420, '분실 시각', '2026-10-15 19:30 무렵', 20)
    f3 = c.field((x0 + 20, y0 + 152), 420, '분실 장소', '(장소)', 20)
    c.field((x0 + 20, y0 + 218), 420, '마지막 사용', '2026-10-15 18:10', 20)
    c.mark((f2[0], f2[1], f3[2], f3[3]), 1, 'right')
    y = y0 + 300
    for t in extra:
        checkbox(c, x0 + 190, y, t)
        y += 44
    b = c.button((x0 + 190, y + 20), '신고', 'danger', 22, (40, 12))
    c.mark(b, 2, 'right')
    return (x0, y0, x1, y1)


@fig('sec003_36_phone.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = loss_form(c, '휴대폰 (개인 휴대폰)', ['인증 앱이 설치되어 있음', '회사 메일·메신저 앱이 설치되어 있음'])
    c.banner((x0 + 760, y0 + 20, x1 - 20, y0 + 230), '신고하면 정보보안팀이 인증 앱 등록을 해제하고 회사 앱의 로그인을 끊습니다. 새 휴대폰 등록은 본인 확인 뒤 진행합니다.', 'info', 20)
    c.banner((x0 + 760, y0 + 260, x1 - 20, y0 + 340), '서비스데스크(내선 1000)에도 함께 알립니다.', 'amber', 20)
    c.save(P('sec003_36_phone.png'))


@fig('sec003_37_laptop.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = loss_form(c, '업무 노트북', ['저장된 업무 자료가 있음 (고객 자료 포함)', 'VPN·메일 자동 로그인 사용'])
    c.banner((x0 + 760, y0 + 20, x1 - 20, y0 + 230), '정보보안팀이 단말 관리로 원격 잠금을 하고, 필요하면 원격 초기화합니다. 분실 경위서를 작성합니다.', 'info', 20)
    c.banner((x0 + 760, y0 + 260, x1 - 20, y0 + 370), '찾았으면 켜지 말고 서비스데스크에 가져와 점검을 받은 뒤 씁니다.', 'amber', 20)
    c.save(P('sec003_37_laptop.png'))


@fig('m_sso_overseas.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'SSO 접속 기록 조회 (가상)', SSO_MENU, 3)
    rows = [['EMP-0000', '(출장 국가)', '11-02 ~ 11-06', '업무 노트북, 휴대폰', ('등록 대기', AMBER, True)]]
    boxes = c.table((x0, y0), x1 - x0, ['사번', '국가', '기간', '기기', '상태'], rows, [170, 200, 220, 300, 150], 19)
    c.mark(boxes[0], 1, 'bottom', 2)
    c.field((x0, y0 + 160), 420, '신청 번호', 'SEC-REQ-0000', 19, 140)
    c.field((x0, y0 + 220), 420, '종료', '기간 종료 시 자동 해제', 19, 140)
    b = c.button((x0 + 600, y0 + 190), '예외 등록', 'primary', 21)
    c.mark(b, 2, 'right')
    c.banner((x0, y0 + 320, x1, y0 + 410), '출장 기간 밖의 해외 접속, 등록하지 않은 기기의 접속은 계속 추가 인증 대상이다.', 'info', 20)
    c.save(P('m_sso_overseas.png'))


@fig('m_sso_fail.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'SSO 접속 기록 조회 (가상)', SSO_MENU, 1)
    c.text((x0, y0 + 16), '로그인 실패 기록 (최근 1시간)', 22, NAVY, True, 'lm')
    R = lambda v: (v, RED, True)
    rows = [['09:01', '사내망', '모바일 메일 앱', '비밀번호 불일치'], ['09:02', '사내망', '모바일 메일 앱', '비밀번호 불일치'],
            ['09:03', '사내망', '모바일 메일 앱', '비밀번호 불일치'],
            [R('09:20'), R('해외 IP A'), R('알 수 없음'), R('비밀번호 불일치')], [R('09:20'), R('해외 IP B'), R('알 수 없음'), R('비밀번호 불일치')]]
    boxes = c.table((x0, y0 + 50), x1 - x0, ['시각', '접속 위치', '기기', '결과'], rows, [140, 220, 300, 300], 19)
    c.mark((boxes[0][0], boxes[0][1], boxes[2][2], boxes[2][3]), 1, 'right', 2)
    c.mark((boxes[3][0], boxes[3][1], boxes[4][2], boxes[4][3]), 2, 'right', 2)
    c.banner((x0, y0 + 360, x0 + 520, y0 + 470), '① 같은 기기·1분 간격: 저장된 예전 비밀번호 → 계정·로그인 처리', 'info', 19)
    c.banner((x0 + 540, y0 + 360, x1, y0 + 470), '② 여러 해외 IP·짧은 시간: 대입 시도 → 도용 의심 처리', 'warn', 19)
    c.save(P('m_sso_fail.png'))


@fig('m_server_ir.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '침해 대응 기록 (가상)', ['초동 조치', '증거 보존', '로그 분석', '영향 범위', '보고'], 0)
    rows = [['계정·세션', 'svc_backup2 차단, 세션 종료', ('완료 02:58', GREEN, True)],
            ['서버', '네트워크 격리 (시스템인프라팀)', ('완료 03:05', GREEN, True)],
            ['증거', '메모리·디스크 이미지, 접근 로그 사본', ('진행 중', AMBER, True)],
            ['영향 범위', '내려받은 파일 목록·개인정보 포함 여부', ('대기', GREY, False)],
            ['보고', '정보보안팀장 · 개인정보 포함 시 법무팀', ('대기', GREY, False)]]
    boxes = c.table((x0, y0 + 10), x1 - x0, ['구분', '조치', '상태'], rows, [180, 560, 220], 19)
    c.mark((boxes[0][0], boxes[0][1], boxes[1][2], boxes[1][3]), 1, 'right', 2)
    c.mark(boxes[2], 2, 'right', 2)
    c.mark((boxes[3][0], boxes[3][1], boxes[4][2], boxes[4][3]), 3, 'right', 2)
    c.banner((x0, y0 + 330, x1, y0 + 430), '증거를 남기기 전에 서버를 재시작하거나 다시 설치하지 않는다. 격리는 네트워크 단위로 한다.', 'warn', 20)
    c.save(P('m_server_ir.png'))


@fig('m_mdm.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '단말 관리 콘솔 (가상)', ['장치 목록', '원격 잠금', '원격 초기화', '분실 기록'], 1)
    rows = [['NB-RND-0071', '연구소 정OO', '업무 노트북', '10-15 18:10', ('디스크 암호화 켜짐', GREEN, True)]]
    boxes = c.table((x0, y0 + 10), x1 - x0, ['장치', '사용자', '종류', '마지막 연결', '상태'], rows, [200, 180, 170, 180, 260], 19)
    c.mark(boxes[0], 1, 'bottom', 2)
    b1 = c.button((x0, y0 + 170), '원격 잠금', 'danger', 21)
    b2 = c.button((b1[2] + 16, y0 + 170), '원격 초기화', 'plain', 21)
    c.button((b2[2] + 16, y0 + 170), '연결 기록 보기', 'plain', 21)
    c.mark(b1, 2, 'bottom')
    c.banner((x0, y0 + 300, x1, y0 + 420), '원격 잠금은 장비가 다음에 연결될 때 적용된다. 연결 기록이 없으면 세션 종료·비밀번호 변경을 먼저 하고, 원격 초기화는 정보보안팀장 판단 후 실행한다.', 'info', 20)
    c.save(P('m_mdm.png'))


@fig('m003_flow.png')
def _():
    flow(P('m003_flow.png'), [
        ('신고 접수', '모르는 로그인·인증 알림, 무단 접근 흔적, 장비 분실은 즉시 이관 대상이다.'),
        ('초동 조치', '세션 종료·계정 차단, 분실 장비 원격 잠금, 침해 서버 네트워크 격리'),
        ('증거 보존', '로그·화면·장비 상태를 남긴다. 재시작·삭제 금지'),
        ('분석·영향 범위', '접속 기록과 내려받은 자료를 확인한다. 개인정보면 법정 기한을 판단한다.'),
        ('복구·보고', '비밀번호·MFA 재등록, 패치·재구축, 결과 회신과 보고'),
    ], colors=[(192, 57, 43), ORANGE, NAVY, NAVY, GREEN])


# ---------------- IT-SEC-004 ----------------
@fig('sec004_31_usb.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '정보보안 포털 (가상) — 이동식 저장매체 사용 신청')
    f1 = c.field((x0 + 20, y0 + 20), 460, '사용 목적', '고객사 납품 파일 전달', 20)
    f2 = c.field((x0 + 20, y0 + 86), 460, '사용 기간', '2026-10-16 ~ 2026-10-20 (최대 7일)', 20)
    c.field((x0 + 20, y0 + 152), 460, '매체', '회사 지급 USB (관리 번호)', 20)
    c.field((x0 + 20, y0 + 218), 460, '옮길 파일', '납품_산출물_v3.zip', 20)
    c.mark((f1[0], f1[1], f2[2], f2[3]), 1, 'right')
    checkbox(c, x0 + 190, y0 + 300, '보안 서약에 동의합니다 (목적 외 사용·개인 보관 금지)')
    c.mark((x0 + 190, y0 + 300, x0 + 800, y0 + 326), 2, 'right', 6)
    b = c.button((x0 + 190, y0 + 370), '신청 (팀장 승인 요청)', 'primary', 22, (30, 12))
    c.mark(b, 3, 'right')
    c.banner((x0 + 20, y0 + 480, x1 - 20, y0 + 570), '팀장 승인 → 정보보안팀 등록 후 쓸 수 있습니다. 기간이 끝나면 다시 차단됩니다.', 'info', 20)
    c.save(P('sec004_31_usb.png'))


@fig('sec004_32_dlp.png')
def _():
    c = Canvas(1400, 860)
    dialog(c, (40, 60, 760, 440), '외부 전송이 차단되었습니다',
           ['첨부한 파일에 개인정보가 들어 있습니다.', '파일: 행사_참석자_목록.xlsx', '감지: 휴대폰 번호 42건, 생년월일 42건', '개인정보를 가린 뒤 다시 보내 주세요.'],
           [('확인', 'primary')])
    c.mark((60, 160, 740, 250), 1, 'right', 4)
    x0, y0, x1, y1 = c.window((40, 480, 1360, 830), '마스킹 예시')
    rows = [['이름', '홍길동', '홍*동'], ['휴대폰 번호', '010-1234-5678', '010-****-5678'], ['생년월일', '1990-01-01', '1990-**-**']]
    boxes = c.table((x0, y0 - 6), x1 - x0, ['항목', '원본 (보내지 않음)', '마스킹 후'], rows, [300, 400, 400], 19, 44)
    c.mark((x0 + 700, boxes[0][1], x1, boxes[-1][3]), 2, 'right', 2)
    c.banner((800, 60, 1360, 330), '꼭 필요한 항목만 남기고 나머지는 지웁니다. 원본을 보내야 하면 정보보안 포털 (가상)에서 반출을 신청합니다 (팀장 승인).', 'info', 20)
    c.save(P('sec004_32_dlp.png'))


@fig('sec004_33_block.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '웹 브라우저')
    addr = (x0, y0, x1, y0 + 46)
    c.rect(addr, BG, LINE, 2, 20)
    c.text((x0 + 20, y0 + 23), 'https://reference-docs.example.net/manual', 19, TEXT, False, 'lm')
    c.mark(addr, 1, 'bottom', 4)
    c.text(((x0 + x1) / 2, y0 + 160), '이 사이트는 회사 보안 정책에 따라 차단되었습니다', 28, RED, True, 'mm')
    c.text(((x0 + x1) / 2, y0 + 220), '차단 분류: 파일 공유·저장 (가상)', 21, TEXT, False, 'mm')
    c.text(((x0 + x1) / 2, y0 + 260), '시각: 2026-10-15 14:05   ·   PC: PC-MKT-0040', 19, GREY, False, 'mm')
    c.mark((x0 + 330, y0 + 196, x1 - 330, y0 + 280), 2, 'right', 4)
    b = c.button((((x0 + x1) / 2) - 120, y0 + 330), '차단 해제 요청', 'primary', 22, (34, 14))
    c.mark(b, 3, 'right')
    c.banner((x0 + 120, y0 + 450, x1 - 120, y0 + 560), '업무 용도를 적어 요청합니다. 정보보안팀이 사이트 평판을 확인하고 1영업일 안에 처리합니다. 악성·피싱 분류 사이트는 해제하지 않습니다.', 'info', 20)
    c.save(P('sec004_33_block.png'))


@fig('sec004_34_ai.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = c.window((30, 30, 1370, 830), '정보보안 포털 (가상) — 승인된 생성형 AI 도구')
    rows = [['사내 AI 도우미 (가상)', '사내 문서 요약·초안 작성', ('사용 가능', GREEN, True)],
            ['외부 AI 서비스 A (가상)', '공개 정보 검색·번역', ('조건부', AMBER, True)],
            ['그 밖의 외부 AI 서비스', '—', ('사용 안 함', RED, True)]]
    boxes = c.table((x0, y0), x1 - x0, ['도구', '쓸 수 있는 업무', '상태'], rows, [380, 560, 280], 20, 52)
    c.mark((boxes[0][0], boxes[0][1], boxes[-1][2], boxes[-1][3]), 1, 'right', 2)
    c.text((x0, y0 + 270), '어떤 도구에도 입력하지 않는 정보', 22, RED, True, 'lm')
    box = chips(c, x0, y0 + 300, ['고객 정보', '개인정보', '소스코드', '비밀번호·인증번호', 'API Key'], 230, PINK, (231, 179, 166), RED)
    c.mark(box, 2, 'bottom', 4)
    c.banner((x0, y0 + 450, x1, y0 + 550), '이미 입력했다면 지우는 것으로 끝나지 않습니다. 입력한 도구·시각·내용을 정리해 정보보안팀 내선 1119 (가상)에 알립니다.', 'warn', 20)
    c.save(P('sec004_34_ai.png'))


@fig('m_dlp_exception.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), 'DLP 관리 콘솔 (가상)', ['매체 예외', '반출 예외', '차단 기록', '만료 예정'], 0)
    rows = [['EMP-0000', '고객사 납품 파일 전달', '10-16 ~ 10-20', ('팀장 승인', GREEN, True), ('서약 완료', GREEN, True)]]
    boxes = c.table((x0, y0), x1 - x0, ['신청자', '목적', '기간', '승인', '보안 서약'], rows, [160, 330, 200, 150, 150], 19)
    c.mark((boxes[0][0] + 690, boxes[0][1], boxes[0][2], boxes[0][3]), 1, 'bottom', 2)
    c.field((x0, y0 + 170), 380, '허용 범위', '지정 USB (관리 번호)만', 19, 120)
    c.field((x0, y0 + 230), 380, '기간', '최대 7일', 19, 120)
    c.field((x0, y0 + 290), 380, '기록', '복사한 파일 이름 기록', 19, 120)
    b = c.button((x0 + 620, y0 + 230), '예외 등록', 'primary', 21)
    c.mark(b, 2, 'right')
    c.banner((x0, y0 + 400, x1, y0 + 490), '[만료 예정]에서 기간이 끝나는 예외를 확인한다. 연장은 새 신청으로만 받는다.', 'info', 20)
    c.save(P('m_dlp_exception.png'))


@fig('m_webfilter.png')
def _():
    c = Canvas(1400, 860)
    x0, y0, x1, y1 = console(c, (30, 30, 1370, 830), '웹 필터 관리 콘솔 (가상)', ['차단 기록', 'URL 조회', '예외 목록', '정책'], 1)
    c.field((x0, y0 + 4), 520, 'URL', 'reference-docs.example.net', 19, 70)
    rows = [['분류', '파일 공유·저장'], ['평판', ('낮은 위험', GREEN, True)], ['악성·피싱 기록', ('없음', GREEN, True)], ['요청 사유', '제품 기술 문서 확인 (업무)']]
    boxes = c.table((x0, y0 + 80), x1 - x0, ['항목', '결과'], rows, [260, 700], 19)
    c.mark((boxes[1][0], boxes[1][1], boxes[2][2], boxes[2][3]), 1, 'right', 2)
    c.field((x0, y0 + 340), 420, '예외 범위', '이 도메인 · 요청 부서', 19, 120)
    b = c.button((x0 + 640, y0 + 340), 'URL 예외 등록', 'primary', 21)
    c.mark(b, 2, 'right')
    c.save(P('m_webfilter.png'))


@fig('m004_flow.png')
def _():
    flow(P('m004_flow.png'), [
        ('접수', '신청 내용(목적·기간·대상)과 승인 여부를 확인한다. 정책 문의는 안내로 끝낸다.'),
        ('대체 방법 확인', '파일 공유 링크, 마스킹처럼 예외 없이 해결되는지 먼저 본다.'),
        ('승인 확인', '매체·반출은 팀장 승인과 보안 서약이 있어야 한다.'),
        ('예외 등록', '범위는 가장 좁게, 기간은 최대 7일. 티켓 번호를 남긴다.'),
        ('회신·만료 관리', '결과를 안내하고 FIN. 만료 예정 예외를 확인한다.'),
    ], colors=[NAVY, NAVY, AMBER, ORANGE, GREEN])
