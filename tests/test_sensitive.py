"""민감정보 필터 (M4-2-3) 테스트. 예시는 docs/10 6.3 시험 예시 그대로."""
import pytest

from app.agent.sensitive import (MASK_NOTICE, MASK_NOTICE_IDENTITY, MASK_NOTICE_PASSWORD, Pseudonymizer, mask_notices,
                                 mask_secrets)

STAFF = ['김민지', '박서준']


def external(text: str) -> str:
    """외부 모델에 가는 글 = 저장 전 가림(②)을 거친 글을 치환(④)"""
    return Pseudonymizer(STAFF).apply(mask_secrets(text).text)


# (입력, ② 저장되는 글, ④ 외부 모델에 가는 글, 기록 유형). None 은 '앞 칸과 같음'
CASES = [
    ('비밀번호는 Abc123! 인데 로그인이 안 돼요', '비밀번호는 ●●●●●● 인데 로그인이 안 돼요', None, 'PASSWORD'),
    ('비번: qwer1234', '비번: ●●●●●●', None, 'PASSWORD'),
    ('OTP 482913 넣었는데 실패해요', 'OTP ●●●●●● 넣었는데 실패해요', None, 'OTP'),
    ('API 키는 sk-abcdefghijklmnopqrstuvwx 입니다', 'API 키는 ●●●●●● 입니다', None, 'API_KEY'),
    ('주민번호 900101-1234567 입력하라고 떠요', '주민번호 ●●●●●● 입력하라고 떠요', None, 'RRN'),
    ('카드 1234-5678-9012-3456 결제가 안 돼요', '카드 ●●●●●● 결제가 안 돼요', None, 'CARD'),
    ('환불 계좌 110-123-456789 로 부탁해요', '환불 계좌 ●●●●●● 로 부탁해요', None, 'ACCOUNT'),
    ('김민지 팀장님 010-1234-5678로 연락 주세요', None, '[직원1] 팀장님 [전화번호1]로 연락 주세요', None),
    ('minji.kim@ict.example 메일이 안 와요', None, '[이메일1] 메일이 안 와요', None),
    ('EMP-1001 권한 요청합니다', None, '[사번1] 권한 요청합니다', None),
    ('인증 문자가 01012345678로 안 와요', None, '인증 문자가 [전화번호1]로 안 와요', None),
    ('인증번호가 안 와요', None, None, None),
    ('비밀번호는 사용할 수 없다고 나와요', None, None, None),
    ('오류 코드 0x80070005 가 떠요', None, None, None),
    ('내선 1119로 전화했어요', None, None, None),
    ('2026-10-25 오전부터 안 돼요', None, None, None),
    ('IP 10.20.30.40 서버 접속이 안 돼요', None, None, None),
    ('어제 바꾼 거 qwer1234! 인데 안 돼요', None, None, None),     # 한계 (6.2): 이름 없이 쓴 비밀번호
    ('김 팀장님이 승인했어요', None, None, None),                  # 한계 (6.2): 명부에 없는 표기
]


@pytest.mark.parametrize('no, text, stored, sent, kind', [(i, *c) for i, c in enumerate(CASES, 1)])
def test_policy_examples(no, text, stored, sent, kind):
    stored = stored or text
    m = mask_secrets(text)
    assert m.text == stored
    assert external(text) == (sent or stored)
    assert m.counts == ({kind: 1} if kind else {})


def test_same_person_same_number_across_history_and_message():
    p = Pseudonymizer(STAFF)
    history = [p.apply('김민지 팀장님께 여쭤봤어요'), p.apply('박서준 님도 같은 증상이에요')]
    message = p.apply('김민지 팀장님이 박서준 님 권한도 요청하래요')
    assert history == ['[직원1] 팀장님께 여쭤봤어요', '[직원2] 님도 같은 증상이에요']
    assert message == '[직원1] 팀장님이 [직원2] 님 권한도 요청하래요'


