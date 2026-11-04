import re


def first_line_summary(text: str, max_length: int) -> str:
    """글의 첫 내용 줄을 공백을 정리해 돌려준다. 길면 잘라 말줄임표를 붙인다 (결과는 max_length 이내). 내용이 없으면 빈 글자."""
    line = next((stripped for raw in text.splitlines() if (stripped := re.sub(r"\s+", " ", raw).strip())), "")
    return line if len(line) <= max_length else f"{line[:max_length - 1].rstrip()}…"
