"""근거 문장 고르기와 검색어 만들기 (M3). 규칙 설명은 search/README.md.

- pick_evidence : 검색 결과 본문에서 질문과 단어가 많이 겹치는 줄을 최대 3개 고른다. 없으면 빈 튜플
- build_query   : 사용자가 여러 번 쓴 글을 시간순으로 이어 붙여 검색어를 만든다. 길면 오래된 글부터 뺀다
"""
import re

from app.rag.search.result import MAX_EVIDENCE

MIN_SHARED = 2              # 이보다 적게 겹치는 줄은 근거로 고르지 않는다
MIN_LINE_CHARS = 6          # '- 사번' 같은 짧은 줄은 근거로 쓰지 않는다
MAX_QUERY_CHARS = 1500      # 검색어 상한. 임베딩 입력 한도 1024토큰에 여유를 둔 값 (가이드 글 기준 1토큰 ≈ 2자)

WORD = re.compile(r'[0-9A-Za-z가-힣]+')
LIST_MARK = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s+')
# 문장 끝·높임 표현은 거의 모든 줄에 있어 겹쳐도 근거가 아니다
# 이 소제목 아래 목록은 문의할 때 알려 줄 항목·준비물이라 해결 근거가 아니다
SKIP_SECTIONS = ('문의 시 알려 주실 정보', '이관 시 전달 정보', '준비할 정보', '준비할 것')
ENDINGS = {'니다', '습니', '합니', '니까', '해요', '어요', '아요', '세요', '에요', '이요', '네요', '하다', '한다', '된다'}


def _pieces(text: str, with_heads: bool = False) -> set[str]:
    """단어를 두 글자씩 자른 조각. 조사가 붙어도 겹치게 한다 ('복구 키를' ↔ '복구 키').

    한 글자 단어는 그대로 쓰고, with_heads 면 단어 첫 글자도 넣어 질문의 한 글자 단어('키')와 맞춘다.
    """
    out = set()
    for w in WORD.findall(text.lower()):
        if len(w) == 1:
            out.add(w)
            continue
        out.update(w[i:i + 2] for i in range(len(w) - 1))
        if with_heads:
            out.add(w[0])
    return out - ENDINGS


def _candidates(text: str):
    """근거가 될 수 있는 줄. 머리말(문서 > 장 > 항목), 소제목, 속성 줄, 그림 줄, 짧은 줄,
    '문의 시 알려 주실 정보' 같은 준비 항목 목록은 뺀다."""
    skip = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('#'):
            skip = s.lstrip('#').strip() in SKIP_SECTIONS
            continue
        if skip or not s or s.startswith('[그림]') or ' > ' in s or s.startswith('|'):
            continue
        if re.match(r'^[^:]{1,12}: .+ · .+: ', s):          # '문의 유형: HW-02 · 처리 구분: …'
            continue
        s = LIST_MARK.sub('', s).strip()
        if len(s) >= MIN_LINE_CHARS:
            yield s


def pick_evidence(query: str, text: str, limit: int = MAX_EVIDENCE) -> tuple[str, ...]:
    """질문과 겹치는 조각이 많은 줄부터 최대 limit 개. 겹침이 MIN_SHARED 보다 적으면 고르지 않는다.

    돌려주는 줄은 text 안에 그대로 있는 글이다 (목록 기호만 뗀다).
    """
    q = _pieces(query)
    if not q:
        return ()
    scored = []
    for order, line in enumerate(_candidates(text)):
        shared = len(q & _pieces(line, with_heads=True))
        if shared >= MIN_SHARED:
            scored.append((-shared, order, line))
    picked, seen = [], set()
    for _, _, line in sorted(scored):
        if line not in seen:
            picked.append(line)
            seen.add(line)
        if len(picked) == limit:
            break
    return tuple(picked)


def build_query(user_messages: list[str], max_chars: int = MAX_QUERY_CHARS) -> str:
    """검색어 = 이 문의를 연 뒤(다시 열면 그 이후부터) 사용자가 쓴 글을 시간순으로 이어 붙인 것.

    AI 메시지는 넣지 않는다. 길면 오래된 글부터 빼고, 가장 최근 글 하나가 혼자 길면 앞부분만 쓴다.
    예) ['VPN이 안 돼요', '691번이요'] → 'VPN이 안 돼요\\n691번이요'
    """
    msgs = [m.strip() for m in user_messages if m and m.strip()]
    if not msgs:
        raise ValueError('사용자 글이 없습니다')
    kept, total = [], 0
    for m in reversed(msgs):
        add = len(m) + (1 if kept else 0)
        if kept and total + add > max_chars:
            break
        kept.append(m)
        total += add
    return '\n'.join(reversed(kept))[:max_chars]
