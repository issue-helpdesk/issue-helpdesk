"""R-29 이전 문의에 누른 버튼과 카드 메시지를 채운다. 문의·접수·초안은 건드리지 않는다. 다시 돌려도 된다.

마이그레이션 c4e7a1d95f28 을 먼저 반영한다. 기본은 대상만 출력하고, --apply 를 줘야 저장한다.

    python db/backfill_action_messages.py            # 넣을 건수와 복원하지 못하는 접수만 확인
    python db/backfill_action_messages.py --apply

누른 시각이 없는 선택은 초안 생성·초안 수정·접수 생성·문의 종료 시각으로 넣는다.
옛 해결 안내("해결로 종료되었습니다.")는 그 자리에서 RESOLVED 선택으로 바꾼다. 문구는 화면이 정한다.
이미 선택·카드 메시지가 있는 문의는 건너뛴다.
복원하지 못하는 것: 완료된 접수의 이전 "미해결"(CLS 때 덮어써짐), 처리 후 재요청(FIN → WIP) 왕복.
"""
import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import func, select               # noqa: E402
from sqlalchemy.orm import Session                # noqa: E402

from app.db.session import get_engine             # noqa: E402
from app.models import ChatSession, Inquiry, Message, Ticket, TicketDraft, TicketStatusHistory  # noqa: E402

OLD_RESOLVED_NOTICE = "해결로 종료되었습니다."


@dataclass
class Report:
    inquiries: int = 0
    messages: int = 0
    no_session: list[int] = field(default_factory=list)       # 세션이 없어 메시지를 붙일 수 없는 문의
    reopened: list[int] = field(default_factory=list)         # FIN → WIP 왕복을 복원하지 못한 접수


def choice(session_id: int, code: str, at: datetime | None) -> Message:
    return Message(session_id=session_id, sender="USER", kind="CHOICE", code=code, created_at=at)


def card(session_id: int, kind: str, at: datetime | None, draft_id: int | None = None) -> Message:
    return Message(session_id=session_id, sender="SYSTEM", kind=kind, draft_id=draft_id, created_at=at)


def rows_for(inquiry: Inquiry, session_id: int, drafts: list[TicketDraft], ticket: Ticket | None) -> list[Message]:
    """seq 없이 순서대로 만든 메시지. AI 해결은 convert_resolved_notice 가 따로 처리한다."""
    closed_at = inquiry.closed_at or inquiry.updated_at
    rows: list[Message] = []
    if inquiry.resolution_result == "UNRESOLVED":
        rows.append(choice(session_id, "UNRESOLVED", drafts[0].created_at if drafts else closed_at))
    for draft in drafts:
        rows += [choice(draft.session_id, "CONNECT", draft.created_at),
                 card(draft.session_id, "DRAFT_CARD", draft.created_at, draft.id)]
        if draft.status == "CANCELLED":
            rows.append(choice(draft.session_id, "CANCEL", draft.updated_at or closed_at))
        if ticket is not None and ticket.draft_id == draft.id:
            rows += [choice(draft.session_id, "CONFIRM", ticket.created_at),
                     card(draft.session_id, "TICKET_CARD", ticket.created_at)]
    if inquiry.status == "CLOSED_UNRESOLVED" and not drafts:
        rows.append(choice(session_id, "NO_CONNECT", closed_at))
    if ticket is not None and ticket.resolution_confirmed_at is not None:
        rows.append(choice(ticket.session_id, "TICKET_RESOLVED", ticket.resolution_confirmed_at))
    return rows


def old_resolved_notice(db: Session, session_id: int) -> Message | None:
    return db.scalar(select(Message).where(Message.session_id == session_id, Message.sender == "SYSTEM",
                                           Message.content == OLD_RESOLVED_NOTICE))


def backfill(db: Session, *, dry_run: bool = False) -> Report:
    """커밋은 부르는 쪽이 한다."""
    report = Report()
    done = set(db.scalars(
        select(ChatSession.inquiry_id).join(Message, Message.session_id == ChatSession.id)
        .where(Message.kind.in_(("CHOICE", "DRAFT_CARD", "TICKET_CARD")))
    ))
    for inquiry in db.scalars(select(Inquiry).order_by(Inquiry.id)).all():
        if inquiry.id in done:
            continue
        session_id = db.scalar(select(ChatSession.id).where(ChatSession.inquiry_id == inquiry.id)
                               .order_by(ChatSession.started_at.desc(), ChatSession.id.desc()).limit(1))
        if session_id is None:
            report.no_session.append(inquiry.id)
            continue
        drafts = db.scalars(select(TicketDraft).where(TicketDraft.inquiry_id == inquiry.id)
                            .order_by(TicketDraft.created_at, TicketDraft.id)).all()
        ticket = db.scalar(select(Ticket).where(Ticket.inquiry_id == inquiry.id))
        if ticket is not None and db.scalar(select(TicketStatusHistory.id).where(
                TicketStatusHistory.ticket_id == ticket.id, TicketStatusHistory.from_status == "FIN",
                TicketStatusHistory.to_status == "WIP").limit(1)) is not None:
            report.reopened.append(ticket.id)

        rows = rows_for(inquiry, session_id, drafts, ticket)
        converted = 0
        if inquiry.status == "AI_RESOLVED":
            old = old_resolved_notice(db, session_id)
            if old is None:
                rows.append(choice(session_id, "RESOLVED", inquiry.closed_at or inquiry.updated_at))
            else:
                converted = 1
                if not dry_run:
                    old.sender, old.kind, old.code, old.content = "USER", "CHOICE", "RESOLVED", None
        if not rows and not converted:
            continue
        report.inquiries += 1
        report.messages += len(rows) + converted
        if dry_run:
            continue
        next_seq: dict[int, int] = {}
        for row in rows:
            if row.session_id not in next_seq:
                last = db.scalar(select(func.max(Message.seq)).where(Message.session_id == row.session_id))
                next_seq[row.session_id] = (last or 0) + 1
            row.seq = next_seq[row.session_id]
            next_seq[row.session_id] += 1
            db.add(row)
        db.flush()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="저장한다. 없으면 건수만 출력한다")
    args = parser.parse_args()
    with Session(get_engine()) as db:
        report = backfill(db, dry_run=not args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(f"{'저장' if args.apply else '대상'}: 문의 {report.inquiries}건, 메시지 {report.messages}건")
    print(f"세션이 없어 건너뜀: {report.no_session}")
    print(f"재요청 왕복을 복원하지 못한 접수: {report.reopened}")


if __name__ == "__main__":
    main()
