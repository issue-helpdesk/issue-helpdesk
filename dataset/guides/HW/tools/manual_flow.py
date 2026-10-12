"""담당자 매뉴얼(-M)의 항목마다 '처리 흐름도' 그림을 만들어 docx·pptx에 넣는다.

그림의 글은 모두 매뉴얼 docx의 해당 항목에서 그대로 읽어 온다 (새로 쓰는 문장 없음).
접수 시 확인 질문 → 판단 기준 → 처리 절차 → 처리 후 안내 문구 / 재발 방지 / 이관 시 전달 정보.

- docx: 항목 제목 아래 정보 표 바로 뒤에 그림과 그림 설명을 넣는다.
- pptx: 항목의 마지막 장 뒤에 '처리 흐름도' 장을 추가한다.
그림 표·설명의 서식은 짝이 되는 사용자 가이드(guide/)의 것을 본뜬다. 이미 넣은 항목은 건너뛴다.

실행: python dataset/guides/HW/tools/manual_flow.py
"""
import copy
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Emu
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation

HW = Path(__file__).resolve().parent.parent
FONT_DIR = Path("C:/Windows/Fonts")
W, H = 2400, 1040
INK, SUB, NAVY, LINE = "#1B1B1B", "#5F6368", "#1F3864", "#B5B5B5"
PRIORITY = {"P1": "#C50F1F", "P2": "#D83B01", "P3": "#0067C0", "P4": "#5F6368"}
SECTIONS = ["접수 시 확인 질문", "판단 기준", "처리 절차", "처리 후 안내 문구", "재발 방지", "이관 시 전달 정보"]
CAPTION = "처리 흐름도. 접수 시 확인 질문, 판단 기준, 처리 절차, 처리 후 안내와 이관 정보를 순서대로 표시한다."


def font(size, bold=False):
    return ImageFont.truetype(str(FONT_DIR / ("malgunbd.ttf" if bold else "malgun.ttf")), size)


# ---------------------------------------------------------------- 매뉴얼 읽기
def _text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _style(el):
    ppr = el.find(qn("w:pPr"))
    st = ppr.find(qn("w:pStyle")) if ppr is not None else None
    return st.get(qn("w:val")) if st is not None else ""


def read_blocks(doc):
    """3장의 항목을 읽는다. 항목 = {no, title, info(dict), info_tbl(요소), 소제목: [줄...]}"""
    blocks, cur, sec = [], None, None
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            st, tx = _style(el), _text(el).strip()
            if st == "Heading1":
                cur = None
            elif st == "Heading2" and re.match(r"3\.\d+ ", tx):
                no, title = tx.split(" ", 1)
                cur = {"no": no, "title": title, "info": {}, "info_tbl": None, **{s: [] for s in SECTIONS}}
                blocks.append(cur)
                sec = None
            elif cur is not None and st == "Heading3":
                sec = tx if tx in SECTIONS else None
            elif cur is not None and sec and tx and not tx.startswith("그림 "):
                cur[sec].append(tx)
        elif el.tag == qn("w:tbl") and cur is not None and cur["info_tbl"] is None:
            cells = [_text(tc).strip() for tc in el.iter(qn("w:tc"))]
            cur["info"] = dict(zip(cells[0::2], cells[1::2]))
            cur["info_tbl"] = el
    return blocks


