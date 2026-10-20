"""검색 요청·결과 형식 (WBS M3-1-1, C → D).

문서 결과의 모양은 청크_메타데이터.md 8장을 그대로 따르고, 아래 넷을 더한다. 설명은 search/README.md.
- 근거 문장 `evidence`  : 단위 본문에서 질문과 맞는 문장 (최대 3개)
- 근거 충분 여부 `sufficient` : 가이드 최고 점수가 기준값 이상인지. 부족하면 과거 사례를 쓸지 D가 판단한다
- 요청 형식 `SearchRequest` : 사용자 역할은 서버가 확인한 값만 받는다
- 과거 사례 결과 `LegacyResult` : 과거 이력(legacy_inquiries) 검색 결과. 개인 정보 칸은 없다
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

SERVICE_ROLES = ('EMPLOYEE', 'AGENT', 'ADMIN')
SOURCES = ('DOCUMENT', 'LEGACY')
VIEW_SCOPES = ('ALL', 'AGENT', 'ADMIN')
TRANSFER_POLICIES = ('ALLOWED', 'MASKED', 'BLOCKED')
CHUNK_TYPES = ('ITEM', 'CHAPTER', 'FAQ', 'PREFACE')

# 역할마다 볼 수 있는 view_scope (청크_메타데이터.md 4장). 문서와 과거 사례에 똑같이 쓴다
VISIBLE_SCOPES = {
    'EMPLOYEE': ('ALL',),
    'AGENT': ('ALL', 'AGENT'),
    'ADMIN': ('ALL', 'AGENT', 'ADMIN'),
}

MAX_EVIDENCE = 3            # 근거 문장 최대 개수
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
DEFAULT_THRESHOLD = 0.5     # 임시 기준값. M3-2-1에서 Golden Set으로 다시 정한다


def visible_scopes(service_role: str) -> tuple[str, ...]:
    """역할이 볼 수 있는 view_scope. 모르는 역할은 아무것도 볼 수 없다."""
    return VISIBLE_SCOPES.get(service_role, ())


def _check(value, allowed, name):
    if value not in allowed:
        raise ValueError(f'{name}={value!r} (허용: {", ".join(allowed)})')


@dataclass(frozen=True)
class SearchRequest:
    """검색 요청. service_role·user_id는 화면에서 받은 값이 아니라 백엔드가 로그인 정보로 채운다."""
    query: str
    service_role: str                                  # EMPLOYEE / AGENT / ADMIN (users.service_role)
    user_id: int | None = None                         # 본인 사례만 보기 같은 규칙이 생길 때 쓴다
    sources: tuple[str, ...] = SOURCES                 # 찾을 대상: DOCUMENT(가이드·매뉴얼·공통 기준) / LEGACY(과거 사례)
    category_code: str | None = None                   # 분류를 먼저 정했으면 좁힌다. 공통 기준(분류 없음)은 항상 포함
    top_k: int = DEFAULT_TOP_K                         # 대상마다 돌려줄 결과 수

    def __post_init__(self):
        if not self.query.strip():
            raise ValueError('query 가 비어 있습니다')
        _check(self.service_role, SERVICE_ROLES, 'service_role')
        for s in self.sources:
            _check(s, SOURCES, 'sources')
        if not 1 <= self.top_k <= MAX_TOP_K:
            raise ValueError(f'top_k={self.top_k} (1~{MAX_TOP_K})')


@dataclass(frozen=True)
class ChunkHit:
    """단위를 이루는 조각 하나. score 는 실제로 검색에 맞은 조각만 있고, 붙이기만 한 조각은 None."""
    id: int                                            # document_chunks.id
    part: int
    score: float | None = None


@dataclass(frozen=True)
class DocumentResult:
    """문서 검색 결과 하나 = 단위 하나 (청크_메타데이터.md 8장)."""
    unit_key: str                                      # IT-SW-003@v2.0/item:3.1
    chunk_type: str                                    # ITEM / CHAPTER / FAQ / PREFACE
    doc_code: str
    title: str
    version: str
    location: str                                      # 3.1 · 3.1 · p.4-6 · 4 · FAQ-035
    heading_path: str
    text: str                                          # 머리말 + 조각을 part 순서로 붙인 본문. 답변 근거로 쓴다
    chunks: tuple[ChunkHit, ...]
    unit_score: float                                  # 맞은 조각 점수 중 가장 높은 값
    score_type: str                                    # cosine:<임베딩 model 값>
    view_scope: str
    transfer_policy: str
    evidence: tuple[str, ...] = ()                     # [추가] 질문과 맞는 문장. text 안에 그대로 있는 문장만
    inquiry_type_codes: tuple[str, ...] = ()
    handling: str = ''
    also_in: tuple[str, ...] = ()                      # 같은 본문이 있는 다른 단위의 unit_key
    source_kind: str = field(default='DOCUMENT', init=False)

    def __post_init__(self):
        _check(self.chunk_type, CHUNK_TYPES, 'chunk_type')
        _check(self.view_scope, VIEW_SCOPES, 'view_scope')
        _check(self.transfer_policy, TRANSFER_POLICIES, 'transfer_policy')
        _check_evidence(self.evidence, self.text)
        if not any(c.score is not None for c in self.chunks):
            raise ValueError(f'{self.unit_key}: 검색에 맞은 조각(score 가 있는 조각)이 없습니다')

    @property
    def citation(self) -> str:
        """화면 출처 표시. doc_code + location (청크_메타데이터.md 8장, 예: IT-SW-003 3.1)."""
        return f'{self.doc_code} {self.location}'.strip()


@dataclass(frozen=True)
class LegacyResult:
    """[추가] 과거 사례 검색 결과 하나 (legacy_inquiries). 요청자·담당자처럼 사람을 가리키는 칸은 넣지 않는다."""
    legacy_inquiry_id: int                             # legacy_inquiries.id
    legacy_no: str                                     # INQ-2026-00245
    inquiry_type_code: str | None
    title: str
    text: str                                          # 임베딩에 쓴 글 (legacy_inquiry_embeddings.source_text: 증상·원인·해결)
    root_cause: str
    resolution: str
    resolved_at: str | None                            # 'YYYY-MM-DD HH:MM'. 처리 중이면 None
    score: float
    score_type: str
    view_scope: str
    transfer_policy: str
    evidence: tuple[str, ...] = ()
    source_kind: str = field(default='LEGACY', init=False)

    def __post_init__(self):
        _check(self.view_scope, VIEW_SCOPES, 'view_scope')
        _check(self.transfer_policy, TRANSFER_POLICIES, 'transfer_policy')
        _check_evidence(self.evidence, self.text)

    @property
    def citation(self) -> str:
        when = f' ({self.resolved_at[:7]})' if self.resolved_at else ''
        return f'과거 사례 {self.legacy_no}{when}'


def _check_evidence(evidence, text):
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f'근거 문장은 {MAX_EVIDENCE}개까지입니다 ({len(evidence)}개)')
    for s in evidence:
        if s not in text:                              # 지어낸 문장이 근거로 나가지 않게
            raise ValueError(f'근거 문장이 본문에 없습니다: {s[:30]}…')


@dataclass(frozen=True)
class SearchResponse:
    """검색 응답. documents·legacy 는 각각 점수 높은 순."""
    query: str
    model: str                                         # 임베딩 model 값 (이름@리비전/전처리)
    threshold: float                                   # 이번 판단에 쓴 기준값
    documents: tuple[DocumentResult, ...] = ()
    legacy: tuple[LegacyResult, ...] = ()
    took_ms: int = 0

    @property
    def best_score(self) -> float | None:
        """문서 결과 중 가장 높은 점수. 과거 사례 점수는 넣지 않는다 (sufficient 참고)."""
        return max((d.unit_score for d in self.documents), default=None)

    @property
    def sufficient(self) -> bool:
        """[추가] 가이드만으로 근거가 충분한지 (가이드 문서 점수만 본다).

        False 면 가이드만으로는 부족하다는 뜻이다. 과거 사례(legacy)를 쓸지는 D가 판단한다 (PRD 4.2 검색 순서):
        현재 가이드·운영 정책과 충돌하지 않으면 "과거 처리 사례 참고"로 답하고, 그래도 없으면 추가 확인·담당자 연결.
        외부 전송 정책으로 근거가 빠지는 경우도 D가 따로 본다.
        """
        best = self.best_score
        return best is not None and best >= self.threshold

    def to_dict(self) -> dict:
        """API·로그용. citation·sufficient·best_score 같은 계산 값도 함께 넣는다."""
        def one(r):
            d = asdict(r)
            d['citation'] = r.citation
            return d
        return {
            'query': self.query, 'model': self.model, 'threshold': self.threshold, 'took_ms': self.took_ms,
            'best_score': self.best_score, 'sufficient': self.sufficient,
            'documents': [one(r) for r in self.documents], 'legacy': [one(r) for r in self.legacy],
        }


def message_source_rows(used: list[DocumentResult | LegacyResult]) -> list[dict]:
    """답변에 실제로 쓴 근거 → message_sources 행 (청크_메타데이터.md 6장 스냅샷 규칙).

    used 는 D가 답변에 쓴 결과만, 쓴 순서대로 넘긴다. 문서는 단위를 이루는 조각을 모두 넣고,
    당시 doc_code·version·location 과 실제로 쓴 본문(excerpt)을 같이 남긴다. message_id 는 저장할 때 채운다.
    """
    rows = []
    for rank, r in enumerate(used, start=1):
        if isinstance(r, DocumentResult):
            for c in r.chunks:
                rows.append({'source_kind': 'DOCUMENT', 'chunk_id': c.id, 'legacy_inquiry_id': None,
                             'doc_code': r.doc_code, 'version': r.version, 'location': r.location,
                             'excerpt': r.text, 'rank': rank})
        else:
            rows.append({'source_kind': 'LEGACY', 'chunk_id': None, 'legacy_inquiry_id': r.legacy_inquiry_id,
                         'doc_code': None, 'version': None, 'location': r.legacy_no,
                         'excerpt': r.text, 'rank': rank})
    return rows
