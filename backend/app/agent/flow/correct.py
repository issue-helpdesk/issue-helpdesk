"""AI 출력 보정 (docs/08 3.2 4~9단계와 처리 방향 보정). 판단 흐름의 보정 노드(correct_first·correct_second)가 쓴다.

- unsafe_reply : 9단계. reply 가 비밀번호·인증번호·API 키를 달라고 하거나, 접수·배정됐다고 말하는가
- correct      : 4~8단계와 처리 방향 보정. 바꾼 것은 override_reasons 항목(08 5.4)으로 함께 돌려준다

1~3단계(버전·JSON·필수 키)는 call_judge 가 한다. 9단계에서 다시 부르는 일은 graph.py 가 한다.
"""
import os
import re
from dataclasses import dataclass

from app.agent.llm import AIInput, AIOutput, Facts, Taxonomy
from app.agent.llm.schemas import (ACTIONS, CATEGORY_CODES, ESCALATION_REASONS, EVIDENCE_KINDS, IMPACT_SCOPES,
                                   MISSING_ITEMS, REQUEST_KINDS, URGENCIES, WORK_STOPPED)
from app.agent.sensitive import Filtered
from app.rag.search import SearchResponse

TITLE_MAX = 255                                     # inquiries.title
ASKED_LATER = ('occurred_at', 'tried_actions')      # 판단 단계에서 묻지 않고 초안 단계에서 묻는다 (08 3.1)
LIMIT_RULES = ('ASK_MORE_UNANSWERED', 'ASK_MORE_LIMIT')

# 9단계 검사. 문장 하나에 "하지 마세요"가 있으면 안내로 보고 넘긴다 ("비밀번호는 알려 주지 마세요")
SENTENCE = re.compile(r'[^.!?\n]+')
DONT = re.compile(r'마세요|말아|않|금지|절대')
# 비밀값을 사용자에게 달라고 부탁할 때만 ("비밀번호를 알려 주세요"·"인증번호 6자리를 보내주시면").
# "알려 드릴게요"는 안내이고, 사이에 "~면"·"~거나" 같은 다른 말이 끼면 비밀값을 달라는 말이 아니다
# ("인증번호를 받을 수 없으면 말씀해 주세요"). 사이 낱말은 3개까지만 본다
ASK_SECRET = re.compile(r'(?:비밀번호|비번|패스워드|암호(?!화)|인증번호|인증 번호|인증코드|보안코드|OTP|PIN|API\s?키|토큰|password)'
                        r'\S*(?:\s+(?!\S*(?:면|거나|지만|는데)(?:\s|$))\S+){0,3}?\s*'
                        r'(?:(?:알려|보내|적어|말씀해|공유해|전달해|남겨)\s?주|(?:여기|채팅|이곳)\S*\s*입력)', re.IGNORECASE)
# "접수됐어요"·"티켓을 생성했어요"·"담당자가 배정됐어요". 동사가 바로 붙어야 한다 ("접수 전 내용을 확인했어요"는 아님)
CLAIM_DONE = re.compile(r'(?:접수|(?:티켓|Ticket)\S*\s?(?:생성|발행)|담당자\S*\s?(?:배정|지정))'
                        r'(?:가|이|는)?\s?(?:완료\s?)?(?:되었|됐|했)', re.IGNORECASE)


@dataclass(frozen=True)
class Limits:
    """추가 질문 상한 (09 4.2 팀 결정 시작값). 환경변수로 바꾼다."""
    unanswered: int = 2         # ASK_MORE_UNANSWERED_LIMIT
    total: int = 5              # ASK_MORE_TOTAL_LIMIT

    @classmethod
    def from_env(cls) -> 'Limits':
        return cls(int(os.environ.get('ASK_MORE_UNANSWERED_LIMIT', cls.unanswered)),
                   int(os.environ.get('ASK_MORE_TOTAL_LIMIT', cls.total)))


@dataclass(frozen=True)
class Corrected:
    output: AIOutput
    overrides: tuple[dict, ...]         # override_reasons 항목. 바뀐 게 없으면 ()


def override(field: str, ai, final, rule: str, reason: str) -> dict:
    """override_reasons 한 항목 (08 5.4). rule 은 08 3.2 rule 코드."""
    return {'field': field, 'ai': ai, 'final': final, 'rule': rule, 'reason': reason}


def unsafe_reply(reply: str) -> bool:
    """08 3.2 9단계. True 면 한 번 다시 생성하고, 또 True 면 안전 기본값을 쓴다."""
    for s in SENTENCE.findall(reply):
        if not DONT.search(s) and (ASK_SECRET.search(s) or CLAIM_DONE.search(s)):
            return True
    return False