# ---------------------------------------------------------------- 그림
def wrap(d, text, f, width):
    """낱말 단위로 줄을 나눈다."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}" if cur else word
        if cur and d.textlength(trial, font=f) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def box(d, x, y, w, h, num, title, items, color, fill, numbered=False, quote=False):
    d.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill, outline=color, width=3)
    d.rounded_rectangle([x, y, x + w, y + 70], radius=16, fill=color)
    d.rectangle([x, y + 40, x + w, y + 70], fill=color)
    d.ellipse([x + 18, y + 11, x + 66, y + 59], fill="white")
    d.text((x + 42, y + 35), str(num), font=font(28, True), fill=color, anchor="mm")
    d.text((x + 84, y + 35), title, font=font(29, True), fill="white", anchor="lm")
    for size in (33, 30, 27, 25, 23, 21, 19):
        f = font(size)
        lh = int(size * 1.42)
        indent = 44
        laid = [wrap(d, it, f, w - 56 - indent) for it in items]
        total = sum(len(ls) * lh + 14 for ls in laid)
        if total <= h - 100:
            break
    cy = y + 92
    for i, ls in enumerate(laid):
        mark = f"{i + 1}." if numbered else ("“" if quote else "•")
        d.text((x + 28, cy), mark, font=font(size, True), fill=color)
        for ln in ls:
            d.text((x + 28 + indent, cy), ln, font=f, fill=INK)
            cy += lh
        cy += 14


def arrow_right(d, x1, x2, y):
    d.polygon([(x1, y - 14), (x2 - 30, y - 14), (x2 - 30, y - 34), (x2, y), (x2 - 30, y + 34), (x2 - 30, y + 14),
               (x1, y + 14)], fill=NAVY)


def draw(block, out):
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((30, 62), f"{block['no']} 처리 흐름", font=font(40, True), fill=NAVY, anchor="lm")
    # 정보 칩 (오른쪽 정렬)
    x = W - 30
    for k in reversed(list(block["info"])):
        v = block["info"][k]
        kw, vw = d.textlength(k, font=font(24)), d.textlength(v, font=font(26, True))
        cw = int(kw + vw + 62)
        col = PRIORITY.get(v, NAVY) if k == "기본 긴급도" else NAVY
        d.rounded_rectangle([x - cw, 32, x, 92], radius=30, fill="#EEF2F7", outline=col, width=3)
        d.text((x - cw + 24, 62), k, font=font(24), fill=SUB, anchor="lm")
        d.text((x - 24, 62), v, font=font(26, True), fill=col, anchor="rm")
        x -= cw + 16
    cw_, gap = 746, 61
    xs = [30, 30 + cw_ + gap, 30 + 2 * (cw_ + gap)]
    y1, h1, y2, h2 = 130, 500, 690, 290
    box(d, xs[0], y1, cw_, h1, 1, "접수 시 확인 질문", block["접수 시 확인 질문"], NAVY, "#F4F7FB")
    box(d, xs[1], y1, cw_, h1, 2, "판단 기준", block["판단 기준"], "#B7791F", "#FFFBEB")
    box(d, xs[2], y1, cw_, h1, 3, "처리 절차", block["처리 절차"], "#107C10", "#F2FAF2", numbered=True)
    for i in (0, 1):
        arrow_right(d, xs[i] + cw_ + 6, xs[i + 1] - 6, y1 + h1 // 2)
    # 처리 뒤 마무리
    cx = xs[2] + cw_ // 2
    d.polygon([(cx - 14, y1 + h1 + 6), (cx + 14, y1 + h1 + 6), (cx + 14, y2 - 34), (cx + 34, y2 - 34), (cx, y2 - 4),
               (cx - 34, y2 - 34), (cx - 14, y2 - 34)], fill=NAVY)
    box(d, xs[2], y2, cw_, h2, 4, "처리 후 안내 문구", [t.strip('"“”') for t in block["처리 후 안내 문구"]], "#0067C0",
        "#F0F6FC", quote=True)
    box(d, xs[1], y2, cw_, h2, 5, "재발 방지", block["재발 방지"], "#5F6368", "#F7F7F7")
    box(d, xs[0], y2, cw_, h2, 6, "이관 시 전달 정보", block["이관 시 전달 정보"], "#5F6368", "#F7F7F7")
    d.text((W / 2, H - 24), f"※ {block['no']} 항목의 내용을 한 장으로 정리한 처리 흐름도입니다. 세부 내용은 본문을 따릅니다.",
           font=font(22), fill=SUB, anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)


# ---------------------------------------------------------------- 문서에 넣기
def _set_caption(runs, no):
    runs[0].text = f"그림 {no}. "
    runs[1].text = CAPTION
    for r in runs[2:]:
        r.text = ""


def fill_docx(path, doc_id, guide_docx):
    doc = Document(str(path))
    blocks = read_blocks(doc)
    for b in blocks:
        draw(b, HW / "images" / f"{doc_id}_fig{b['no']}.png")
    gbody = list(Document(str(guide_docx)).element.body.iterchildren())
    tpl_tbl = next(c for c in gbody if c.tag == qn("w:tbl") and c.findall(".//" + qn("w:drawing")))
    tpl_cap = gbody[gbody.index(tpl_tbl) + 1]
    width = Emu((int(tpl_tbl.tblPr.find(qn("w:tblW")).get(qn("w:w"))) - 260) * 635)
    existing = _text(doc.element.body)
    n = 0
    for b in blocks:
        no = b["no"]
        if f"그림 {no}. " in existing:
            continue
        tbl, capp = copy.deepcopy(tpl_tbl), copy.deepcopy(tpl_cap)
        b["info_tbl"].addnext(capp)
        b["info_tbl"].addnext(tbl)
        para = Table(tbl, doc._body).cell(0, 0).paragraphs[0]
        for r in list(para.runs):
            r._r.getparent().remove(r._r)
        pic = para.add_run().add_picture(str(HW / "images" / f"{doc_id}_fig{no}.png"), width=width)
        pic._inline.docPr.set("descr", f"그림 {no}. {CAPTION}")
        _set_caption(Paragraph(capp, doc._body).runs, no)
        n += 1
    if n:
        doc.save(str(path))
    return [b["no"] for b in blocks], n


def _kicker(slide):
    sh = list(slide.shapes)[0]
    return sh.text_frame.text if sh.has_text_frame else ""


def fill_pptx(path, doc_id, guide_pptx, numbers):
    prs = Presentation(str(path))
    gtpl = next(s for s in Presentation(str(guide_pptx)).slides if _kicker(s).endswith("화면 예시"))
    tpl_cap = next(s for s in gtpl.shapes if s.has_text_frame and s.text_frame.text.startswith("그림"))
    tpl_pic = next(s for s in gtpl.shapes if s.shape_type == 13)
    have = " ".join(s.text_frame.text for sl in prs.slides for s in sl.shapes if s.has_text_frame)
    n = 0
    for no in numbers:
        if f"그림 {no}. " in have:
            continue
        slides = list(prs.slides)
        idx = max(i for i, s in enumerate(slides) if f"· {no} " in _kicker(s))
        src = list(slides[idx].shapes)
        new = prs.slides.add_slide(slides[idx].slide_layout)
        for ph in list(new.placeholders):
            ph._element.getparent().remove(ph._element)
        for s in (src[0], src[1]):
            new.shapes._spTree.append(copy.deepcopy(s._element))
        runs = new.shapes[0].text_frame.paragraphs[0].runs
        runs[-1].text = re.sub(r"(\d+\.\d+) .*$", r"\1 처리 흐름도", runs[-1].text)
        pic = new.shapes.add_picture(str(HW / "images" / f"{doc_id}_fig{no}.png"),
                                     tpl_pic.left, tpl_pic.top, tpl_pic.width, tpl_pic.height)
        pic._element.nvPicPr.cNvPr.set("descr", f"그림 {no}. {CAPTION}")
        new.shapes._spTree.append(copy.deepcopy(tpl_cap._element))
        _set_caption([r for p in new.shapes[-1].text_frame.paragraphs for r in p.runs], no)
        new.shapes._spTree.append(copy.deepcopy(src[-1]._element))
        ids = prs.slides._sldIdLst
        el = ids[-1]
        ids.remove(el)
        ids.insert(idx + 1, el)
        n += 1
    if n:
        prs.save(str(path))
    return n


if __name__ == "__main__":
    for docx in sorted((HW / "manual").glob("*.docx")):
        doc_id = docx.name.split("_")[0]                      # IT-HW-001-M
        guide = next((HW / "guide").glob(doc_id[:-2] + "_*.docx"))
        numbers, a = fill_docx(docx, doc_id, guide)
        b = fill_pptx(docx.with_suffix(".pptx"), doc_id, guide.with_suffix(".pptx"), numbers)
        print(doc_id, "항목", len(numbers), "docx", a, "pptx", b)
