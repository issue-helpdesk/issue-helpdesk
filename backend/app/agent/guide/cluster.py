"""해결 사례 가이드화: 묶기 (기획 4단계). AI 를 부르지 않는다. 임베딩은 서버 안에서 돈다 (외부 전송 아님).

1. 판단과 대상이 같은 티켓끼리 그룹을 나눈다 (group_key)
2. 그룹 안에서 요약+증상 임베딩의 코사인 유사도로 묶는다 (bundle). 접수 순서대로 한 건씩,
   가장 비슷한 묶음의 평균 벡터와 비교해 기준값 이상이면 넣고 아니면 새 묶음
3. 기존 묶음과 비교한다 (match_existing). 검토 중 → 근거 추가, 등록됨 → WAITING, 거절됨 → 새 묶음에 표시

기준값 0.75·최소 1건은 M4 결정 (2026-11-09). 근거는 README "묶기 설정".
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.guide.judge import TicketText
from app.models import GuideCluster, KnowledgeDocument, Ticket, TicketGuideState

THRESHOLD = 0.75                # 같은 묶음으로 볼 코사인 유사도 (bge-m3)
MIN_TICKETS = 1                 # 이보다 적으면 초안을 만들지 않고 WAITING

EmbedFn = Callable[[list[str]], list[list[float]]]      # 글들 → 벡터들 (Embedder.embed_documents)


def group_key(category_code: str, judgment: str, target_doc: str | None, target_item: str | None) -> tuple:
    """묶을 그룹. 항목 추가는 넣을 문서, 변경은 문서+항목까지 같아야 한다 (김태연 님 Q2 "한 묶음은 한 항목")."""
    if judgment == 'ADD_ITEM':
        return category_code, judgment, target_doc, None
    if judgment == 'CHANGE':
        return category_code, judgment, target_doc, target_item
    return category_code, judgment, None, None             # 새 가이드·매뉴얼 후보: 분류만


def embed_text(summary: str | None, symptom: str | None) -> str:
    """묶기에 쓰는 글: 요약 + 증상 (시험의 '제목 + 내용'에 가장 가까운 칸)."""
    return '\n'.join(v for v in (summary, symptom) if v and v.strip()) or '(내용 없음)'


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n else v


def bundle(vectors: Sequence[Sequence[float]], threshold: float = THRESHOLD) -> list[list[int]]:
    """벡터 순서(접수 순서)대로 묶는다. 결과는 입력 번호 목록들."""
    sums: list[np.ndarray] = []
    members: list[list[int]] = []
    for i, v in enumerate(vectors):
        u = _unit(v)
        scores = [float(_unit(s) @ u) for s in sums]
        best = int(np.argmax(scores)) if scores else -1
        if best >= 0 and scores[best] >= threshold:
            sums[best] = sums[best] + u
            members[best].append(i)
        else:
            sums.append(u.copy())
            members.append([i])
    return members


def centroid(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    return _unit(np.sum([_unit(v) for v in vectors], axis=0))


@dataclass(frozen=True)
class Match:
    kind: str                   # ATTACH (검토 중, 등록 전) · WAIT (검토 중, 등록 후) · REJECTED
    cluster: GuideCluster
    score: float


def _existing(session: Session, key: tuple) -> list[GuideCluster]:
    """같은 그룹의 기존 묶음 (검토 중·거절). 반영된 묶음은 현행 가이드에 들어갔으므로 판단에서 '이미 있음'이 된다."""
    category, judgment, target_doc, target_item = key
    stmt = select(GuideCluster).where(GuideCluster.category_code == category, GuideCluster.judgment == judgment,
                                      GuideCluster.status.in_(('REVIEWING', 'REJECTED')))
    if target_doc is not None:
        stmt = stmt.join(KnowledgeDocument, KnowledgeDocument.id == GuideCluster.target_document_id) \
                   .where(KnowledgeDocument.doc_code == target_doc)
    out = list(session.scalars(stmt.order_by(GuideCluster.id)))
    if judgment == 'CHANGE':
        out = [c for c in out if (c.draft_basis or {}).get('target_section') == target_item]
    return out


def _cluster_texts(session: Session, cluster_id: int) -> list[str]:
    rows = session.execute(select(Ticket.summary, Ticket.symptom)
                           .join(TicketGuideState, TicketGuideState.ticket_id == Ticket.id)
                           .where(TicketGuideState.cluster_id == cluster_id).order_by(Ticket.id)).all()
    return [embed_text(s, y) for s, y in rows]


def match_existing(session: Session, key: tuple, center: np.ndarray, embed_fn: EmbedFn,
                   threshold: float = THRESHOLD, cache: dict[int, np.ndarray] | None = None) -> Match | None:
    """새 묶음과 비슷한 기존 묶음. 검토 중(등록 전) > 검토 중(등록 후) > 거절 순으로, 같은 종류 안에서는 점수 순.
    cache: 한 회차 안에서 기존 묶음의 평균 벡터를 다시 임베딩하지 않게 (근거가 늘면 부르는 쪽이 지운다)."""
    found: dict[str, Match] = {}
    cache = {} if cache is None else cache
    for c in _existing(session, key):
        if c.id not in cache:
            texts = _cluster_texts(session, c.id)
            if not texts:                                   # 근거 티켓이 없는 묶음 (있으면 안 되지만 건너뜀)
                continue
            cache[c.id] = centroid(embed_fn(texts))
        score = float(cache[c.id] @ center)
        if score < threshold:
            continue
        kind = 'REJECTED' if c.status == 'REJECTED' else ('WAIT' if c.registered_version_id else 'ATTACH')
        if kind not in found or score > found[kind].score:
            found[kind] = Match(kind, c, score)
    for kind in ('ATTACH', 'WAIT', 'REJECTED'):
        if kind in found:
            return found[kind]
    return None


def texts_of(tickets: Sequence[TicketText]) -> list[str]:
    return [embed_text(t.summary, t.symptom) for t in tickets]
