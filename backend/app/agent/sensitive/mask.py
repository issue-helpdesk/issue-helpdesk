"""A·B 등급 가림 (docs/10 2.3·3.1·3.2). 저장 전 가림(②)과 로그 안전망(5.3 ④)에 쓴다.

규칙은 frontend/src/core/mask.ts 와 같다. 다른 점은 README.md 4장
(휴대폰은 숫자 경계 안에서만 찾음, 유선 번호는 남김, 이름 뒤 '값'·'번호'·'코드' 허용).

- mask_secrets : 비밀정보(A)·고유식별·금융(B)을 ●●●●●● 로 바꾸고 유형별 개수를 돌려준다. 원래 값은 남기지 않는다
- mask_notices : 가린 종류에 맞는 안내 문구 (docs/10 6.1). 문구는 mask.ts·디자인 가이드 문구 사전과 같다
"""
import re
from collections import Counter
from dataclasses import dataclass, field

MASK = '●●●●●●'

# 기록 유형 (docs/10 5.2 SENSITIVE_INPUT 의 result)
SECRET_TYPES = ('PASSWORD', 'OTP', 'API_KEY', 'PRIVATE_KEY')      # A 등급
IDENTITY_TYPES = ('RRN', 'CARD', 'ACCOUNT')                        # B 등급

# 가리지 않는 C 등급 값. 치환(pseudonym.py)도 같은 규칙을 쓴다
PHONE = (r'(?<![0-9])(?:01[016789][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}'      # 휴대폰 (붙여 써도 됨)
         r'|0(?:2|[3-6][1-5]|70)[-\s][0-9]{3,4}[-\s][0-9]{4})(?![0-9])')  # 유선·인터넷 전화 (지역번호 뒤 구분자 필수)
EMAIL = r'[A-Za-z0-9_.+-]+@[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+'
EMP_NO = r'EMP-[0-9]{4}(?![0-9])'

# 이름 뒤에 값이 붙은 비밀번호·인증번호 ("비밀번호는 abc123", "인증번호: 123456", "PIN값이 1245")
LABELED = re.compile(r'(비밀번호|비번|패스워드|암호|인증번호|인증 번호|인증코드|보안코드|OTP|PIN|password|passwd|pwd|pw)'
                     r'((?:값|번호|코드)?\s*(?:는|은|이|가|:|=)\s*)([^\s,]+)', re.IGNORECASE)
PASSWORD_LABEL = re.compile(r'(비밀번호|비번|패스워드|암호|password|passwd|pwd|pw)', re.IGNORECASE)
VALUE_CHAR = re.compile(r'[0-9A-Za-z!@#$%^&*]')     # 값에 숫자·영문·기호가 있을 때만 가린다 ("비밀번호는 사용할 수 없다고" 는 그대로)
PRIVATE_KEY = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)')
KEY_PREFIX = re.compile(r'(?:sk-|ghp_|AKIA|xoxb-|Bearer\s+)[A-Za-z0-9._-]{20,}')
KEY_LABELED = re.compile(r'(API\s?키|토큰|token|secret)(\s*(?:는|은|이|가|:|=)?\s*)([A-Za-z0-9._-]{16,})', re.IGNORECASE)
RRN = re.compile(r'[0-9]{6}-[0-9]{7}')
CARD = re.compile(r'[0-9]{4}([-\s])[0-9]{4}\1[0-9]{4}\1[0-9]{4}')
DASHED = re.compile(r'[0-9]+(?:-[0-9]+)+')          # 숫자를 - 로 이은 묶음. 합계 10자리 이상이면 계좌번호
ACCOUNT_DIGITS = 10
LONG_DIGITS = re.compile(r'[0-9]{6,}')              # 6자리 이상 연속 숫자는 인증번호·OTP 로 본다
# 가리지 않는 값: 전화번호·이메일·사번(C 등급), 0x 오류 코드
KEEP = re.compile(f'{PHONE}|{EMAIL}|{EMP_NO}|0[xX][0-9a-fA-F]+')
SLOT = ''                                    # 남길 값을 잠시 치워 둘 자리 표시 (사용자 글에 나오지 않는 문자)

