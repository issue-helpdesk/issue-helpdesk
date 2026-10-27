"""C·D 등급 치환 (docs/10 3.1 치환 규칙). 외부 모델 호출 직전(④)에 쓴다. DB 에 저장하는 글은 바꾸지 않는다.

- Pseudonymizer : 전화번호(휴대폰·유선)·이메일·사번·직원 이름을 [전화번호N]·[이메일N]·[사번N]·[직원N] 으로 바꾼다.
  외부 모델을 한 번 부를 때마다 새로 만들고, 이전 대화(history) → 이번 글(message) 순서로 apply 한다.
  처음 나온 순서대로 번호를 매기므로 같은 사람은 같은 번호가 된다. 대응표는 밖으로 내보내지 않는다 (호출이 끝나면 버린다).
"""
import re
from collections.abc import Iterable

from app.agent.sensitive.mask import EMAIL, EMP_NO, PHONE   # 가림에서 남긴 값을 여기서 바꾼다

LABELS = {'phone': '전화번호', 'email': '이메일', 'emp': '사번', 'name': '직원'}


def _same(kind: str, value: str) -> str:
    """같은 값을 다르게 쓴 것을 하나로 본다 (010-1234-5678 = 01012345678, 대소문자가 다른 이메일)"""
    if kind == 'phone':
        return re.sub(r'[^0-9]', '', value)
    return value.lower()


class Pseudonymizer:
    def __init__(self, staff_names: Iterable[str] = ()):
        """staff_names: 직원 이름 목록 (users.name). 긴 이름부터 맞춰 '김민지' 안의 '민지' 같은 짧은 이름이 먼저 걸리지 않게 한다."""
        names = sorted({n.strip() for n in staff_names if n and n.strip()}, key=len, reverse=True)
        parts = [f'(?P<email>{EMAIL})', f'(?P<phone>{PHONE})', f'(?P<emp>{EMP_NO})']
        if names:
            parts.append('(?P<name>' + '|'.join(map(re.escape, names)) + ')')
        self._pattern = re.compile('|'.join(parts))
        self._numbers: dict[tuple[str, str], int] = {}
        self._next: dict[str, int] = {}

    def apply(self, text: str) -> str:
        """예) '김민지 팀장님 010-1234-5678로 연락 주세요' → '[직원1] 팀장님 [전화번호1]로 연락 주세요'"""
        return self._pattern.sub(self._replace, text)

    def _replace(self, m: re.Match) -> str:
        kind = m.lastgroup
        key = (kind, _same(kind, m.group(0)))
        if key not in self._numbers:
            self._next[kind] = self._next.get(kind, 0) + 1
            self._numbers[key] = self._next[kind]
        return f'[{LABELS[kind]}{self._numbers[key]}]'
