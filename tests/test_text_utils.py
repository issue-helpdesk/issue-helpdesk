import pytest

from app.utils.text_utils import first_line_summary


@pytest.mark.parametrize("text, limit, expected", [
    ("VPN 접속 불가", 40, "VPN 접속 불가"),
    ("\n  \n 첫 줄  내용 \n둘째 줄", 40, "첫 줄 내용"),
    ("가나다라마", 5, "가나다라마"),
    ("가나다라마바", 5, "가나다라…"),
    ("가나 다라마바", 4, "가나…"),
    ("  \n ", 40, ""),
    ("", 40, ""),
])
def test_first_line_summary(text, limit, expected):
    assert first_line_summary(text, limit) == expected
