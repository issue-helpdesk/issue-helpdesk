"""docx·pdf 생성: python make_all.py [001 002 ...]

1) docx 생성 → 2) LibreOffice로 PDF 변환 → 3) PDF에서 장 구분 페이지를 찾아 목차 쪽 번호를 채워 다시 생성·변환.
"""
import importlib, os, re, subprocess, sys
import pymupdf
import render

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SOFFICE = r'C:\Program Files\LibreOffice\program\soffice.exe'
G_KEYS = [('01', '개요', 'c1'), ('02', '먼저 확인할 사항', 'c2'), ('03', '증상별 조치 방법', 'c3'), ('04', '자주 묻는 질문', 'c4'),
          ('05', '주의사항', 'c5'), ('06', '문의처', 'c6'), ('부록', '관련 문서 · 용어 · 개정 이력', 'c7')]
M_KEYS = [('01', '개요', 'c1'), ('02', '접수·분류 기준', 'c2'), ('03', '증상별 처리 절차', 'c3'), ('04', '대형 장애 대응', 'c4'),
          ('05', '처리 기록 기준', 'c5'), ('부록', '내부 연락처 · 개정 이력', 'c6')]


def to_pdf(docx):
    out = os.path.dirname(docx)
    subprocess.run([SOFFICE, '--headless', '--convert-to', 'pdf:writer_pdf_Export:{"ExportBookmarks":{"type":"boolean","value":"true"},"UseTaggedPDF":{"type":"boolean","value":"true"}}',
                    '--outdir', out, docx], check=True, capture_output=True)
    return os.path.splitext(docx)[0] + '.pdf'


def find_pages(pdf, keys):
    d = pymupdf.open(pdf)
    res = {}
    for i, p in enumerate(d):
        lines = [l.strip() for l in p.get_text().splitlines()
                 if l.strip() and not l.strip().startswith('©') and not re.fullmatch(r'\d+ / \d+', l.strip())]
        for num, title, key in keys:
            if key not in res and len(lines) >= 2 and lines[0] == num and lines[1] == title:
                res[key] = i + 1
    d.close()
    return res


HEADS = {'문서 정보', 'Contents', '개요', '먼저 확인할 사항', '증상별 조치 방법', '자주 묻는 질문', '주의사항', '문의처', '부록',
         '접수·분류 기준', '증상별 처리 절차', '대형 장애 대응', '처리 기록 기준', '01', '02', '03', '04', '05', '06', '━━━━━'}


def overflow_pages(pdf):
    """페이지 머리(제목)로 시작하지 않는 쪽 = 앞 쪽에서 넘친 쪽."""
    out = []
    for i, p in enumerate(pymupdf.open(pdf)):
        lines = [l.strip() for l in p.get_text().splitlines()
                 if l.strip() and not l.strip().startswith('©') and not re.fullmatch(r'\d+ / \d+', l.strip())]
        if not lines or lines[0] not in HEADS:
            out.append(i + 1)
    return out


def make(doc, kind, folder, keys):
    fn = render.guide if kind == 'guide' else render.manual
    m = doc['meta']
    path = os.path.join(ROOT, folder, f"{m['doc_no']}_{m['title']}.docx")
    fn(doc).save(path)
    pages = find_pages(to_pdf(path), keys)
    fn(doc, pages).save(path)
    pdf = to_pdf(path)
    n = len(pymupdf.open(pdf))
    print(f"{os.path.basename(path)}: {n}쪽, 목차 {pages}")
    for pg in overflow_pages(pdf):
        print(f"  ! 넘침 의심: {pg}쪽")
    return path, pdf


if __name__ == '__main__':
    which = sys.argv[1:] or ['001', '002', '003', '004']
    for w in which:
        mod = importlib.import_module(f'content_{w}')
        make(mod.GUIDE, 'guide', 'guide', G_KEYS)
        make(mod.MANUAL, 'manual', 'manual', M_KEYS)
