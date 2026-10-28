"""검색 근거의 외부 전송 검사 (docs/10 4장 ④, docs/08 1.4 외부 전송 규칙). 외부 모델 호출 직전에 쓴다.

- filter_evidence : ALLOWED 는 그대로, MASKED 는 가림(A·B)+치환(C·D), BLOCKED·모르는 값은 뺀다.
  MASKED 를 가리다 실패하면 그 근거만 BLOCKED 로 보고 뺀다 (docs/10 3.3).
"""
from dataclasses import dataclass, replace

from app.agent.sensitive.mask import mask_secrets
from app.agent.sensitive.pseudonym import Pseudonymizer
from app.rag.search.result import DocumentResult, LegacyResult


@dataclass(frozen=True)
class Filtered:
    documents: tuple[DocumentResult, ...]
    legacy: tuple[LegacyResult, ...]
    blocked: tuple[str, ...] = ()      # 뺀 근거 번호 (doc_code·legacy_no) → audit_logs BLOCK · DOC_BLOCKED (docs/10 5.2)
    failed: tuple[str, ...] = ()       # 그 가운데 가리다 실패해 뺀 것 → FAIL · FILTER_FAILED (docs/10 5.2)

    @property
    def all_blocked(self) -> bool:
        """결과가 있었는데 모두 빠짐 → LLM 을 부르지 않고 ESCALATE, escalation_reason=전송제한 (docs/08 3.2 ALL_BLOCKED).

        처음부터 결과가 없었던 경우(근거부족)는 False 다.
        """
        return bool(self.blocked) and not self.documents and not self.legacy


def filter_evidence(documents, legacy, pseudonymizer: Pseudonymizer) -> Filtered:
    """pseudonymizer 는 이번 호출에서 이전 대화·이번 글에 쓴 것을 그대로 넘긴다 (같은 사람은 같은 번호)."""
    def clean(text: str) -> str:
        return pseudonymizer.apply(mask_secrets(text).text)

    def kept_evidence(evidence, text):
        # 근거 문장은 본문 안에 그대로 있어야 한다 (result.py). 가린 뒤 본문과 맞지 않는 문장은 뺀다
        return tuple(e for e in map(clean, evidence) if e in text)

    def masked_doc(r: DocumentResult) -> DocumentResult:
        text = clean(r.text)
        return replace(r, text=text, evidence=kept_evidence(r.evidence, text))

    def masked_legacy(r: LegacyResult) -> LegacyResult:
        text = clean(r.text)
        return replace(r, title=clean(r.title), text=text, root_cause=clean(r.root_cause),
                       resolution=clean(r.resolution), evidence=kept_evidence(r.evidence, text))

    blocked, failed = [], []

    def check(results, key, masked):
        out = []
        for r in results:
            if r.transfer_policy == 'ALLOWED':
                out.append(r)
            elif r.transfer_policy == 'MASKED':
                try:
                    out.append(masked(r))
                except Exception:
                    blocked.append(key(r))
                    failed.append(key(r))
            else:                                       # BLOCKED, 값이 없거나 그 밖의 값
                blocked.append(key(r))
        return tuple(out)

    docs = check(documents, lambda r: r.doc_code, masked_doc)
    cases = check(legacy, lambda r: r.legacy_no, masked_legacy)
    return Filtered(docs, cases, tuple(blocked), tuple(failed))