def test_same_phone_written_differently_gets_same_number():
    p = Pseudonymizer()
    assert p.apply('010-1234-5678 이요, 아니 01012345678, 010 9999 0000') == '[전화번호1] 이요, 아니 [전화번호1], [전화번호2]'


def test_new_pseudonymizer_starts_numbering_again():
    """대응표는 호출마다 버린다 (docs/10 3.1)"""
    assert Pseudonymizer(STAFF).apply('박서준') == '[직원1]'
    assert Pseudonymizer(STAFF).apply('박서준') == '[직원1]'


def test_counts_each_type_separately():
    m = mask_secrets('비밀번호는 Abc123! 이고 주민번호 900101-1234567, 인증번호: 123456, 비번=zxcv9876')
    assert m.counts == {'PASSWORD': 2, 'RRN': 1, 'OTP': 1}
    assert (m.secret, m.password, m.identity, m.hit) == (True, True, True, True)


def test_private_key_block():
    m = mask_secrets('키 보내요\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAK\n-----END RSA PRIVATE KEY-----\n확인 부탁')
    assert m.text == '키 보내요\n●●●●●●\n확인 부탁'
    assert m.counts == {'PRIVATE_KEY': 1}


def test_original_values_left_nowhere():
    secrets = ['Abc123!', '900101-1234567', 'sk-abcdefghijklmnopqrstuvwx', '482913']
    m = mask_secrets(f'비밀번호는 {secrets[0]} 주민번호 {secrets[1]} 키 {secrets[2]} OTP {secrets[3]}')
    dumped = repr(m) + repr(m.counts)
    assert not any(s in dumped for s in secrets)


@pytest.mark.parametrize('text, stored, kind', [
    ('Bearer abcdefghijklmnopqrstuvwxyz', '●●●●●●', 'API_KEY'),
    ('ghp_abcdefghijklmnopqrstuvwxyz', '●●●●●●', 'API_KEY'),
    ('AKIAABCDEFGHIJKLMNOPQRST', '●●●●●●', 'API_KEY'),
    ('xoxb-12345678901234567890ab', '●●●●●●', 'API_KEY'),
    ('secret: abcdefghijklmnop12', 'secret: ●●●●●●', 'API_KEY'),
    ('PIN: 1234', 'PIN: ●●●●●●', 'OTP'),
    ('카드 1234 5678 9012 3456', '카드 ●●●●●●', 'CARD'),
])
def test_rules_not_in_policy_examples(text, stored, kind):
    """docs/10 2.3 규칙 가운데 6.3 시험 예시에 없는 것"""
    m = mask_secrets(text)
    assert (m.text, m.counts) == (stored, {kind: 1})


@pytest.mark.parametrize('text, stored, kind', [
    ('PIN값이 1245', 'PIN값이 ●●●●●●', 'OTP'),
    ('PIN번호는 1245', 'PIN번호는 ●●●●●●', 'OTP'),
    ('OTP코드: 4821', 'OTP코드: ●●●●●●', 'OTP'),
    ('비밀번호값은 abc12', '비밀번호값은 ●●●●●●', 'PASSWORD'),
    ('비밀번호값은 모르겠어요', '비밀번호값은 모르겠어요', None),       # 값에 숫자·영문이 없음
    ('PIN번호가 틀렸대요', 'PIN번호가 틀렸대요', None),
])
def test_label_with_value_word(text, stored, kind):
    """이름과 구분자 사이에 '값'·'번호'·'코드'가 끼어도 잡는다 (docs/10 2.3)"""
    m = mask_secrets(text)
    assert (m.text, m.counts) == (stored, {kind: 1} if kind else {})


