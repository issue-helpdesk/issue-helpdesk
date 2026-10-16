"""가상 화면 그림 도구 (Pillow).

실제 캡처가 아니라 설명용 가상 화면이다. 회사 로고·실제 제품명은 넣지 않는다.
강조는 참고 매뉴얼 형식을 따라 빨간 테두리 + 주황 번호 원으로 표시한다.
"""
from PIL import Image, ImageDraw, ImageFont

FONT = 'C:/Windows/Fonts/malgun.ttf'
FONT_B = 'C:/Windows/Fonts/malgunbd.ttf'
NAVY = (34, 57, 95)
TEXT = (31, 41, 51)
GREY = (91, 101, 115)
LIGHT = (233, 238, 244)
LINE = (213, 219, 227)
RED = (214, 48, 39)
ORANGE = (232, 89, 12)
WHITE = (255, 255, 255)
BG = (246, 247, 249)
BLUE = (37, 99, 235)
GREEN = (46, 125, 79)
AMBER = (183, 121, 31)
PINK = (251, 232, 227)

_cache = {}


def font(size, bold=False):
    k = (size, bold)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(FONT_B if bold else FONT, size)
    return _cache[k]


class Canvas:
    def __init__(self, w=1400, h=900, bg=BG):
        self.im = Image.new('RGB', (w, h), bg)
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = w, h

    # 기본 도형
    def rect(self, box, fill=WHITE, outline=LINE, width=2, r=8):
        self.d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)

    def text(self, xy, s, size=22, color=TEXT, bold=False, anchor='la'):
        self.d.text(xy, s, font=font(size, bold), fill=color, anchor=anchor)

    def wrap(self, xy, s, width, size=22, color=TEXT, bold=False, gap=8):
        x, y = xy
        f = font(size, bold)
        line = ''
        for ch in s:
            if ch == '\n':
                self.d.text((x, y), line, font=f, fill=color); y += size + gap; line = ''; continue
            if self.d.textlength(line + ch, font=f) > width:
                self.d.text((x, y), line, font=f, fill=color); y += size + gap; line = ch
            else:
                line += ch
        if line:
            self.d.text((x, y), line, font=f, fill=color); y += size + gap
        return y

    def window(self, box, title, bar=NAVY):
        x0, y0, x1, y1 = box
        self.rect(box, WHITE, LINE, 2, 10)
        self.d.rounded_rectangle((x0, y0, x1, y0 + 52), 10, fill=bar)
        self.d.rectangle((x0, y0 + 30, x1, y0 + 52), fill=bar)
        self.text((x0 + 22, y0 + 26), title, 22, WHITE, True, 'lm')
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            cx = x1 - 30 - i * 30
            self.d.ellipse((cx - 8, y0 + 18, cx + 8, y0 + 34), fill=c)
        return (x0 + 24, y0 + 72, x1 - 24, y1 - 20)

    def button(self, xy, label, kind='primary', size=22, pad=(22, 12)):
        f = font(size, True)
        tw = self.d.textlength(label, font=f)
        x, y = xy
        box = (x, y, x + tw + pad[0] * 2, y + size + pad[1] * 2)
        fill, fg, ol = {
            'primary': (NAVY, WHITE, NAVY), 'danger': (RED, WHITE, RED),
            'plain': (WHITE, TEXT, LINE), 'ok': (GREEN, WHITE, GREEN)}[kind]
        self.d.rounded_rectangle(box, 8, fill=fill, outline=ol, width=2)
        self.d.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label, font=f, fill=fg, anchor='mm')
        return box

    def field(self, xy, w, label, value='', size=20, lw=170):
        x, y = xy
        self.text((x, y + 22), label, size, GREY, False, 'lm')
        box = (x + lw, y, x + lw + w, y + 44)
        self.rect(box, WHITE, LINE, 2, 6)
        if value:
            self.text((box[0] + 14, y + 22), value, size, TEXT, False, 'lm')
        return box

    def banner(self, box, s, kind='warn', size=21):
        fill, ol, fg = {'warn': (PINK, (231, 179, 166), RED), 'info': (LIGHT, LINE, NAVY),
                        'ok': ((227, 242, 232), (181, 214, 192), GREEN), 'amber': ((252, 241, 220), (240, 214, 160), AMBER)}[kind]
        self.rect(box, fill, ol, 2, 8)
        self.wrap((box[0] + 18, box[1] + 14), s, box[2] - box[0] - 36, size, fg, True)

    def highlight(self, box, pad=6):
        x0, y0, x1, y1 = box
        self.d.rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), 6, outline=RED, width=4)

    def badge(self, xy, n, r=19):
        x, y = xy
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=ORANGE)
        self.d.text((x, y + 1), str(n), font=font(22, True), fill=WHITE, anchor='mm')

    def mark(self, box, n, side='right', pad=6):
        """빨간 강조 + 번호."""
        self.highlight(box, pad)
        x0, y0, x1, y1 = box
        if side == 'right':
            self.badge((x1 + pad + 26, (y0 + y1) / 2), n)
        elif side == 'left':
            self.badge((x0 - pad - 26, (y0 + y1) / 2), n)
        elif side == 'top':
            self.badge(((x0 + x1) / 2, y0 - pad - 24), n)
        else:
            self.badge(((x0 + x1) / 2, y1 + pad + 24), n)

    def arrow(self, a, b, color=NAVY, width=6):
        self.d.line([a, b], fill=color, width=width)
        import math
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        L = 20
        p1 = (b[0] - L * math.cos(ang - 0.5), b[1] - L * math.sin(ang - 0.5))
        p2 = (b[0] - L * math.cos(ang + 0.5), b[1] - L * math.sin(ang + 0.5))
        self.d.polygon([b, p1, p2], fill=color)

    def table(self, xy, w, headers, rows, colw, size=19, rowh=46, head_fill=LIGHT):
        x, y = xy
        cx = x
        self.d.rectangle((x, y, x + w, y + rowh), fill=head_fill)
        for i, h in enumerate(headers):
            self.text((cx + 12, y + rowh / 2), h, size, NAVY, True, 'lm'); cx += colw[i]
        y += rowh
        boxes = []
        for r in rows:
            cx = x
            self.d.line((x, y + rowh, x + w, y + rowh), fill=LINE, width=2)
            for i, v in enumerate(r):
                color = TEXT
                bold = False
                if isinstance(v, tuple):
                    v, color, bold = v
                self.text((cx + 12, y + rowh / 2), v, size, color, bold, 'lm'); cx += colw[i]
            boxes.append((x, y, x + w, y + rowh))
            y += rowh
        return boxes

    def phone(self, box, title='', bar=NAVY):
        x0, y0, x1, y1 = box
        self.d.rounded_rectangle(box, 40, fill=(30, 30, 34))
        inner = (x0 + 16, y0 + 50, x1 - 16, y1 - 50)
        self.d.rounded_rectangle(inner, 18, fill=WHITE)
        self.d.rounded_rectangle((x0 + (x1 - x0) / 2 - 50, y0 + 20, x0 + (x1 - x0) / 2 + 50, y0 + 32), 6, fill=(60, 60, 66))
        if title:
            self.d.rectangle((inner[0], inner[1], inner[2], inner[1] + 64), fill=bar)
            self.text(((inner[0] + inner[2]) / 2, inner[1] + 32), title, 22, WHITE, True, 'mm')
            return (inner[0] + 18, inner[1] + 84, inner[2] - 18, inner[3] - 18)
        return (inner[0] + 18, inner[1] + 18, inner[2] - 18, inner[3] - 18)

    def step_card(self, box, n, title, body, size=20):
        self.rect(box, WHITE, LINE, 2, 10)
        self.d.rectangle((box[0], box[1], box[2], box[1] + 8), fill=NAVY)
        self.badge((box[0] + 34, box[1] + 46), n)
        self.wrap((box[0] + 64, box[1] + 30), title, box[2] - box[0] - 80, size + 2, NAVY, True)
        self.wrap((box[0] + 22, box[1] + 84), body, box[2] - box[0] - 44, size, TEXT)

    def save(self, path):
        self.im.save(path, optimize=True)