def correct(out: AIOutput, inp: AIInput, *, second: bool, sent: Filtered | None, search: SearchResponse | None,
            taxonomy: Taxonomy, limits: Limits = Limits()) -> Corrected:
    """second: 검색 뒤 2차 판단인가 (1차에는 근거 보정을 하지 않는다, 08 3.2).
    sent: Claude 에 보낸 근거 (JudgeResult.evidence). 8단계는 보낸 것 기준으로 본다. 검색 전이면 None.
    """
    d = out.model_dump(mode='json')
    f = d['facts']
    o: list[dict] = []

    # 4. 허용값 (08 3.1)
    if d['action'] not in ACTIONS:
        o.append(override('action', d['action'], 'ESCALATE', 'INVALID_VALUE', '허용값 밖의 처리 방향'))
        d['action'] = 'ESCALATE'
    for target, key, values in ((d, 'category_code', CATEGORY_CODES), (d, 'request_kind', REQUEST_KINDS),
                                (d, 'urgency_suggested', URGENCIES), (d, 'escalation_reason', ESCALATION_REASONS),
                                (f, 'impact_scope', IMPACT_SCOPES)):
        if target[key] is not None and target[key] not in values:
            name = f'facts.{key}' if target is f else key
            o.append(override(name, target[key], None, 'INVALID_VALUE', '허용값 밖의 값'))
            target[key] = None
    if f['work_stopped'] not in WORK_STOPPED:          # null 을 받지 않는 칸이라 '모름'으로 둔다
        o.append(override('facts.work_stopped', f['work_stopped'], 'unknown', 'INVALID_VALUE', '허용값 밖의 값'))
        f['work_stopped'] = 'unknown'
    for key, ok in (('missing_items', lambda m: m in MISSING_ITEMS), ('evidence', lambda e: e['kind'] in EVIDENCE_KINDS)):
        kept = [v for v in d[key] if ok(v)]
        if len(kept) != len(d[key]):
            o.append(override(key, d[key], kept, 'INVALID_VALUE', '허용값 밖의 항목을 뺌'))
            d[key] = kept

    # 5. 세부 유형이 분류 체계에 있고 Category 와 맞는가. Category 는 그대로 둔다
    code = d['inquiry_type_code']
    if code is not None:
        t = next((t for t in taxonomy.types if t.code == code), None)
        if t is None or t.category_code != d['category_code']:
            why = '분류 체계에 없는 세부 유형' if t is None else 'Category 와 맞지 않는 세부 유형'
            o.append(override('inquiry_type_code', code, None, 'TYPE_CODE_MISMATCH', why))
            d['inquiry_type_code'] = None

    # 6. 이미 답한 항목과 초안 단계 항목은 묻지 않는다
    known = _known_items(inp.collected_facts)
    d['missing_items'] = list(dict.fromkeys(m for m in d['missing_items'] if m not in ASKED_LATER and m not in known))

    # 7. 처리 방향별 필수 값 (08 2.5). ESCALATE 사유는 아래 처리 방향 보정에서 채운다
    title = d['title'] if d['title'].strip() else (f['summary'].strip() or 'IT 문의')
    if title != d['title'] or len(title) > TITLE_MAX:
        o.append(override('title', d['title'], title[:TITLE_MAX], 'INVALID_VALUE', '제목이 비었거나 255자를 넘음'))
        d['title'] = title[:TITLE_MAX]

    # 8. 근거가 Claude 에 보낸 검색 결과에 그대로 있는가
    texts = _sent_texts(sent)
    d['evidence'] = [e for e in d['evidence'] if e['quote'] and e['quote'] in texts.get((e['kind'], e['source_id']), '')]

    # 처리 방향 보정 (08 3.2 표 순서)
    def escalate(reason: str, rule: str, why: str):
        o.append(override('action', d['action'], 'ESCALATE', rule, why))
        d['action'], d['escalation_reason'] = 'ESCALATE', reason

    if second and d['action'] == 'ANSWER':
        if not d['evidence']:
            escalate('근거부족', 'NO_EVIDENCE', '남은 근거가 없음')
        elif search is not None and not search.sufficient and not any(e['kind'] == 'LEGACY' for e in d['evidence']):
            escalate('근거부족', 'GUIDE_INSUFFICIENT', '가이드 근거가 부족하고 과거 사례 근거도 없음')
    if d['action'] == 'ASK_MORE':
        if not d['missing_items']:
            escalate('전문판단', 'ASK_MORE_EMPTY', '물을 항목이 없음')
        elif inp.ask_more_unanswered_count >= limits.unanswered:
            escalate('전문판단', 'ASK_MORE_UNANSWERED', f'답을 못 얻은 추가 질문 {inp.ask_more_unanswered_count}번')
        elif inp.ask_more_count >= limits.total:
            escalate('전문판단', 'ASK_MORE_LIMIT', f'추가 질문 {inp.ask_more_count}번')
    if d['action'] == 'ESCALATE' and d['escalation_reason'] is None:
        o.append(override('escalation_reason', None, '전문판단', 'INVALID_VALUE', '담당자 연결 사유가 비어 있음'))
        d['escalation_reason'] = '전문판단'
    if inp.prior_urgent_signal and not d['urgent_signal']:
        o.append(override('urgent_signal', False, True, 'URGENT_LATCH', '이 문의에서 이미 긴급 징후가 있었음'))
        d['urgent_signal'] = True
    if d['urgent_signal'] and d['action'] != 'ESCALATE':
        escalate('긴급대응', 'URGENT_SIGNAL', '긴급 징후는 담당자 연결')
    if d['action'] != 'ESCALATE' and d['escalation_reason'] is not None:    # 08 2.5: ESCALATE 가 아니면 null
        o.append(override('escalation_reason', d['escalation_reason'], None, 'INVALID_VALUE', '담당자 연결이 아님'))
        d['escalation_reason'] = None

    return Corrected(AIOutput.model_validate(d), tuple(o))


def _known_items(facts: Facts | None) -> set[str]:
    """collected_facts 에 이미 값이 있는 추가 질문 항목. impact 는 영향 범위와 업무 중단 정도를 둘 다 알 때."""
    if facts is None:
        return set()
    known = {k for k in ('target_system', 'symptom') if getattr(facts, k)}
    if facts.impact_scope is not None and facts.work_stopped != 'unknown':
        known.add('impact')
    return known


def _sent_texts(sent: Filtered | None) -> dict[tuple[str, str], str]:
    if sent is None:
        return {}
    return {**{('DOCUMENT', r.unit_key): r.text for r in sent.documents},
            **{('LEGACY', r.legacy_no): r.text for r in sent.legacy}}