@pytest.mark.parametrize('text, sent', [
    ('대표번호 02-1234-5678로 걸었어요', '대표번호 [전화번호1]로 걸었어요'),
    ('031-123-4567 매장이에요', '[전화번호1] 매장이에요'),
    ('070 1234 5678 인터넷 전화', '[전화번호1] 인터넷 전화'),
])
def test_landline_is_c_grade(text, sent):
    """유선 전화는 휴대폰과 같은 C 등급: 저장은 그대로, 외부 모델에는 치환 (계좌로 가리지 않는다)"""
    assert mask_secrets(text).text == text
    assert external(text) == sent


def test_placeholder_char_in_input_does_not_break():
    """가림 안에서 쓰는 자리 표시 문자(U+E000)가 사용자 글에 있어도 오류 없이 가린다"""
    assert mask_secrets('a0b 비번: qwer1234 hong@a.com').text == 'a0b 비번: ●●●●●● hong@a.com'


def test_phone_inside_longer_number_is_not_kept():
    """mask.ts 와 다른 점: 긴 숫자 안의 휴대폰 모양은 휴대폰으로 보지 않는다"""
    assert mask_secrets('자산 12301012345678').text == '자산 ●●●●●●'


def test_notices_by_kind():
    """docs/10 6.1. frontend/tests/refine.test.tsx 의 문구 예시와 같다"""
    assert mask_notices(mask_secrets('인증번호: 123456')) == [MASK_NOTICE]
    assert mask_notices(mask_secrets('비밀번호는 abc12345')) == [f'{MASK_NOTICE} {MASK_NOTICE_PASSWORD}']
    assert mask_notices(mask_secrets('주민번호 900101-1234567')) == [MASK_NOTICE_IDENTITY]
    assert mask_notices(mask_secrets('비번: qwer1234 카드 1234-5678-9012-3456')) == [
        f'{MASK_NOTICE} {MASK_NOTICE_PASSWORD}', MASK_NOTICE_IDENTITY]
    assert mask_notices(mask_secrets('그냥 문장')) == []


def test_notices_same_as_frontend():
    """서버가 보낸 문구를 화면이 그대로 보여 주므로 mask.ts 와 글자까지 같아야 한다"""
    import re
    from pathlib import Path

    import app.agent.sensitive.mask as server

    ts = (Path(__file__).parents[1] / 'frontend/src/core/mask.ts').read_text(encoding='utf-8')
    names = ['MASK_NOTICE', 'MASK_NOTICE_PASSWORD', 'MASK_NOTICE_IDENTITY', 'MASK_NOTICE_DRAFT', 'BLOCKED_NOTICE']
    for name in names:
        front = re.search(rf"export const {name} = '(.*)'", ts).group(1).replace('\\n', '\n')
        assert getattr(server, name) == front, name


@pytest.mark.parametrize('text, stored', [
    ('제 비밀번호는 abc12345 입니다', '제 비밀번호는 ●●●●●● 입니다'),
    ('주문번호 12345678 확인', '주문번호 ●●●●●● 확인'),
    ('비밀번호를 잊어버렸어요', '비밀번호를 잊어버렸어요'),
    ('비번은 Abc123!', '비번은 ●●●●●●'),
    ('인증코드: 4821a9', '인증코드: ●●●●●●'),
    ('토큰은 abcdefghijklmnop1234', '토큰은 ●●●●●●'),
    ('키는 sk-abcdefghijklmnopqrstuvwx 입니다', '키는 ●●●●●● 입니다'),
    ('카드 1234-5678-9012-3456', '카드 ●●●●●●'),
    ('계좌 110-123-456789', '계좌 ●●●●●●'),
    *[(keep, keep) for keep in ['010-1234-5678', 'hong@company.com', 'EMP-1001', '내선 1000', '10.20.30.40', '0x80070005']],
])
def test_same_as_frontend_mask(text, stored):
    """frontend/tests/refine.test.tsx 의 가림 예시와 같은 결과 (서버·화면 규칙 일치, docs/10 2.3)"""
    assert mask_secrets(text).text == stored