def flow(path, steps, title=None, w=2000, h=520, colors=None):
    """처리 흐름도: steps = [(제목, 설명), ...] 를 화살표로 잇는다. 6개 이하."""
    c = Canvas(w, h, WHITE)
    if title:
        c.text((40, 50), title, 30, NAVY, True, 'lm')
    n = len(steps)
    gap = 56
    bw = (w - 80 - gap * (n - 1)) / n
    y0 = 40 if not title else 110
    for i, (t, s) in enumerate(steps):
        x0 = 40 + i * (bw + gap)
        col = (colors or [NAVY] * n)[i]
        c.rect((x0, y0, x0 + bw, h - 40), WHITE, LINE, 2, 12)
        c.d.rounded_rectangle((x0, y0, x0 + bw, y0 + 90), 12, fill=col)
        c.d.rectangle((x0, y0 + 60, x0 + bw, y0 + 90), fill=col)
        c.wrap((x0 + 22, y0 + 18), f'{i + 1}. {t}', bw - 40, 25, WHITE, True, 4)
        c.wrap((x0 + 22, y0 + 116), s, bw - 44, 22, TEXT, False, 10)
        if i < n - 1:
            c.arrow((x0 + bw + 6, (y0 + h - 40) / 2), (x0 + bw + gap - 6, (y0 + h - 40) / 2))
    c.save(path)
