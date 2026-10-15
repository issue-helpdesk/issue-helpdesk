"""HW 사용자 가이드에 넣는 화면 예시 그림을 만든다.

실제 화면 캡처가 아니라 Pillow로 그린 가상 화면이다. 가이드의 '조치 방법' 단계 번호와
같은 번호를 노란 딱지로 붙이고, 눌러야 하는 자리는 빨간 상자로 표시한다.

실행: python dataset/guides/HW/tools/make_figures.py  (Windows, 맑은 고딕 필요)
결과: dataset/guides/HW/images/*.png
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "images"
FONT_DIR = Path("C:/Windows/Fonts")

RED = "#E60012"
YELLOW = "#FFE600"
BLUE = "#0067C0"
INK = "#1B1B1B"
SUB = "#5F6368"
LINE = "#D0D0D0"
PANEL = "#F3F3F3"
NAVY = "#1F3864"

W, H = 2400, 1040


def font(size, bold=False):
    return ImageFont.truetype(str(FONT_DIR / ("malgunbd.ttf" if bold else "malgun.ttf")), size)


class Fig:
    def __init__(self):
        self.im = Image.new("RGB", (W, H), "white")
        self.d = ImageDraw.Draw(self.im)
        self.marks = []  # 주석은 화면을 다 그린 뒤 맨 위에 그린다

    # --- 기본 도형 ---
    def text(self, x, y, t, size=26, fill=INK, bold=False, anchor="la"):
        self.d.text((x, y), t, font=font(size, bold), fill=fill, anchor=anchor)

    def rect(self, x, y, w, h, fill=None, outline=None, width=2, r=0):
        self.d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=outline, width=width)

    def hline(self, x, y, w, fill=LINE):
        self.d.line([x, y, x + w, y], fill=fill, width=2)

    # --- 화면 부품 ---
    def window(self, x, y, w, h, title, bg="white", bar="#FFFFFF", fg=INK):
        self.rect(x + 6, y + 8, w, h, fill="#DADADA", r=14)
        self.rect(x, y, w, h, fill=bg, outline="#8A8A8A", width=2, r=14)
        self.d.rounded_rectangle([x + 2, y + 2, x + w - 2, y + 58], radius=12, fill=bar)
        self.d.rectangle([x + 2, y + 40, x + w - 2, y + 58], fill=bar)
        self.hline(x + 2, y + 58, w - 4)
        self.text(x + 24, y + 30, title, 24, fg, anchor="lm")
        cx = x + w - 150
        self.d.line([cx, y + 30, cx + 18, y + 30], fill=fg, width=2)
        self.d.rectangle([cx + 50, y + 21, cx + 68, y + 39], outline=fg, width=2)
        self.d.line([cx + 100, y + 21, cx + 118, y + 39], fill=fg, width=2)
        self.d.line([cx + 118, y + 21, cx + 100, y + 39], fill=fg, width=2)

    def button(self, x, y, w, h, label, primary=False, size=24):
        self.rect(x, y, w, h, fill=BLUE if primary else "#FBFBFB", outline=BLUE if primary else "#B5B5B5", r=8)
        self.text(x + w / 2, y + h / 2, label, size, "white" if primary else INK, anchor="mm")
        return (x, y, w, h)

    def checkbox(self, x, y, checked, size=30):
        self.rect(x, y, size, size, fill=BLUE if checked else "white", outline=BLUE if checked else "#7A7A7A", r=5)
        if checked:
            self.d.line([x + 6, y + 16, x + 13, y + 23, x + 25, y + 8], fill="white", width=4)

    def radio(self, x, y, checked, size=30):
        self.d.ellipse([x, y, x + size, y + size], fill="white", outline=BLUE if checked else "#7A7A7A", width=3)
        if checked:
            self.d.ellipse([x + 8, y + 8, x + size - 8, y + size - 8], fill=BLUE)

    def field(self, x, y, w, h, value="", hint=False):
        self.rect(x, y, w, h, fill="white", outline="#9A9A9A", r=6)
        self.text(x + 16, y + h / 2, value, 24, SUB if hint else INK, anchor="lm")

    # --- 주석 ---
    def mark(self, box, pad=10):
        x, y, w, h = box
        self.marks.append(("box", (x - pad, y - pad, w + 2 * pad, h + 2 * pad)))

    def label(self, x, y, t, anchor="la"):
        self.marks.append(("label", (x, y, t, anchor)))

    def flow(self, x1, x2, y=None):
        """화면과 화면 사이의 진행 화살표."""
        y = y or 480
        self.d.polygon([(x1, y - 16), (x2 - 34, y - 16), (x2 - 34, y - 40), (x2, y), (x2 - 34, y + 40),
                        (x2 - 34, y + 16), (x1, y + 16)], fill=NAVY)

    def save(self, name):
        for kind, a in self.marks:
            if kind == "box":
                x, y, w, h = a
                self.d.rectangle([x, y, x + w, y + h], outline=RED, width=7)
        for kind, a in self.marks:
            if kind == "label":
                x, y, t, anchor = a
                f = font(27, True)
                l, tp, r, b = self.d.textbbox((x, y), t, font=f, anchor=anchor)
                self.d.rectangle([l - 12, tp - 9, r + 12, b + 9], fill=YELLOW, outline="#8A7A00", width=2)
                self.d.text((x, y), t, font=f, fill="#000000", anchor=anchor)
        OUT.mkdir(parents=True, exist_ok=True)
        self.im.save(OUT / name, optimize=True)
        print("saved", name)


# ---------------------------------------------------------------- IT-HW-001 3.1
def hw001_3_1():
    f = Fig()
    y0, ph = 30, 920
    # 1) 파일 탐색기
    x = 20
    f.window(x, y0, 730, ph, "내 PC - 파일 탐색기")
    f.rect(x + 2, y0 + 60, 726, 60, fill=PANEL)
    f.text(x + 30, y0 + 90, "←   →   ↑      내 PC  >", 24, SUB, anchor="lm")
    f.rect(x + 2, y0 + 120, 200, ph - 124, fill="#FAFAFA")
    for i, n in enumerate(["홈", "바탕 화면", "다운로드", "문서", "내 PC"]):
        if n == "내 PC":
            f.rect(x + 12, y0 + 136 + i * 56, 180, 46, fill="#DCEBFA", r=6)
        f.text(x + 30, y0 + 159 + i * 56, n, 24, anchor="lm")
    f.text(x + 230, y0 + 160, "장치 및 드라이브", 24, SUB, anchor="lm")
    f.hline(x + 230, y0 + 186, 470)
    dx, dy = x + 230, y0 + 210
    f.rect(dx, dy, 470, 130, fill="#E8F1FB", outline="#99C2EE", r=6)
    f.rect(dx + 18, dy + 34, 76, 56, fill="#6E7B8B", r=6)
    f.rect(dx + 28, dy + 70, 20, 10, fill="#9CE29C")
    f.text(dx + 112, dy + 30, "로컬 디스크 (C:)", 25, anchor="lm")
    f.rect(dx + 112, dy + 54, 330, 24, fill="#E6E6E6", outline="#BDBDBD")
    f.rect(dx + 112, dy + 54, 317, 24, fill="#DA3B01")
    f.text(dx + 112, dy + 102, "237GB 중 9.1GB 사용 가능", 22, SUB, anchor="lm")
    f.label(dx, dy + 150, "빨간색 = 공간 부족")
    # 오른쪽 클릭 메뉴
    mx, my = x + 380, y0 + 400
    f.rect(mx + 5, my + 6, 320, 330, fill="#D5D5D5", r=10)
    f.rect(mx, my, 320, 330, fill="white", outline="#A0A0A0", r=10)
    for i, n in enumerate(["열기", "새 창에서 열기", "빠른 실행에 고정", "포맷...", "속성"]):
        if n == "속성":
            f.hline(mx + 10, my + 14 + i * 60 - 2, 300)
            f.rect(mx + 8, my + 20 + i * 60, 304, 52, fill="#E5F1FB", r=6)
            f.mark((mx + 8, my + 20 + i * 60, 304, 52), pad=4)
        f.text(mx + 28, my + 46 + i * 60, n, 25, anchor="lm")
    f.label(x + 40, y0 + 760, "1. C드라이브 마우스 오른쪽 클릭 > [속성]")
    f.flow(762, 823)

    # 2) 속성
    x = 835
    f.window(x, y0, 730, ph, "로컬 디스크 (C:) 속성", bg=PANEL)
    for i, n in enumerate(["일반", "도구", "하드웨어", "보안"]):
        sel = i == 0
        f.rect(x + 24 + i * 150, y0 + 78, 146, 50, fill="white" if sel else "#E6E6E6", outline="#B5B5B5")
        f.text(x + 97 + i * 150, y0 + 103, n, 23, anchor="mm")
    f.rect(x + 24, y0 + 127, 682, 680, fill="white", outline="#B5B5B5")
    f.text(x + 50, y0 + 175, "종류:  로컬 디스크", 24, anchor="lm")
    f.text(x + 50, y0 + 220, "파일 시스템:  NTFS", 24, anchor="lm")
    f.hline(x + 50, y0 + 255, 630)
    f.rect(x + 50, y0 + 285, 26, 26, fill=BLUE)
    f.text(x + 92, y0 + 298, "사용 중인 공간", 24, anchor="lm")
    f.text(x + 680, y0 + 298, "227.9GB", 24, anchor="rm")
    f.rect(x + 50, y0 + 335, 26, 26, fill="#C9C9C9")
    f.text(x + 92, y0 + 348, "사용 가능한 공간", 24, anchor="lm")
    f.text(x + 680, y0 + 348, "9.1GB", 24, RED, True, anchor="rm")
    f.hline(x + 50, y0 + 385, 630)
    f.text(x + 92, y0 + 418, "용량", 24, anchor="lm")
    f.text(x + 680, y0 + 418, "237GB", 24, anchor="rm")
    cx, cy, r = x + 220, y0 + 610, 130
    f.d.pieslice([cx - r, cy - r, cx + r, cy + r], -90, 256, fill=BLUE, outline="white")
    f.d.pieslice([cx - r, cy - r, cx + r, cy + r], 256, 270, fill="#C9C9C9", outline="white")
    f.text(cx, cy + r + 30, "드라이브 C:", 22, SUB, anchor="mm")
    b = f.button(x + 440, y0 + 580, 230, 60, "디스크 정리")
    f.mark(b)
    f.label(x + 400, y0 + 520, "1. [디스크 정리] 실행")
    f.button(x + 290, y0 + 836, 130, 54, "확인")
    f.button(x + 434, y0 + 836, 130, 54, "취소")
    f.button(x + 578, y0 + 836, 130, 54, "적용")
    f.flow(1577, 1638)

    # 3) 디스크 정리
    x = 1650
    f.window(x, y0, 730, ph, "디스크 정리: (C:)", bg=PANEL)
    f.text(x + 30, y0 + 105, "디스크 정리를 사용하면 (C:)에서 최대 6.2GB의", 23, anchor="lm")
    f.text(x + 30, y0 + 141, "디스크 공간을 확보할 수 있습니다.", 23, anchor="lm")
    f.text(x + 30, y0 + 205, "삭제할 파일:", 24, anchor="lm")
    f.rect(x + 30, y0 + 232, 670, 380, fill="white", outline="#9A9A9A")
    rows = [("다운로드한 프로그램 파일", "0바이트", True), ("임시 인터넷 파일", "312MB", True),
            ("휴지통", "1.8GB", True), ("임시 파일", "3.9GB", True), ("미리 보기 사진", "24.1MB", False)]
    for i, (n, s, c) in enumerate(rows):
        ry = y0 + 252 + i * 70
        f.checkbox(x + 50, ry + 8, c)
        f.text(x + 100, ry + 23, n, 25, anchor="lm")
        f.text(x + 680, ry + 23, s, 24, SUB, anchor="rm")
    f.mark((x + 44, y0 + 252 + 2 * 70, 646, 116), pad=4)
    f.label(x + 44, y0 + 640, "2. '임시 파일', '휴지통' 등을 선택")
    f.text(x + 30, y0 + 720, "확보되는 디스크 공간 합계:", 24, anchor="lm")
    f.text(x + 700, y0 + 720, "6.0GB", 24, anchor="rm")
    b = f.button(x + 400, y0 + 836, 140, 54, "확인", primary=True)
    f.mark(b)
    f.button(x + 560, y0 + 836, 140, 54, "취소")
    f.label(x + 220, y0 + 848, "2. [확인]")
    f.save("IT-HW-001_fig3.1.png")


# ---------------------------------------------------------------- IT-HW-001 3.2
def _taskmgr(f, x, y0, w, ph, tab):
    f.window(x, y0, w, ph, "작업 관리자")
    f.rect(x + 2, y0 + 60, 210, ph - 64, fill="#F7F7F7")
    for i, n in enumerate(["프로세스", "성능", "앱 기록", "시작 앱", "사용자"]):
        if n == tab:
            f.rect(x + 12, y0 + 80 + i * 62, 190, 50, fill="#E3E3E3", r=6)
            f.rect(x + 12, y0 + 90 + i * 62, 6, 30, fill=BLUE, r=3)
        f.text(x + 36, y0 + 105 + i * 62, n, 24, anchor="lm")
    return x + 232, y0 + 80


def hw001_3_2():
    f = Fig()
    y0, ph = 30, 920
    # 1) 프로세스
    x, w = 20, 1130
    cx, cy = _taskmgr(f, x, y0, w, ph, "프로세스")
    f.text(cx, cy + 20, "프로세스", 30, bold=True, anchor="lm")
    cols = [("CPU", "34%", "#FFF4CE"), ("메모리", "91%", "#F7B9A8"), ("디스크", "100%", "#F1707B")]
    hx = cx + 420
    f.text(cx, cy + 112, "이름", 23, SUB, anchor="lm")
    for i, (n, v, c) in enumerate(cols):
        f.rect(hx + i * 150, cy + 60, 146, 80, fill=c)
        f.text(hx + i * 150 + 132, cy + 82, v, 28, bold=True, anchor="rm")
        f.text(hx + i * 150 + 132, cy + 120, n, 22, SUB, anchor="rm")
    f.mark((hx, cy + 60, 446, 80), pad=6)
    rows = [("스프레드시트 (4)", "6.2%", "1,840MB", "2.1MB/s"), ("웹 브라우저 (18)", "11.4%", "2,950MB", "0.4MB/s"),
            ("사내 메신저", "1.1%", "410MB", "0.1MB/s"), ("클라우드 동기화", "8.9%", "380MB", "38.6MB/s"),
            ("사내 보안 에이전트", "5.8%", "520MB", "12.4MB/s"), ("화상회의", "0.3%", "210MB", "0MB/s")]
    shade = ["#FFF9E5", "#FBD9CF", "#F9C9C0"]
    for i, r in enumerate(rows):
        ry = cy + 150 + i * 64
        f.hline(cx, ry + 62, w - 260)
        f.rect(cx + 4, ry + 16, 30, 30, fill="#8FA8C8", r=6)
        f.text(cx + 50, ry + 31, r[0], 24, anchor="lm")
        for j in range(3):
            f.rect(hx + j * 150, ry + 2, 146, 58, fill=shade[j])
            f.text(hx + j * 150 + 132, ry + 31, r[j + 1], 23, anchor="rm")
    f.label(cx, cy + 600, "2. 작업 관리자(Ctrl+Shift+Esc)에서")
    f.label(cx, cy + 660, "   CPU·메모리·디스크 사용률 확인")
    f.flow(1162, 1223)

    # 2) 시작 앱
    x, w = 1235, 1145
    cx, cy = _taskmgr(f, x, y0, w, ph, "시작 앱")
    f.text(cx, cy + 20, "시작 앱", 30, bold=True, anchor="lm")
    b = f.button(x + w - 220, cy - 6, 190, 54, "사용 안 함")
    f.mark(b)
    c = [cx, cx + 330, cx + 560, cx + 720]
    for i, n in enumerate(["이름", "게시자", "상태", "시작 시 영향"]):
        f.text(c[i], cy + 110, n, 23, SUB, anchor="lm")
    f.hline(cx, cy + 136, w - 260)
    rows = [("사내 메신저", "사내 배포", "사용", "높음"), ("클라우드 동기화", "사내 배포", "사용", "높음"),
            ("음악 플레이어", "개인 설치", "사용", "중간"), ("화상회의 도우미", "사내 배포", "사용", "중간"),
            ("사내 보안 에이전트", "정보보안팀", "사용", "높음")]
    for i, r in enumerate(rows):
        ry = cy + 146 + i * 70
        if i == 2:
            f.rect(cx - 10, ry, w - 250, 66, fill="#CCE4F7")
            f.mark((cx - 10, ry, w - 250, 66), pad=2)
        f.rect(cx + 4, ry + 18, 30, 30, fill="#8FA8C8", r=6)
        f.text(cx + 50, ry + 33, r[0], 24, anchor="lm")
        for j in range(1, 4):
            f.text(c[j], ry + 33, r[j], 24, anchor="lm")
        f.hline(cx, ry + 68, w - 260)
    f.label(cx, cy + 520, "3. 업무에 필요 없는 프로그램 선택 > [사용 안 함]")
    f.rect(cx - 10, cy + 590, w - 250, 70, fill="#FDE7E9", outline=RED, r=8)
    f.text(cx + 10, cy + 625, "보안 프로그램(사내 보안 에이전트)은 바꾸지 않습니다.", 25, "#A80000", True, anchor="lm")
    f.save("IT-HW-001_fig3.2.png")


# ---------------------------------------------------------------- IT-HW-001 3.6
def hw001_3_6():
    f = Fig()
    y0, ph = 30, 920
    x, w = 20, 1440
    f.rect(x + 6, y0 + 8, w, ph, fill="#DADADA", r=14)
    f.rect(x, y0, w, ph, fill="#0B5CAD", outline="#083E75", width=3, r=14)
    f.text(x + 90, y0 + 110, "디스크 암호화 복구", 46, "white", anchor="lm")
    f.text(x + 90, y0 + 220, "복구 키를 입력하세요", 34, "white", True, anchor="lm")
    f.text(x + 90, y0 + 285, "이 드라이브의 잠금을 해제하려면 복구 키를 입력하십시오.", 26, "#DCEBFA", anchor="lm")
    ib = (x + 90, y0 + 350, 1000, 76)
    f.rect(*ib, fill="#0B5CAD", outline="white", width=3)
    f.text(x + 112, y0 + 388, "______ - ______ - ______ - ______ - ______ - ______ - ______ - ______", 24, "#DCEBFA", anchor="lm")
    f.mark(ib, pad=12)
    f.label(x + 90, y0 + 456, "4. 안내받은 복구 키를 입력합니다")
    f.text(x + 90, y0 + 580, "복구 키 ID(이 키를 식별하는 데 사용):", 26, "#DCEBFA", anchor="lm")
    f.text(x + 90, y0 + 628, "7C2A91E4-3B5D-4F08-A6C1-9E2D4B7F1A30", 30, "white", True, anchor="lm")
    f.mark((x + 80, y0 + 556, 760, 100), pad=6)
    f.label(x + 880, y0 + 606, "1. 복구 키 ID를 적어 둡니다", anchor="lm")
    f.text(x + 90, y0 + 800, "Enter 키를 눌러 계속", 24, "white", anchor="lm")
    f.text(x + 90, y0 + 846, "Esc 키를 눌러 복구 옵션 더 보기", 24, "white", anchor="lm")

    # 안내 흐름
    x, w = 1500, 880
    f.rect(x, y0, w, ph, fill="#FAFAFA", outline="#B5B5B5", r=14)
    f.text(x + 40, y0 + 60, "복구 키는 이렇게 받습니다", 32, bold=True, anchor="lm")
    f.rect(x + 40, y0 + 120, w - 80, 110, fill="#FDE7E9", outline=RED, r=10)
    f.text(x + 64, y0 + 155, "2. 아무 키나 여러 번 입력하지 않습니다.", 27, "#A80000", True, anchor="lm")
    f.text(x + 64, y0 + 198, "복구 키를 추측해서 입력하지 않습니다.", 24, "#A80000", anchor="lm")
    steps = [("3. IT 헬프데스크에 전화", "내선 1000 (평일 09:00~18:00)"),
             ("본인 확인", "사번, 화면의 복구 키 ID, 노트북 모델명"),
             ("담당자가 복구 키 안내", "4. 안내받은 키를 왼쪽 화면에 입력"),
             ("로그인 화면이 나오면 해결", "같은 화면이 반복되면 헬프데스크에 다시 알림")]
    for i, (t, s) in enumerate(steps):
        sy = y0 + 280 + i * 158
        f.rect(x + 40, sy, w - 80, 120, fill="white", outline="#B5B5B5", r=10)
        f.d.ellipse([x + 76, sy + 44, x + 108, sy + 76], fill=NAVY)
        f.text(x + 150, sy + 40, t, 28, bold=True, anchor="lm")
        f.text(x + 150, sy + 84, s, 23, SUB, anchor="lm")
        if i < 3:
            f.d.polygon([(x + w / 2 - 22, sy + 126), (x + w / 2 + 22, sy + 126), (x + w / 2, sy + 152)], fill=NAVY)
    f.save("IT-HW-001_fig3.6.png")


# ---------------------------------------------------------------- IT-HW-001 3.8
def _monitor(f, x, y, w, h, n, sel=False):
    f.rect(x, y, w, h, fill=BLUE if sel else "#5B6B7C", outline="#2B3A4A", width=3, r=8)
    f.text(x + w / 2, y + h / 2, n, 54, "white", True, anchor="mm")


def _settings(f, x, y0, w, ph):
    f.window(x, y0, w, ph, "설정", bg=PANEL, bar=PANEL)
    for i, n in enumerate(["시스템", "Bluetooth 및 장치", "네트워크 및 인터넷", "개인 설정", "앱", "계정"]):
        if i == 0:
            f.rect(x + 16, y0 + 96 + i * 62, 300, 52, fill="#E3E3E3", r=6)
            f.rect(x + 16, y0 + 107 + i * 62, 6, 30, fill=BLUE, r=3)
        f.text(x + 40, y0 + 122 + i * 62, n, 24, anchor="lm")
    return x + 350, y0 + 80


def hw001_3_8():
    f = Fig()
    y0, ph = 30, 920
    x, w = 20, 1390
    cx, cy = _settings(f, x, y0, w, ph)
    cw = w - 380
    f.text(cx, cy + 30, "시스템  >  디스플레이", 34, bold=True, anchor="lm")
    f.rect(cx, cy + 80, cw, 250, fill="white", outline=LINE, r=10)
    _monitor(f, cx + cw / 2 - 110, cy + 135, 220, 130, "1", True)
    f.button(cx + cw - 150, cy + 262, 120, 50, "식별")
    f.rect(cx, cy + 350, cw, 80, fill="white", outline=LINE, r=10)
    f.text(cx + 30, cy + 390, "여러 디스플레이", 26, bold=True, anchor="lm")
    f.text(cx + cw - 40, cy + 390, "∧", 26, SUB, anchor="mm")
    f.rect(cx, cy + 432, cw, 90, fill="white", outline=LINE, r=10)
    f.text(cx + 30, cy + 477, "모니터 연결 기억", 24, anchor="lm")
    f.checkbox(cx + cw - 70, cy + 462, True)
    f.rect(cx, cy + 524, cw, 100, fill="white", outline=LINE, r=10)
    f.text(cx + 30, cy + 574, "다른 디스플레이 감지", 24, anchor="lm")
    b = f.button(cx + cw - 170, cy + 546, 140, 56, "감지")
    f.mark(b)
    f.label(cx + cw - 190, cy + 574, "1. 케이블을 다시 연결하고 [감지]", anchor="rm")
    f.rect(cx, cy + 646, cw, 90, fill="white", outline=LINE, r=10)
    f.text(cx + 30, cy + 691, "배율", 24, anchor="lm")
    f.text(cx + cw - 40, cy + 691, "100% (권장)", 24, SUB, anchor="rm")
    f.flow(1422, 1483)

    x, w = 1495, 885
    f.window(x, y0, w, ph, "설정", bg=PANEL, bar=PANEL)
    cx, cy, cw = x + 40, y0 + 80, w - 80
    f.text(cx, cy + 30, "시스템  >  디스플레이", 34, bold=True, anchor="lm")
    f.rect(cx, cy + 80, cw, 250, fill="white", outline=LINE, r=10)
    _monitor(f, cx + cw / 2 - 230, cy + 135, 220, 130, "1", True)
    _monitor(f, cx + cw / 2 + 10, cy + 135, 220, 130, "2")
    f.mark((cx + cw / 2 + 10, cy + 135, 220, 130), pad=10)
    f.label(cx + cw / 2 - 150, cy + 370, "외부 모니터(2)가 보이면 해결")
    f.rect(cx, cy + 450, cw, 90, fill="white", outline=LINE, r=10)
    f.text(cx + 30, cy + 495, "여러 디스플레이", 24, anchor="lm")
    f.field(cx + cw - 330, cy + 466, 300, 58, "디스플레이 확장   ∨")
    f.rect(cx, cy + 570, cw, 200, fill="#FFF4CE", outline="#C8A400", r=10)
    f.text(cx + 30, cy + 615, "그래도 화면이 안 나오면", 26, bold=True, anchor="lm")
    f.text(cx + 30, cy + 665, "2. 도킹스테이션 전원을 껐다가 다시 켭니다.", 24, anchor="lm")
    f.text(cx + 30, cy + 710, "3. 헬프데스크 안내에 따라 펌웨어를 업데이트합니다.", 24, anchor="lm")
    f.save("IT-HW-001_fig3.8.png")


# ---------------------------------------------------------------- IT-HW-002 3.3
def hw002_3_3():
    f = Fig()
    y0, ph = 30, 920
    x, w = 20, 2360
    f.window(x, y0, w, ph, "그룹웨어 - IT 요청 - 장비 신청", bg="white")
    f.rect(x + 2, y0 + 60, w - 4, 70, fill=NAVY)
    f.text(x + 36, y0 + 95, "그룹웨어", 30, "white", True, anchor="lm")
    for i, n in enumerate(["메일", "전자결재", "게시판", "IT 요청"]):
        f.text(x + 300 + i * 190, y0 + 95, n, 25, "white", i == 3, anchor="lm")
    f.rect(x + 870, y0 + 124, 96, 6, fill=YELLOW)
    # 왼쪽 메뉴
    f.rect(x + 2, y0 + 130, 420, ph - 134, fill="#F5F6F8")
    f.text(x + 36, y0 + 185, "IT 요청", 28, bold=True, anchor="lm")
    menu = ["권한 신청", "장비 신청", "복합기 요청"]
    for i, n in enumerate(menu):
        my = y0 + 230 + i * 70
        if n == "장비 신청":
            f.rect(x + 20, my, 382, 58, fill="#DCE6F5", r=6)
            f.mark((x + 20, my, 382, 58), pad=4)
        f.text(x + 50, my + 29, n, 25, bold=(n == "장비 신청"), anchor="lm")
    f.label(x + 30, y0 + 470, "그룹웨어 > IT 요청 > 장비 신청")
    # 양식
    fx, fy = x + 480, y0 + 170
    f.text(fx, fy + 10, "장비 신청", 34, bold=True, anchor="lm")
    f.hline(fx, fy + 50, w - 540, fill="#9A9A9A")
    lab = lambda yy, t: f.text(fx, yy, t, 25, bold=True, anchor="lm")
    lab(fy + 115, "신청 종류")
    kinds = ["수리", "교체", "신규 지급", "비품", "반납"]
    kx = fx + 260
    for i, n in enumerate(kinds):
        f.radio(kx + i * 250, fy + 100, n == "교체")
        f.text(kx + i * 250 + 44, fy + 115, n, 25, anchor="lm")
    f.mark((kx - 14, fy + 82, 1250, 66), pad=4)
    f.label(kx + 1270, fy + 115, "신청 종류를 선택", anchor="lm")
    lab(fy + 215, "신청자 사번")
    f.field(kx, fy + 186, 420, 58, "EMP-0000", hint=True)
    lab(fy + 305, "대상 장비")
    f.field(kx, fy + 276, 420, 58, "노트북   ∨")
    f.text(kx + 480, fy + 305, "현재 장비 지급일", 25, bold=True, anchor="lm")
    f.field(kx + 720, fy + 276, 420, 58, "YYYY-MM-DD", hint=True)
    lab(fy + 395, "희망 OS")
    f.field(kx, fy + 366, 420, 58, "Windows   ∨")
    f.text(kx + 450, fy + 395, "개발 직군만 macOS / Windows 중 선택", 23, SUB, anchor="lm")
    lab(fy + 485, "사유·증상")
    f.field(kx, fy + 456, 1480, 120, "")
    f.text(kx + 16, fy + 490, "예) 지급일로부터 3년이 지나 교체를 신청합니다.", 24, SUB, anchor="lm")
    lab(fy + 635, "첨부 (사진 등)")
    f.button(kx, fy + 606, 180, 58, "파일 선택")
    f.text(kx + 200, fy + 635, "수리 신청은 파손 부위 사진을 첨부합니다.", 23, SUB, anchor="lm")
    b = f.button(kx + 1300, fy + 606, 180, 62, "제출", primary=True, size=26)
    f.mark(b)
    f.label(kx + 1280, fy + 637, "내용을 적고 [제출]", anchor="rm")
    f.save("IT-HW-002_fig3.3.png")


# ---------------------------------------------------------------- IT-HW-003 3.1
PRN = "본사 3층 복합기"


def hw003_3_1():
    f = Fig()
    y0, ph = 30, 920
    x, w = 20, 1090
    f.window(x, y0, w, ph, "설정", bg=PANEL, bar=PANEL)
    cx, cy, cw = x + 40, y0 + 80, w - 80
    f.text(cx, cy + 22, "Bluetooth 및 장치  >  프린터 및 스캐너  >", 25, SUB, anchor="lm")
    f.text(cx, cy + 76, PRN, 36, bold=True, anchor="lm")
    f.rect(cx, cy + 120, cw, 100, fill="white", outline=LINE, r=10)
    f.rect(cx + 26, cy + 144, 66, 52, fill="#6E7B8B", r=6)
    f.rect(cx + 38, cy + 132, 42, 16, fill="#C9C9C9")
    f.text(cx + 116, cy + 170, "프린터 상태:  오류", 25, "#A80000", anchor="lm")
    f.button(cx + cw - 150, cy + 142, 120, 54, "제거")
    f.text(cx, cy + 266, "프린터 설정", 26, bold=True, anchor="lm")
    rows = ["인쇄 대기열 열기", "테스트 페이지 인쇄", "인쇄 기본 설정", "프린터 속성"]
    for i, n in enumerate(rows):
        ry = cy + 296 + i * 92
        f.rect(cx, ry, cw, 84, fill="white", outline=LINE, r=10)
        f.text(cx + 30, ry + 42, n, 25, anchor="lm")
        f.text(cx + cw - 40, ry + 42, ">", 26, SUB, anchor="mm")
        if i == 0:
            f.mark((cx, ry, cw, 84), pad=4)
    f.label(cx, cy + 690, "2. [설정] > [프린터 및 스캐너] > 복합기 선택")
    f.label(cx, cy + 750, "    > [인쇄 대기열 열기]")
    f.flow(1122, 1183)

    x, w = 1195, 1185
    f.window(x, y0, w, ph, PRN)
    for i, n in enumerate(["프린터", "문서", "보기"]):
        if i == 0:
            f.rect(x + 14, y0 + 68, 110, 48, fill="#DCEBFA")
        f.text(x + 34 + i * 120, y0 + 92, n, 24, anchor="lm")
    f.hline(x + 2, y0 + 120, w - 4)
    c = [x + 440, x + 690, x + 870, x + 990, x + 1070]
    for i, n in enumerate(["문서 이름", "상태", "소유자", "페이지", "제출 시간"]):
        f.text(c[i], y0 + 150, n, 23, SUB, anchor="lm")
    f.hline(x + 2, y0 + 176, w - 4)
    docs = [("회의자료.pptx", "오류 - 인쇄 중", "EMP-0000", "12", "오전 9:12"),
            ("회의자료.pptx", "스풀링", "EMP-0000", "12", "오전 9:14")]
    for i, r in enumerate(docs):
        for j, v in enumerate(r):
            f.text(c[j], y0 + 212 + i * 60, v, 24, "#A80000" if (j == 1 and i == 0) else INK, anchor="lm")
    # 프린터 메뉴
    mx, my = x + 14, y0 + 118
    f.rect(mx + 5, my + 6, 400, 400, fill="#D5D5D5", r=8)
    f.rect(mx, my, 400, 400, fill="white", outline="#A0A0A0", r=8)
    items = ["기본 프린터로 설정", "인쇄 기본 설정...", "인쇄 일시 중지", "모든 문서 취소", "공유...", "속성"]
    for i, n in enumerate(items):
        iy = my + 14 + i * 62
        if n == "모든 문서 취소":
            f.rect(mx + 8, iy, 384, 54, fill="#E5F1FB", r=6)
            f.mark((mx + 8, iy, 384, 54), pad=4)
        f.text(mx + 30, iy + 27, n, 25, anchor="lm")
    f.label(mx + 430, my + 290, "2. [프린터] > [모든 문서 취소]", anchor="lm")
    f.rect(x + 40, y0 + 620, w - 80, 190, fill="#FFF4CE", outline="#C8A400", r=10)
    f.text(x + 70, y0 + 668, "1. 먼저 복합기 화면에 오류가 있는지 확인합니다.", 25, anchor="lm")
    f.text(x + 70, y0 + 716, "3. 대기열을 비운 뒤 PC를 재부팅하고 다시 인쇄합니다.", 25, anchor="lm")
    f.text(x + 70, y0 + 764, "복합기 화면에 오류 코드가 있으면 3.3을 봅니다.", 24, SUB, anchor="lm")
    f.save("IT-HW-003_fig3.1.png")


# ---------------------------------------------------------------- IT-HW-003 3.6
def hw003_3_6():
    f = Fig()
    y0, ph = 30, 920
    x, w = 20, 1500
    f.window(x, y0, w, ph, "소프트웨어 센터")
    f.rect(x + 2, y0 + 60, 330, ph - 64, fill=NAVY)
    nav = ["응용 프로그램", "프린터 설치", "설치 상태", "장치 준수"]
    for i, n in enumerate(nav):
        ny = y0 + 90 + i * 72
        if n == "프린터 설치":
            f.rect(x + 14, ny, 306, 58, fill="#3A5796", r=6)
            f.mark((x + 14, ny, 306, 58), pad=4)
        f.text(x + 44, ny + 29, n, 25, "white", n == "프린터 설치", anchor="lm")
    f.label(x + 250, y0 + 30, "1. 소프트웨어 센터 실행", anchor="lm")
    f.label(x + 30, y0 + 400, "2. [프린터 설치]")
    cx, cy, cw = x + 370, y0 + 80, w - 410
    f.text(cx, cy + 24, "프린터 설치", 34, bold=True, anchor="lm")
    f.text(cx, cy + 96, "건물", 24, SUB, anchor="lm")
    f.field(cx + 70, cy + 68, 260, 56, "본사   ∨")
    f.text(cx + 370, cy + 96, "층", 24, SUB, anchor="lm")
    f.field(cx + 420, cy + 68, 260, 56, "전체   ∨")
    rows = [("본사 3층 복합기", "본사 · 3층 · 컬러 복합기"),
            ("본사 11층 복합기", "본사 · 11층 · 컬러 복합기"), ("연구동 2층 복합기", "연구동 · 2층 · 흑백 복합기"),
            ("연구동 4층 복합기", "연구동 · 4층 · 컬러 복합기")]
    for i, (n, s) in enumerate(rows):
        ry = cy + 150 + i * 104
        sel = i == 0
        f.rect(cx, ry, cw, 94, fill="#E8F1FB" if sel else "white", outline="#99C2EE" if sel else LINE, r=10)
        f.rect(cx + 24, ry + 26, 62, 46, fill="#6E7B8B", r=6)
        f.rect(cx + 36, ry + 14, 38, 16, fill="#C9C9C9")
        f.text(cx + 110, ry + 32, n, 26, bold=True, anchor="lm")
        f.text(cx + 110, ry + 68, s, 22, SUB, anchor="lm")
        if sel:
            b = f.button(cx + cw - 170, ry + 20, 140, 54, "설치", primary=True)
            f.mark(b)
            f.mark((cx, ry, cw - 200, 94), pad=4)
    f.label(cx + 20, cy + 700, "2. 건물·층에 맞는 복합기 선택")
    f.label(cx + cw - 20, cy + 700, "3. [설치]", anchor="ra")
    f.flow(1532, 1593)

    x, w = 1605, 775
    f.window(x, y0 + 160, w, 600, "소프트웨어 센터", bg="white")
    cx, cy = x + 40, y0 + 250
    f.d.ellipse([cx, cy, cx + 90, cy + 90], fill="#107C10")
    f.d.line([cx + 22, cy + 48, cx + 40, cy + 66, cx + 70, cy + 28], fill="white", width=9)
    f.text(cx + 120, cy + 26, "설치 완료", 32, bold=True, anchor="lm")
    f.text(cx + 120, cy + 72, "본사 3층 복합기를 설치했습니다.", 24, SUB, anchor="lm")
    f.hline(cx, cy + 130, w - 80)
    f.text(cx, cy + 180, "프린터 목록에 복합기가 보이는지 확인하고", 24, anchor="lm")
    f.text(cx, cy + 220, "테스트 페이지를 인쇄해 보세요.", 24, anchor="lm")
    b = f.button(cx, cy + 300, 330, 60, "테스트 페이지 인쇄", primary=True)
    f.mark(b)
    f.button(cx + 360, cy + 300, 160, 60, "닫기")
    f.label(cx, cy + 400, "3. 끝나면 테스트 페이지 인쇄")
    f.save("IT-HW-003_fig3.6.png")


# ================================================================ 공통 부품 (단계 카드·장비 그림)
def steps_card(f, x, y, w, h, title, items):
    """가이드의 단계를 그대로 옮긴 카드. items = (번호, [줄...], 종류). 종류: "" / "hl"(이 그림의 단계) / "warn" / "sub"."""
    f.rect(x, y, w, h, fill="#FAFAFA", outline="#B5B5B5", r=14)
    f.text(x + 36, y + 56, title, 31, bold=True, anchor="lm")
    cy = y + 104
    for num, lines, kind in items:
        bh = 44 + len(lines) * 38
        fill, line, ink = {"hl": ("#FFF4CE", "#C8A400", INK), "warn": ("#FDE7E9", RED, "#A80000"),
                           "sub": ("#EEF2F7", "#B5C2D3", SUB)}.get(kind, ("white", "#B5B5B5", INK))
        f.rect(x + 30, cy, w - 60, bh, fill=fill, outline=line, r=10)
        tx = x + 56
        if num:
            f.d.ellipse([x + 50, cy + 20, x + 102, cy + 72], fill=NAVY)
            f.text(x + 76, cy + 45, str(num), 27, "white", True, anchor="mm")
            tx = x + 124
        for i, ln in enumerate(lines):
            f.text(tx, cy + 44 + i * 38, ln, 25, ink, bold=(kind == "warn" and i == 0), anchor="lm")
        cy += bh + 16
    return cy


def stage(f, x, y, w, h, title=None):
    f.rect(x, y, w, h, fill="#F4F7FB", outline="#B5C2D3", r=14)
    if title:
        f.text(x + 36, y + 50, title, 28, SUB, True, anchor="lm")


def laptop(f, x, y, w=520, screen="#101820"):
    """노트북 정면 그림. (x, y)는 화면 왼쪽 위. 화면 높이를 돌려준다."""
    h = int(w * 0.62)
    f.rect(x, y, w, h, fill="#2F3A48", outline="#1B222C", width=3, r=14)
    f.rect(x + 16, y + 16, w - 32, h - 32, fill=screen)
    f.d.polygon([(x - 10, y + h), (x + w + 10, y + h), (x + w + 60, y + h + 74), (x - 60, y + h + 74)],
                fill="#C9CED6", outline="#8A94A0")
    f.d.polygon([(x + 24, y + h + 12), (x + w - 24, y + h + 12), (x + w - 6, y + h + 48), (x + 6, y + h + 48)],
                fill="#AEB5BF")
    f.rect(x - 60, y + h + 74, w + 120, 14, fill="#9AA3AE", r=6)
    return h


def monitor(f, x, y, w, h, fill="#0B5CAD", text="", fg="white"):
    f.rect(x, y, w, h, fill="#20262E", outline="#11151A", width=3, r=10)
    f.rect(x + 14, y + 14, w - 28, h - 28, fill=fill)
    if text:
        f.text(x + w / 2, y + h / 2, text, 30, fg, True, anchor="mm")
    f.rect(x + w / 2 - 20, y + h, 40, 46, fill="#6E7B8B")
    f.rect(x + w / 2 - 90, y + h + 46, 180, 16, fill="#6E7B8B", r=6)


def dock(f, x, y, w=260, h=70, label="도킹스테이션"):
    f.rect(x, y, w, h, fill="#4A5560", outline="#2B333B", width=3, r=10)
    for i in range(4):
        f.rect(x + 24 + i * 34, y + h - 30, 22, 12, fill="#C9CED6")
    f.text(x + w / 2, y + h + 30, label, 23, SUB, anchor="mm")


def cable(f, pts, color="#3A4652", width=8):
    f.d.line(pts, fill=color, width=width, joint="curve")


def ok_bad(f, x, y, good):
    c = "#107C10" if good else RED
    f.d.ellipse([x, y, x + 70, y + 70], fill=c)
    if good:
        f.d.line([x + 17, y + 37, x + 31, y + 51, x + 54, y + 22], fill="white", width=8)
    else:
        f.d.line([x + 20, y + 20, x + 50, y + 50], fill="white", width=8)
        f.d.line([x + 50, y + 20, x + 20, y + 50], fill="white", width=8)


def panel(f, x, y, w, h, title):
    """복합기 조작 화면(터치 패널)."""
    f.text(x + 10, y - 26, "복합기 화면", 24, SUB, True, anchor="lm")
    f.rect(x, y, w, h, fill="#2B2F36", outline="#15181C", width=3, r=24)
    f.rect(x + 26, y + 26, w - 52, h - 52, fill="white", r=6)
    f.rect(x + 26, y + 26, w - 52, 70, fill=NAVY)
    f.text(x + 56, y + 61, title, 27, "white", True, anchor="lm")
    return x + 56, y + 126, w - 112


def full_screen(f, x, y, w, h, fill):
    f.rect(x + 6, y + 8, w, h, fill="#DADADA", r=14)
    f.rect(x, y, w, h, fill=fill, outline="#0A2540", width=3, r=14)


def spinner(f, cx, cy, r=34, color="white"):
    for i in range(8):
        a = math.radians(i * 45)
        s = 4 + i
        f.d.ellipse([cx + r * math.cos(a) - s, cy + r * math.sin(a) - s, cx + r * math.cos(a) + s,
                     cy + r * math.sin(a) + s], fill=color)


Y0, PH = 30, 920
LX, LW = 20, 1440      # 왼쪽 화면 영역
RX, RW = 1500, 880     # 오른쪽 단계 카드


# ---------------------------------------------------------------- IT-HW-001 나머지
def hw001_3_3():
    f = Fig()
    cx, cy = _taskmgr(f, LX, Y0, LW, PH, "성능")
    tiles = [("CPU", "34%"), ("메모리", "94%"), ("디스크", "41%")]
    for i, (n, v) in enumerate(tiles):
        ty = cy + i * 150
        sel = n == "메모리"
        f.rect(cx, ty, 300, 134, fill="#E5F1FB" if sel else "white", outline="#99C2EE" if sel else LINE, r=8)
        f.text(cx + 24, ty + 44, n, 27, bold=True, anchor="lm")
        f.text(cx + 24, ty + 92, v, 26, "#A80000" if sel else SUB, sel, anchor="lm")
    f.mark((cx, cy + 150, 300, 134), pad=4)
    gx, gw = cx + 340, LW - 232 - 340 - 30
    f.text(gx, cy + 26, "메모리", 40, bold=True, anchor="lm")
    f.text(gx + gw, cy + 26, "사용 중 94%", 30, "#A80000", True, anchor="rm")
    f.rect(gx, cy + 70, gw, 420, fill="white", outline="#8E44AD", width=3)
    pts = [(gx, cy + 490)]
    hs = [210, 190, 160, 150, 120, 90, 70, 60, 48, 40, 36, 30, 28, 26, 26]
    for i, hh in enumerate(hs):
        pts.append((gx + i * gw / (len(hs) - 1), cy + 70 + hh))
    pts.append((gx + gw, cy + 490))
    f.d.polygon(pts, fill="#EAD7F4", outline="#8E44AD")
    f.text(gx, cy + 540, "메모리 사용량", 24, SUB, anchor="lm")
    f.rect(gx, cy + 566, gw, 40, fill="#E6E6E6", outline="#BDBDBD")
    f.rect(gx, cy + 566, int(gw * 0.94), 40, fill="#8E44AD")
    f.mark((gx + gw - 250, cy - 4, 250, 60), pad=6)
    f.label(gx, cy + 660, "2. 작업 관리자에서 메모리 사용률을 확인합니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["쓰지 않는 프로그램과", "브라우저 탭을 닫습니다."], ""),
        (2, ["작업 관리자에서 메모리 사용률을", "확인합니다."], "hl"),
        (3, ["헬프데스크에 원격 점검을 요청합니다.", "담당자가 메모리 증설이나", "저장 장치 교체를 진행합니다."], ""),
        (0, ["문의할 때: 사번, 노트북 모델명,", "느려지는 작업, 작업 관리자 사용률 화면"], "sub")])
    f.save("IT-HW-001_fig3.3.png")


def hw001_3_4():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    lx, ly = LX + 110, Y0 + 230
    h = laptop(f, lx, ly)
    # 전원 버튼
    bx, by = lx + 470, ly + h + 22
    f.d.ellipse([bx, by, bx + 30, by + 22], fill="#5F6B78", outline="#2B333B", width=2)
    f.mark((bx, by, 30, 22), pad=12)
    f.label(lx - 100, ly + h + 150, "2. 충분히 충전한 뒤 전원 버튼을 길게 눌러 다시 켭니다")
    # 충전 단자와 표시등
    px, py = lx + 560, ly + h + 40
    f.d.ellipse([px + 6, py - 26, px + 26, py - 6], fill="#F2A900", outline="#8A6100", width=2)
    f.mark((px - 4, py - 36, 40, 40), pad=6)
    f.label(lx + 100, ly - 90, "1. 충전 표시등이 켜지는지 봅니다")
    # 어댑터와 콘센트
    cable(f, [(px + 40, py + 10), (px + 190, py + 60), (px + 300, py - 40)])
    f.rect(px + 290, py - 90, 170, 80, fill="#3A4652", outline="#1B222C", width=3, r=10)
    f.text(px + 375, py - 50, "어댑터", 23, "white", anchor="mm")
    cable(f, [(px + 460, py - 50), (px + 520, py - 120), (px + 500, py - 292)])
    wx, wy = px + 430, ly - 20
    for i in range(2):
        ox = wx + i * 170
        f.rect(ox, wy, 140, 140, fill="white", outline="#8A949E", width=3, r=16)
        f.d.ellipse([ox + 30, wy + 30, ox + 110, wy + 110], outline="#8A949E", width=3)
        f.d.ellipse([ox + 50, wy + 62, ox + 62, wy + 74], fill="#5F6B78")
        f.d.ellipse([ox + 78, wy + 62, ox + 90, wy + 74], fill="#5F6B78")
    f.text(wx + 155, wy - 34, "콘센트", 24, SUB, True, anchor="mm")
    f.mark((wx + 170, wy, 140, 140), pad=8)
    f.label(wx + 330, wy + 190, "3. 다른 콘센트에 꽂아 봅니다", anchor="ra")
    f.label(lx + 380, py + 190, "1. 어댑터를 콘센트와 노트북에 확실히 꽂습니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["전원 어댑터를 콘센트와 노트북에", "확실히 꽂고 충전 표시등이", "켜지는지 봅니다."], "hl"),
        (2, ["충분히 충전한 뒤 전원 버튼을", "길게 눌러 다시 켭니다."], "hl"),
        (3, ["다른 콘센트에 꽂아 봅니다."], "hl"),
        (4, ["그래도 켜지지 않으면 헬프데스크에", "문의합니다. 담당자가 어댑터를", "점검·교체합니다."], "")])
    f.save("IT-HW-001_fig3.4.png")


def hw001_3_5():
    f = Fig()
    full_screen(f, LX, Y0, LW, PH, "#0078D7")
    x = LX + 110
    f.text(x, Y0 + 170, ":(", 170, "white", anchor="lm")
    f.text(x, Y0 + 340, "PC에 문제가 발생하여 다시 시작해야 합니다.", 38, "white", anchor="lm")
    f.text(x, Y0 + 400, "오류 정보를 수집하고 있습니다. 그런 다음 자동으로 다시 시작합니다.", 28, "#DCEBFA", anchor="lm")
    f.text(x, Y0 + 490, "20% 완료", 34, "white", anchor="lm")
    f.rect(x, Y0 + 590, 120, 120, fill="white")
    for i in range(5):
        for j in range(5):
            if (i * 3 + j * 5) % 4 < 2:
                f.rect(x + 10 + i * 20, Y0 + 600 + j * 20, 20, 20, fill="#0078D7")
    f.text(x + 160, Y0 + 615, "지원 담당자에게 문의할 때 다음 정보를 알려 주세요.", 25, "#DCEBFA", anchor="lm")
    f.text(x + 160, Y0 + 670, "중지 코드:  (화면에 표시되는 오류 문구)", 28, "white", True, anchor="lm")
    f.mark((x + 150, Y0 + 588, 900, 116), pad=6)
    f.label(x + 150, Y0 + 750, "2. 화면의 오류 문구를 휴대폰으로 찍어 둡니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["전원을 끄고 외부 모니터·", "도킹스테이션·USB 장치를 모두 뺀 뒤", "다시 켭니다."], ""),
        (2, ["파란 화면이 계속 나오면 화면의", "오류 문구를 휴대폰으로 찍어 둡니다."], "hl"),
        (3, ["헬프데스크에 문의합니다.", "담당자가 안전 모드로 들어가 드라이버를", "이전 버전으로 되돌립니다."], ""),
        (0, ["같은 업데이트 뒤 여러 명이 같은 증상이면", "IT 헬프데스크 내선 1000으로", "바로 전화합니다."], "warn")])
    f.save("IT-HW-001_fig3.5.png")


def hw001_3_7():
    f = Fig()
    full_screen(f, LX, Y0, LW, PH, "#1B3A5C")
    cx = LX + LW / 2
    f.d.ellipse([cx - 90, Y0 + 150, cx + 90, Y0 + 330], fill="#C9D6E6")
    f.d.ellipse([cx - 34, Y0 + 186, cx + 34, Y0 + 254], fill="#6E87A6")
    f.d.pieslice([cx - 62, Y0 + 262, cx + 62, Y0 + 392], 180, 360, fill="#6E87A6")
    f.text(cx, Y0 + 400, "사용자", 38, "white", True, anchor="mm")
    spinner(f, cx - 110, Y0 + 500)
    f.text(cx - 50, Y0 + 500, "환영합니다", 32, "white", anchor="lm")
    f.mark((cx - 170, Y0 + 448, 400, 104), pad=4)
    f.label(cx, Y0 + 610, "로그인하면 화면이 멈추거나 오류가 나서 들어가지지 않음", anchor="ma")
    f.label(cx, Y0 + 760, "1. 전원 버튼을 길게 눌러 끈 뒤 다시 켭니다", anchor="ma")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["전원 버튼을 길게 눌러 끈 뒤", "다시 켭니다."], "hl"),
        (2, ["같은 증상이면 헬프데스크에 문의합니다.", "담당자가 안전 모드로 들어가", "시스템 파일을 복구합니다."], ""),
        (0, ["문의할 때: 사번, 최근 OS 업데이트 여부,", "화면 메시지"], "sub"),
        (0, ["같은 업데이트 뒤 여러 명이 같은 증상이면", "IT 헬프데스크 내선 1000으로", "바로 전화합니다."], "warn")])
    f.save("IT-HW-001_fig3.7.png")


def hw001_3_9():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    m1x, m2x, my, mw, mh = LX + 150, LX + 770, Y0 + 110, 520, 310
    monitor(f, m1x, my, mw, mh, "#0B5CAD", "모니터 1  (인식됨)")
    monitor(f, m2x, my, mw, mh, "#111111", "신호 없음", "#9AA3AE")
    dx, dy = LX + 590, Y0 + 700
    dock(f, dx, dy, label="노트북 · 도킹스테이션")
    cable(f, [(dx + 60, dy), (dx + 40, dy - 110), (m1x + mw / 2, my + mh + 62)])
    cable(f, [(dx + 200, dy), (dx + 230, dy - 110), (m2x + mw / 2, my + mh + 62)], color=RED, width=10)
    f.mark((m2x + mw / 2 - 40, my + mh + 20, 80, 70), pad=6)
    f.mark((dx + 170, dy - 30, 70, 60), pad=6)
    f.label(LX + 60, my + mh + 130, "1. 인식되지 않는 모니터의 케이블을 양쪽 모두 다시 꽂습니다")
    f.label(dx + 300, dy + 20, "3. 다른 케이블이나 다른 포트로 바꿔 연결", anchor="lm")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["인식되지 않는 모니터의 케이블을", "양쪽 모두 다시 꽂습니다."], "hl"),
        (2, ["디스플레이 설정에서 [감지]를 누릅니다.", "(그림 3.8 참고)"], ""),
        (3, ["다른 케이블이나 다른 포트로", "바꿔 연결해 봅니다."], "hl"),
        (4, ["케이블 불량이면 헬프데스크에", "케이블 교체를 요청합니다."], "")])
    f.save("IT-HW-001_fig3.9.png")


def hw001_3_10():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    # 평소 연결
    f.text(LX + 50, Y0 + 60, "평소 연결  (도킹스테이션을 거침)", 28, SUB, True, anchor="lm")
    ax, ay = LX + 110, Y0 + 130
    laptop(f, ax, ay, 240, "#0B5CAD")
    dock(f, ax + 440, ay + 90, 220, 60)
    cable(f, [(ax + 300, ay + 170), (ax + 440, ay + 120)])
    cable(f, [(ax + 660, ay + 120), (ax + 800, ay + 120)])
    monitor(f, ax + 800, ay - 20, 400, 240, "#3B3B3B")
    for i in range(6):
        yy = ay + 14 + i * 34
        f.d.line([ax + 820, yy, ax + 900, yy + 16, ax + 990, yy - 14, ax + 1090, yy + 14, ax + 1180, yy],
                 fill=["#E74856", "#00B7C3", "#FFF100"][i % 3], width=5)
    f.label(ax + 320, ay + 290, "깜빡이다 꺼지거나 화면이 일그러짐")
    f.hline(LX + 40, Y0 + 500, LW - 80, fill="#B5C2D3")
    # 직접 연결
    bx, by = LX + 110, Y0 + 620
    laptop(f, bx, by, 240, "#0B5CAD")
    cable(f, [(bx + 300, by + 170), (bx + 560, by + 150), (bx + 800, by + 100)], color=RED, width=10)
    monitor(f, bx + 800, by - 30, 400, 220, "#0B5CAD", "?")
    f.label(LX + 50, Y0 + 545, "1. 도킹스테이션 없이 노트북에 모니터를 직접 연결해 같은 증상인지 확인합니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["도킹스테이션 없이 노트북에 모니터를", "직접 연결해 같은 증상인지", "확인합니다."], "hl"),
        (2, ["증상을 사진으로 찍어 헬프데스크에", "문의합니다. 담당자가 도킹스테이션", "펌웨어를 업데이트하거나", "모니터를 교체합니다."], ""),
        (0, ["문의할 때: 사번, 모니터·도킹스테이션", "모델, 증상 사진, 이미 해 본 조치"], "sub")])
    f.save("IT-HW-001_fig3.10.png")


def _receiver(f, x, y):
    f.rect(x, y, 34, 58, fill="#2B333B", r=6)
    f.rect(x + 7, y + 58, 20, 22, fill="#C9CED6")


def hw001_3_11():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    # 끊기는 위치
    f.text(LX + 50, Y0 + 60, "끊기는 경우  (수신기가 도킹스테이션·모니터 포트에 있음)", 28, SUB, True, anchor="lm")
    ax, ay = LX + 150, Y0 + 230
    dock(f, ax, ay, 300, 80)
    _receiver(f, ax + 120, ay - 80)
    ok_bad(f, ax + 340, ay, False)
    monitor(f, ax + 620, ay - 120, 340, 200, "#3B3B3B")
    _receiver(f, ax + 880, ay + 80)
    ok_bad(f, ax + 1000, ay, False)
    f.text(ax + 1060, ay + 110, "모니터 포트", 23, SUB, anchor="lm")
    f.hline(LX + 40, Y0 + 470, LW - 80, fill="#B5C2D3")
    # 권장 위치
    bx, by = LX + 150, Y0 + 590
    h = laptop(f, bx, by, 300, "#0B5CAD")
    _receiver(f, bx + 372, by + h - 18)
    f.mark((bx + 360, by + h - 26, 58, 96), pad=6)
    ok_bad(f, bx + 460, by + h - 10, True)
    f.label(LX + 50, Y0 + 515, "1. 마우스 수신기를 노트북 본체 USB 포트에 꽂습니다")
    # 마우스
    mx, my = bx + 820, by + 20
    f.d.rounded_rectangle([mx, my, mx + 150, my + 230], radius=75, fill="#4A5560", outline="#2B333B", width=3)
    f.d.line([mx + 75, my, mx + 75, my + 90], fill="#2B333B", width=3)
    f.rect(mx + 200, my + 30, 150, 70, fill="white", outline="#2B333B", width=4, r=8)
    f.rect(mx + 350, my + 50, 14, 30, fill="#2B333B")
    f.rect(mx + 210, my + 40, 36, 50, fill=RED)
    f.mark((mx + 200, my + 30, 164, 70), pad=8)
    f.label(mx + 190, my + 150, "2. 마우스 배터리를 확인합니다", anchor="la")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["마우스 수신기를 도킹스테이션이나", "모니터 포트에서 빼서 노트북 본체", "USB 포트에 꽂습니다."], "hl"),
        (2, ["마우스 배터리를 확인합니다."], "hl"),
        (3, ["다시 사용해 봅니다."], ""),
        (0, ["계속 끊기면 IT-HW-002 3.6에 따라", "마우스 교체를 신청합니다."], "sub")])
    f.save("IT-HW-001_fig3.11.png")


def hw001_3_12():
    f = Fig()
    full_screen(f, LX, Y0, LW, PH, "#0B5CAD")
    cx = LX + LW / 2
    spinner(f, cx, Y0 + 240, 46)
    f.text(cx, Y0 + 380, "업데이트 작업 중", 44, "white", anchor="mm")
    f.text(cx, Y0 + 450, "PC를 끄지 마세요.", 32, "#DCEBFA", anchor="mm")
    f.text(cx - 200, Y0 + 570, "재시작 중", 40, "white", True, anchor="mm")
    f.mark((cx - 350, Y0 + 530, 300, 84), pad=4)
    f.label(cx - 20, Y0 + 572, "이 화면에서 오래 멈춰 있음", anchor="lm")
    f.label(cx, Y0 + 710, "1. 전원을 강제로 끄지 말고 전원에 연결한 채 기다립니다", anchor="ma")
    f.label(cx, Y0 + 790, "2. 오래 그대로면 화면을 사진으로 찍어 헬프데스크에 문의합니다", anchor="ma")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["전원을 강제로 끄지 말고 노트북을", "전원에 연결한 채 기다립니다."], "hl"),
        (2, ["오래 그대로면 화면을 사진으로 찍어", "헬프데스크에 문의합니다. 담당자가", "디스크 공간을 확보한 뒤 업데이트를", "다시 진행합니다."], "hl"),
        (3, ["평소 3.1에 따라 C드라이브 여유 공간을", "10% 이상 유지합니다."], ""),
        (0, ["같은 업데이트 뒤 여러 명이 같은 증상이면", "IT 헬프데스크 내선 1000으로", "바로 전화합니다."], "warn")])
    f.save("IT-HW-001_fig3.12.png")


def hw001_3_13():
    f = Fig()
    full_screen(f, LX, Y0, LW, PH, "#2D5F8B")
    # 작업 표시줄
    f.rect(LX + 3, Y0 + PH - 78, LW - 6, 75, fill="#E9EEF3")
    tx = LX + LW - 330
    f.text(LX + LW - 40, Y0 + PH - 40, "오후 2:10", 23, anchor="rm")
    f.d.polygon([(tx, Y0 + PH - 50), (tx + 16, Y0 + PH - 50), (tx + 34, Y0 + PH - 64), (tx + 34, Y0 + PH - 16),
                 (tx + 16, Y0 + PH - 30), (tx, Y0 + PH - 30)], fill=INK)
    f.d.line([tx + 46, Y0 + PH - 52, tx + 66, Y0 + PH - 28], fill=RED, width=5)
    f.d.line([tx + 66, Y0 + PH - 52, tx + 46, Y0 + PH - 28], fill=RED, width=5)
    f.mark((tx - 8, Y0 + PH - 70, 84, 60), pad=4)
    # 소리 출력 창
    px, py, pw, ph = LX + LW - 800, Y0 + 170, 760, 640
    f.rect(px + 6, py + 8, pw, ph, fill="#1E3F5C", r=14)
    f.rect(px, py, pw, ph, fill="#F3F3F3", outline="#8A8A8A", r=14)
    f.text(px + 36, py + 54, "소리 출력", 30, bold=True, anchor="lm")
    f.text(px + 36, py + 120, "볼륨", 24, SUB, anchor="lm")
    f.rect(px + 120, py + 114, 560, 12, fill="#C9C9C9", r=6)
    f.rect(px + 120, py + 114, 380, 12, fill=BLUE, r=6)
    f.d.ellipse([px + 486, py + 104, px + 518, py + 136], fill=BLUE)
    f.text(px + 36, py + 200, "출력 장치", 24, SUB, anchor="lm")
    devs = [("스피커 (노트북 내장)", True), ("헤드셋", False), ("모니터 스피커", False)]
    for i, (n, c) in enumerate(devs):
        ry = py + 230 + i * 110
        f.rect(px + 30, ry, pw - 60, 96, fill="white", outline=LINE, r=10)
        f.radio(px + 56, ry + 33, c)
        f.text(px + 110, ry + 48, n, 26, anchor="lm")
    f.mark((px + 30, py + 230, pw - 60, 316), pad=6)
    f.label(LX + 50, Y0 + 80, "1. 작업 표시줄의 소리 아이콘에서 출력 장치가 맞게 선택되어 있는지 확인합니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["작업 표시줄의 소리 아이콘에서", "출력 장치가 맞게 선택되어 있는지", "확인합니다."], "hl"),
        (2, ["PC를 재부팅합니다."], ""),
        (3, ["그래도 소리가 나지 않으면 헬프데스크에", "문의합니다. 담당자가 오디오", "드라이버를 다시 설치합니다."], ""),
        (0, ["화상회의에서만 소리 문제가 있으면", "IT-SYS-005를 봅니다."], "sub")])
    f.save("IT-HW-001_fig3.13.png")


# ---------------------------------------------------------------- 그룹웨어 양식 (IT-HW-002, IT-HW-003 3.7)
KINDS = ["수리", "교체", "신규 지급", "비품", "반납"]


def gw_form(f, x, w, title, kind, fields, kind_note=None, flow=None):
    """그룹웨어 IT 요청 양식. fields = (이름, 값, 예시 여부, 큰 칸 여부)."""
    f.window(x, Y0, w, PH, f"그룹웨어 - IT 요청 - {title}", bg="white")
    f.rect(x + 2, Y0 + 60, w - 4, 70, fill=NAVY)
    f.text(x + 30, Y0 + 95, "그룹웨어", 28, "white", True, anchor="lm")
    for i, n in enumerate(["메일", "전자결재", "게시판", "IT 요청"]):
        f.text(x + 230 + i * 150, Y0 + 95, n, 24, "white", i == 3, anchor="lm")
    f.rect(x + 680, Y0 + 124, 90, 6, fill=YELLOW)
    f.rect(x + 2, Y0 + 130, 290, PH - 134, fill="#F5F6F8")
    f.text(x + 30, Y0 + 180, "IT 요청", 27, bold=True, anchor="lm")
    for i, n in enumerate(["권한 신청", "장비 신청", "복합기 요청"]):
        my = Y0 + 220 + i * 66
        if n == title:
            f.rect(x + 16, my, 260, 54, fill="#DCE6F5", r=6)
            f.mark((x + 16, my, 260, 54), pad=4)
        f.text(x + 42, my + 27, n, 24, bold=(n == title), anchor="lm")
    fx, fy = x + 330, Y0 + 180
    fw = w - 370
    f.text(fx, fy, title, 32, bold=True, anchor="lm")
    f.hline(fx, fy + 36, fw, fill="#9A9A9A")
    cy = fy + 70
    vx = fx + 210
    if kind:
        f.text(fx, cy + 30, "신청 종류", 24, bold=True, anchor="lm")
        step = (fw - 210) / 5
        for i, n in enumerate(KINDS):
            f.radio(vx + i * step, cy + 15, n == kind)
            f.text(vx + i * step + 40, cy + 30, n, 24, bold=(n == kind), anchor="lm")
            if n == kind:
                f.mark((vx + i * step - 10, cy + 4, step - 14, 52), pad=2)
                if kind_note:
                    if i < 3:
                        f.label(vx + i * step - 10, cy + 74, kind_note)
                    else:
                        f.label(vx + (i + 1) * step - 24, cy + 74, kind_note, anchor="ra")
        cy += 140 if kind_note else 84
    for name, value, hint, big in fields:
        hh = 130 if big else 58
        f.text(fx, cy + 29, name, 24, bold=True, anchor="lm")
        f.rect(vx, cy, fw - 210, hh, fill="white", outline="#9A9A9A", r=6)
        for i, ln in enumerate(value.split("\n")):
            f.text(vx + 16, cy + 29 + i * 38, ln, 23, SUB if hint else INK, anchor="lm")
        cy += hh + 22
    b = f.button(fx + fw - 170, Y0 + PH - 100, 170, 60, "제출", primary=True, size=26)
    f.mark(b)
    if flow:
        fx2 = fx
        for i, n in enumerate(flow):
            tw = 36 + len(n) * 25
            f.rect(fx2, Y0 + PH - 96, tw, 52, fill="#EEF2F7", outline="#B5C2D3", r=26)
            f.text(fx2 + tw / 2, Y0 + PH - 70, n, 23, anchor="mm")
            fx2 += tw
            if i < len(flow) - 1:
                f.d.polygon([(fx2 + 12, Y0 + PH - 82), (fx2 + 32, Y0 + PH - 70), (fx2 + 12, Y0 + PH - 58)], fill=NAVY)
                fx2 += 44


SX, SW, FX, FW = 20, 800, 860, 1520   # 왼쪽 단계 카드 / 오른쪽 양식


def hw002_3_1():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["즉시 전원을 끄고 충전기를", "분리합니다. 다시 켜 보지 않습니다."], "warn"),
        (2, ["그룹웨어 > IT 요청 > 장비 신청에서", "'수리'를 선택하고 경위와 사진을", "적어 제출합니다."], "hl"),
        (0, ["급하면 IT 헬프데스크(내선 1000)로", "전화합니다."], "sub"),
        (3, ["안내받은 시간에 엔드포인트지원팀에", "장비를 맡깁니다."], ""),
        (4, ["수리 기간에는 대여 노트북을", "받아 씁니다."], "")])
    gw_form(f, FX, FW, "장비 신청", "수리", [
        ("신청자 사번", "EMP-0000", True, False), ("대상 장비", "노트북 (모델명)", True, False),
        ("사고 경위·시각", "예) 사고 경위와 시각, 파손 부위를 적습니다.\n     백업이 필요한 데이터도 적습니다.", True, True),
        ("첨부", "파손 부위 사진", True, False)], kind_note="2. '수리' 선택")
    f.save("IT-HW-002_fig3.1.png")


def hw002_3_2():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["외장 키보드나 다른 포트로", "같은 증상인지 확인합니다."], ""),
        (2, ["그룹웨어 > IT 요청 > 장비 신청에서", "'수리'를 선택하고 증상을 적어", "제출합니다."], "hl"),
        (3, ["안내받은 시간에 장비를 맡깁니다."], ""),
        (0, ["무상 보증 기간이면 제조사 보증 수리로", "접수됩니다. 오래 걸리면 대여 노트북을", "지급합니다."], "sub")])
    gw_form(f, FX, FW, "장비 신청", "수리", [
        ("신청자 사번", "EMP-0000", True, False), ("대상 장비", "노트북 (모델명)", True, False),
        ("증상", "예) 어느 키·어느 포트가 안 되는지,\n     증상이 시작된 시점을 적습니다.", True, True)],
        kind_note="2. '수리' 선택")
    f.save("IT-HW-002_fig3.2.png")


def hw002_3_4():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["그룹웨어 > IT 요청 > 장비 신청에서", "'교체'를 선택하고 고사양이 필요한", "사유를 적습니다."], "hl"),
        (2, ["제출하면 부서장에게 결재가", "올라갑니다."], "hl"),
        (0, ["승인 절차", "부서장 승인 → 엔드포인트지원팀", "재고 확인 후 지급"], "sub"),
        (0, ["업무상 필요가 확인되지 않으면", "반려됩니다."], "sub")])
    gw_form(f, FX, FW, "장비 신청", "교체", [
        ("신청자 사번", "EMP-0000", True, False),
        ("필요한 사양", "예) 필요한 사양과 사용하는 프로그램", True, False),
        ("사유", "예) 업무상 고사양 노트북이 필요한 사유를 적습니다.", True, True)],
        kind_note="1. '교체' 선택 + 고사양 사유", flow=["제출", "부서장 승인", "재고 확인", "지급"])
    f.save("IT-HW-002_fig3.4.png")


def hw002_3_5():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["그룹웨어 > IT 요청 > 장비 신청에서", "'신규 지급'을 선택합니다."], "hl"),
        (2, ["입사자 정보와 입사일을 적어", "제출합니다."], "hl"),
        (3, ["입사일에 세팅이 끝난 PC를 받습니다."], ""),
        (0, ["신청 대상: 입사자의 소속 팀장", "또는 팀 담당자"], "sub"),
        (0, ["입사일이 정해지지 않았으면", "보완 요청을 받습니다."], "sub")])
    gw_form(f, FX, FW, "장비 신청", "신규 지급", [
        ("입사자 이름", "", True, False), ("입사일", "YYYY-MM-DD", True, False),
        ("인원 수", "1", False, False), ("직군", "개발 직군이면 희망 OS (macOS / Windows)", True, False)],
        kind_note="1. '신규 지급' 선택")
    f.label(FX + 540, Y0 + 760, "2. 입사자 정보와 입사일을 적어 [제출]", anchor="lm")
    f.save("IT-HW-002_fig3.5.png")


def hw002_3_6():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["그룹웨어 > IT 요청 > 장비 신청에서", "'비품'을 선택합니다."], "hl"),
        (2, ["주변기기 종류와 증상을 적어", "제출합니다."], "hl"),
        (0, ["접수 후 1영업일 안에 재고에서", "지급합니다."], "sub"),
        (0, ["개인 구매 주변기기는 대상이 아닙니다."], "sub")])
    gw_form(f, FX, FW, "장비 신청", "비품", [
        ("신청자 사번", "EMP-0000", True, False), ("주변기기 종류", "예) 마우스, 키보드", True, False),
        ("고장 증상", "예) 고장 증상을 적습니다.", True, True)], kind_note="1. '비품' 선택")
    f.label(FX + 540, Y0 + 760, "2. 주변기기 종류와 증상을 적어 [제출]", anchor="lm")
    f.save("IT-HW-002_fig3.6.png")


def hw002_3_7():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["업무 파일을 팀 공유 드라이브로", "옮깁니다."], ""),
        (2, ["그룹웨어 > IT 요청 > 장비 신청에서", "'반납'을 선택해 제출합니다."], "hl"),
        (3, ["직접 초기화하지 말고 그대로", "엔드포인트지원팀에 반납합니다.", "초기화는 IT에서 진행합니다."], "warn"),
        (0, ["장비를 분실했으면 반납이 아니라", "IT-SEC-003 3.7에 따라 분실 신고를", "합니다."], "sub")])
    gw_form(f, FX, FW, "장비 신청", "반납", [
        ("신청자 사번", "EMP-0000", True, False), ("반납할 장비", "노트북 (모델명)", True, False),
        ("데이터 백업", "업무 데이터 백업 여부", True, False)], kind_note="2. '반납' 선택")
    f.save("IT-HW-002_fig3.7.png")


# ---------------------------------------------------------------- IT-HW-003 나머지
def hw003_3_2():
    f = Fig()
    f.window(LX, Y0, LW, PH, "설정", bg=PANEL, bar=PANEL)
    cx, cy, cw = LX + 50, Y0 + 80, LW - 100
    f.text(cx, cy + 22, "Bluetooth 및 장치  >  프린터 및 스캐너  >", 25, SUB, anchor="lm")
    f.text(cx, cy + 76, PRN, 36, bold=True, anchor="lm")
    f.rect(cx, cy + 120, cw, 110, fill="white", outline=LINE, r=10)
    f.rect(cx + 26, cy + 150, 66, 52, fill="#6E7B8B", r=6)
    f.rect(cx + 38, cy + 138, 42, 16, fill="#C9C9C9")
    f.text(cx + 116, cy + 175, "프린터 상태:  오프라인", 25, "#A80000", anchor="lm")
    b = f.button(cx + cw - 170, cy + 146, 140, 58, "제거")
    f.mark(b)
    f.label(cx + cw - 190, cy + 175, "1. 해당 복합기를 제거합니다", anchor="rm")
    f.text(cx, cy + 286, "프린터 설정", 26, bold=True, anchor="lm")
    for i, n in enumerate(["인쇄 대기열 열기", "테스트 페이지 인쇄", "인쇄 기본 설정", "프린터 속성"]):
        ry = cy + 316 + i * 92
        f.rect(cx, ry, cw, 84, fill="white", outline=LINE, r=10)
        f.text(cx + 30, ry + 42, n, 25, anchor="lm")
        f.text(cx + cw - 40, ry + 42, ">", 26, SUB, anchor="mm")
        if i == 1:
            f.mark((cx, ry, cw, 84), pad=4)
            f.label(cx + 320, ry + 42, "3. 다시 설치한 뒤 테스트 페이지를 인쇄합니다", anchor="lm")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["PC [설정] > [프린터 및 스캐너]에서", "해당 복합기를 제거합니다."], "hl"),
        (2, ["3.6에 따라 소프트웨어 센터에서", "층별 복합기를 다시 설치합니다.", "(그림 3.6 참고)"], ""),
        (3, ["테스트 페이지를 인쇄합니다."], "hl"),
        (0, ["다시 설치해도 목록에 없으면", "헬프데스크에 문의합니다."], "sub")])
    f.save("IT-HW-003_fig3.2.png")


def hw003_3_3():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    px, py, pw, ph = LX + 60, Y0 + 90, 1000, 560
    ix, iy, iw = panel(f, px, py, pw, ph, "오류")
    f.d.polygon([(ix + 60, iy + 40), (ix + 120, iy + 140), (ix, iy + 140)], fill="#F2A900")
    f.text(ix + 60, iy + 104, "!", 54, "white", True, anchor="mm")
    f.text(ix + 170, iy + 70, "오류 E-xx", 60, "#A80000", True, anchor="lm")
    f.text(ix + 170, iy + 136, "(xx는 오류 번호)", 25, SUB, anchor="lm")
    f.text(ix, iy + 230, "인쇄할 수 없습니다.", 30, anchor="lm")
    f.text(ix, iy + 280, "전원을 껐다가 다시 켜도 같은 오류가 나면 문의하십시오.", 25, SUB, anchor="lm")
    f.mark((ix + 160, iy + 24, 330, 140), pad=4)
    f.label(ix + 520, iy + 90, "1. 오류 코드를 적어 둡니다", anchor="lm")
    # 전원 스위치
    sx, sy = LX + 1150, Y0 + 300
    f.text(sx + 110, sy - 40, "복합기 전원 스위치", 24, SUB, True, anchor="mm")
    f.rect(sx, sy, 220, 330, fill="#D7DCE2", outline="#8A94A0", width=3, r=16)
    f.rect(sx + 60, sy + 70, 100, 190, fill="#2B333B", r=10)
    f.rect(sx + 68, sy + 78, 84, 86, fill="#5F6B78", r=8)
    f.text(sx + 110, sy + 120, "I", 40, "white", True, anchor="mm")
    f.text(sx + 110, sy + 214, "O", 36, "#9AA3AE", True, anchor="mm")
    f.mark((sx + 60, sy + 70, 100, 190), pad=8)
    f.label(LX + 80, Y0 + 740, "2. 복합기 전원을 껐다가 1분 뒤 다시 켭니다  (여러 번 껐다 켜지 않습니다)")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["복합기 화면의 오류 코드를", "적어 둡니다."], "hl"),
        (2, ["복합기 전원을 껐다가 1분 뒤", "다시 켭니다."], "hl"),
        (3, ["같은 오류가 나면 복합기 위치와", "오류 코드를 적어 헬프데스크에", "신고합니다. 담당자가 유지보수 업체", "출동을 요청합니다."], ""),
        (4, ["복구될 때까지 가까운 층의", "다른 복합기를 씁니다."], "")])
    f.save("IT-HW-003_fig3.3.png")


def hw003_3_4():
    f = Fig()
    stage(f, LX, Y0, 1010, PH)
    ix, iy, iw = panel(f, LX + 50, Y0 + 110, 910, 600, "메일로 스캔")
    f.text(ix, iy + 40, "받는 사람", 26, bold=True, anchor="lm")
    f.field(ix, iy + 70, iw, 70, "내 메일 주소", hint=True)
    f.mark((ix, iy + 70, iw, 70), pad=6)
    f.text(ix, iy + 200, "파일 형식", 26, bold=True, anchor="lm")
    f.field(ix, iy + 230, 300, 64, "PDF   ∨")
    f.text(ix + 360, iy + 200, "컬러", 26, bold=True, anchor="lm")
    f.field(ix + 360, iy + 230, 300, 64, "자동   ∨")
    f.button(ix + iw - 260, iy + 350, 260, 76, "스캔 시작", primary=True, size=28)
    f.label(LX + 60, Y0 + 770, "2. 받는 메일 주소를 정확히 입력했는지 확인합니다")
    f.flow(1042, 1103)
    # 메일함
    x, w = 1115, 1265
    f.window(x, Y0, w, PH, "사내 메일")
    f.rect(x + 2, Y0 + 60, 330, PH - 64, fill="#F5F6F8")
    for i, n in enumerate(["받은 편지함", "보낸 편지함", "임시 보관함", "스팸(격리)함", "휴지통"]):
        my = Y0 + 90 + i * 70
        if n == "스팸(격리)함":
            f.rect(x + 16, my, 300, 56, fill="#DCE6F5", r=6)
            f.mark((x + 16, my, 300, 56), pad=4)
        f.text(x + 44, my + 28, n, 25, bold=(n == "스팸(격리)함"), anchor="lm")
    mx = x + 370
    f.text(mx, Y0 + 110, "스팸(격리)함", 32, bold=True, anchor="lm")
    f.hline(mx, Y0 + 146, w - 410)
    f.rect(mx, Y0 + 166, w - 410, 96, fill="#E8F1FB", outline="#99C2EE", r=8)
    f.text(mx + 24, Y0 + 196, "복합기 (스캔)", 25, bold=True, anchor="lm")
    f.text(mx + 24, Y0 + 236, "스캔 문서가 첨부되었습니다.   scan.pdf", 23, SUB, anchor="lm")
    f.label(mx, Y0 + 300, "1. 메일함의 스팸(격리)함을 먼저 확인합니다")
    f.rect(mx, Y0 + 470, w - 410, 250, fill="#FFF4CE", outline="#C8A400", r=10)
    f.text(mx + 26, Y0 + 520, "3. 그래도 오지 않으면", 26, bold=True, anchor="lm")
    f.text(mx + 26, Y0 + 572, "복합기 번호(위치)와 스캔한 시각을 적어", 25, anchor="lm")
    f.text(mx + 26, Y0 + 614, "헬프데스크에 신고합니다.", 25, anchor="lm")
    f.text(mx + 26, Y0 + 672, "담당자가 복합기 메일 발송 설정을 고칩니다.", 24, SUB, anchor="lm")
    f.save("IT-HW-003_fig3.4.png")


def hw003_3_5():
    f = Fig()
    stage(f, LX, Y0, LW, PH)
    ix, iy, iw = panel(f, LX + 150, Y0 + 110, 1140, 640, "스캔  >  공유폴더에 저장")
    f.text(ix, iy + 40, "저장 위치", 26, bold=True, anchor="lm")
    f.field(ix, iy + 70, iw, 70, "팀 공유폴더 (등록된 경로)", hint=True)
    dx, dy, dw, dh = ix + 150, iy + 190, iw - 300, 250
    f.rect(dx + 6, dy + 8, dw, dh, fill="#BDBDBD", r=12)
    f.rect(dx, dy, dw, dh, fill="white", outline="#8A8A8A", width=3, r=12)
    ok_bad(f, dx + 40, dy + 50, False)
    f.text(dx + 140, dy + 62, "저장할 수 없습니다", 28, bold=True, anchor="lm")
    f.text(dx + 140, dy + 112, "경로를 찾을 수 없음", 34, "#A80000", True, anchor="lm")
    f.button(dx + dw - 170, dy + dh - 80, 140, 56, "확인")
    f.mark((dx + 130, dy + 82, 380, 60), pad=6)
    f.label(LX + 110, Y0 + 810, "화면 메시지 '경로를 찾을 수 없음'  —  복합기에 예전 경로가 등록되어 있습니다")
    steps_card(f, RX, Y0, RW, PH, "조치 방법", [
        (1, ["저장하려는 공유폴더 경로가", "바뀌었는지 팀에 확인합니다."], ""),
        (2, ["복합기 위치와 새 경로를 적어", "헬프데스크에 요청합니다. 담당자가", "복합기 스캔 경로를 다시 설정합니다."], "hl"),
        (3, ["급하면 '메일로 스캔'을 씁니다."], ""),
        (0, ["공유 드라이브 자체가 열리지 않으면", "IT-SYS-006을 봅니다."], "sub")])
    f.save("IT-HW-003_fig3.5.png")


def hw003_3_7():
    f = Fig()
    steps_card(f, SX, Y0, SW, PH, "신청 방법", [
        (1, ["비품함에 토너가 있으면 복합기 화면", "안내에 따라 직접 교체합니다."], ""),
        (2, ["비품함에 없거나 용지 걸림이 반복되면", "그룹웨어 > IT 요청 > 복합기 요청에", "위치와 증상을 적어 제출합니다."], "hl"),
        (0, ["급하면 IT 헬프데스크(내선 1000)로", "전화합니다."], "sub"),
        (3, ["롤러를 교체하기 전까지는", "다른 용지함(트레이)을 씁니다."], "")])
    gw_form(f, FX, FW, "복합기 요청", None, [
        ("복합기 위치", "건물·층  (예: 본사 3층)", True, False),
        ("요청 내용", "예) 토너 색상 또는 걸림 증상을 적습니다.", True, True)])
    f.label(FX + 540, Y0 + 760, "2. 위치와 증상을 적어 [제출]", anchor="lm")
    f.save("IT-HW-003_fig3.7.png")


FIGURES = (hw001_3_1, hw001_3_2, hw001_3_3, hw001_3_4, hw001_3_5, hw001_3_6, hw001_3_7, hw001_3_8, hw001_3_9,
           hw001_3_10, hw001_3_11, hw001_3_12, hw001_3_13,
           hw002_3_1, hw002_3_2, hw002_3_3, hw002_3_4, hw002_3_5, hw002_3_6, hw002_3_7,
           hw003_3_1, hw003_3_2, hw003_3_3, hw003_3_4, hw003_3_5, hw003_3_6, hw003_3_7)

if __name__ == "__main__":
    import sys

    only = sys.argv[1:]
    for fn in FIGURES:
        if not only or fn.__name__ in only:
            fn()