# 안내 문구 (docs/10 6.1). 첫 줄은 제목, 둘째 줄부터는 설명이다. mask.ts 와 글자까지 같게 둔다
MASK_NOTICE = '민감정보가 감지되었어요.\n입력하신 정보는 안전을 위해 ●●●로 가림 처리했어요. 비밀번호나 인증번호는 입력하지 말아 주세요.'
MASK_NOTICE_PASSWORD = '실제 사용 중인 비밀번호라면 비밀번호 재설정 포털에서 변경해 주세요.'   # 비밀번호였다면 위 설명 뒤에 덧붙인다
MASK_NOTICE_IDENTITY = '개인정보가 감지되었어요.\n입력하신 정보는 안전을 위해 ●●●로 가림 처리했어요. 문의에 필요하지 않은 개인정보는 입력하지 말아 주세요.'
MASK_NOTICE_DRAFT = '민감정보가 가림 처리되었어요.\n입력하신 내용에 민감정보가 포함되어 있어 일부 내용을 가렸어요. 접수 전 내용을 확인해 주세요.'   # TK-03 초안 수정 글
BLOCKED_NOTICE = '담당자의 확인이 필요한 문의예요.\n보안 정책에 따라 AI가 직접 안내하기 어려운 내용이에요. 담당자에게 문의할 수 있도록 도와드릴게요.'   # 근거가 모두 차단됨 (ALL_BLOCKED)


@dataclass(frozen=True)
class Masked:
    text: str
    counts: dict[str, int] = field(default_factory=dict)   # 유형별 가린 개수 (값은 넣지 않는다)

    @property
    def hit(self) -> bool:
        return bool(self.counts)

    @property
    def secret(self) -> bool:
        """비밀정보(A)를 가렸는지"""
        return any(t in self.counts for t in SECRET_TYPES)

    @property
    def password(self) -> bool:
        """그 가운데 비밀번호였는지 (재설정 포털 안내를 덧붙인다, docs/10 6.1)"""
        return 'PASSWORD' in self.counts

    @property
    def identity(self) -> bool:
        """고유식별·금융(B)을 가렸는지"""
        return any(t in self.counts for t in IDENTITY_TYPES)


def mask_secrets(text: str) -> Masked:
    """A·B 등급 값을 ●●●●●● 로 바꾼다. 형식이 분명한 것부터 적용한다 (docs/10 2.3 표 순서).

    예) '비밀번호는 Abc123! 인데' → Masked('비밀번호는 ●●●●●● 인데', {'PASSWORD': 1})
    """
    counts: Counter[str] = Counter()

    def hide(kind: str):
        def repl(_m: re.Match) -> str:
            counts[kind] += 1
            return MASK
        return repl

    def labeled(m: re.Match) -> str:
        key, sep, value = m.groups()
        if not VALUE_CHAR.search(value) or set(value) == {'●'}:
            return m.group(0)
        counts['PASSWORD' if PASSWORD_LABEL.fullmatch(key) else 'OTP'] += 1
        return key + sep + MASK

    def key_labeled(m: re.Match) -> str:
        counts['API_KEY'] += 1
        return m.group(1) + m.group(2) + MASK

    def account(m: re.Match) -> str:
        if len(m.group(0).replace('-', '')) < ACCOUNT_DIGITS:
            return m.group(0)
        counts['ACCOUNT'] += 1
        return MASK

    # 가리면 안 되는 값은 잠시 치워 두었다가 마지막에 되돌린다
    kept: list[str] = []

    def keep(m: re.Match) -> str:
        kept.append(m.group(0))
        return f'{SLOT}{len(kept) - 1}{SLOT}'

    # 자리 표시 문자가 사용자 글에 섞여 있으면 되돌릴 때 헷갈리므로 먼저 지운다 (화면에 보이지 않는 문자)
    out = KEEP.sub(keep, text.replace(SLOT, ''))
    out = PRIVATE_KEY.sub(hide('PRIVATE_KEY'), out)
    out = KEY_PREFIX.sub(hide('API_KEY'), out)
    out = KEY_LABELED.sub(key_labeled, out)
    out = LABELED.sub(labeled, out)
    out = RRN.sub(hide('RRN'), out)
    out = CARD.sub(hide('CARD'), out)
    out = DASHED.sub(account, out)
    out = LONG_DIGITS.sub(hide('OTP'), out)
    out = re.sub(f'{SLOT}([0-9]+){SLOT}', lambda m: kept[int(m.group(1))], out)
    return Masked(out, dict(counts))


def mask_notices(m: Masked) -> list[str]:
    """가린 종류에 맞는 안내 문구들 (비밀정보 → 고유식별·금융 순). 각각 SYSTEM 메시지 하나로 보낸다.

    비밀번호였다면 첫 안내에 재설정 안내가 붙는다. 초안 수정 글은 이 함수 대신 MASK_NOTICE_DRAFT 하나를 쓴다.
    """
    out = []
    if m.secret:
        out.append(f'{MASK_NOTICE} {MASK_NOTICE_PASSWORD}' if m.password else MASK_NOTICE)
    if m.identity:
        out.append(MASK_NOTICE_IDENTITY)
    return out
