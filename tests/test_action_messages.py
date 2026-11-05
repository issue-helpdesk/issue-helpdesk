"""R-29: 누른 버튼과 카드가 대화에 남는지, AI 이력에는 섞이지 않는지, 기존 문의 보정이 맞는지."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ChatSession, Inquiry, Message, Ticket, TicketDraft
from app.repositories.inquiry import InquiryRepository
from app.services.ai_responder import build_ai_input
from test_auth import client  # noqa: F401 (픽스처)
from test_inquiries import INQUIRIES, ai, headers, message_list, owner, resolve, start, taxonomy  # noqa: F401
from test_tickets import (  # noqa: F401
    answered,
    as_user,
    confirm,
    create_draft,
    db,
    draft,
    make_ticket,
    patch_draft,
    set_work_status,
    staff,
    transition,
)


def action_rows(client, headers, inquiry_id):
    return [(m["sender"], m["kind"], m["code"]) for m in message_list(client, headers, inquiry_id) if m["kind"] != "TEXT"]


def test_create_draft_saves_choice_and_card(client, headers, answered, draft):
    rows = message_list(client, headers, answered)

    assert [(m["sender"], m["kind"], m["code"], m["content"]) for m in rows[-2:]] == [
        ("USER", "CHOICE", "CONNECT", None), ("SYSTEM", "DRAFT_CARD", None, None),
    ]
    assert rows[-1]["draft"]["id"] == draft["id"]
    assert rows[-2]["draft"] is None


def test_draft_card_shows_latest_edit_and_survives_confirm(client, db, headers, answered, draft):
    edited = patch_draft(client, headers, draft["id"], {"summary": "수정한 요약"}).json()["draft"]

    assert message_list(client, headers, answered)[-1]["draft"]["summary"] == "수정한 요약"

    confirm(client, headers, draft["id"], edited["updatedAt"])
    rows = message_list(client, headers, answered)
    assert (rows[-3]["draft"]["summary"], rows[-3]["draft"]["status"]) == ("수정한 요약", "CONFIRMED")
    assert [(m["kind"], m["code"], m["content"]) for m in rows[-2:]] == [("CHOICE", "CONFIRM", None), ("TICKET_CARD", None, None)]


def test_confirm_again_adds_no_message(client, db, headers, draft):
    confirm(client, headers, draft["id"])
    before = len(db.scalars(select(Message)).all())

    assert confirm(client, headers, draft["id"]).status_code == 200

    assert len(db.scalars(select(Message)).all()) == before


def test_cancel_draft_saves_cancel_choice(client, headers, answered, draft):
    patch_draft(client, headers, draft["id"], {"status": "CANCELLED"})

    assert action_rows(client, headers, answered)[-1] == ("USER", "CHOICE", "CANCEL")
    assert message_list(client, headers, answered)[-2]["draft"]["status"] == "CANCELLED"


def test_close_inquiry_saves_no_connect_choice(client, headers, answered):
    res = client.patch(f"{INQUIRIES}/{answered}", json={"status": "CLOSED_UNRESOLVED"}, headers=headers)

    assert res.status_code == 200
    assert action_rows(client, headers, answered) == [("USER", "CHOICE", "NO_CONNECT")]


def test_unresolved_then_full_flow_keeps_order(client, headers, answered):
    resolve(client, headers, answered, "UNRESOLVED")
    made = create_draft(client, headers, answered).json()
    confirm(client, headers, made["id"])

    assert [(k, c) for _, k, c in action_rows(client, headers, answered)] == [
        ("CHOICE", "UNRESOLVED"), ("CHOICE", "CONNECT"), ("DRAFT_CARD", None), ("CHOICE", "CONFIRM"), ("TICKET_CARD", None),
    ]
    assert [m["seq"] for m in message_list(client, headers, answered)] == list(range(1, 8))


def test_ai_history_only_has_text(db, client, headers, answered):
    resolve(client, headers, answered, "UNRESOLVED", comment="여전히 안 돼요")
    session_id = db.scalar(select(ChatSession.id))

    history = InquiryRepository(db).conversation(session_id)

    assert [m.sender for m in history] == ["USER", "AI", "USER"]
    assert history[-1].content == "여전히 안 돼요"


def test_masked_input_reaches_ai_as_user_text(db, client, ai, owner, headers):
    """가림 안내가 마지막 메시지여도 AI 는 사용자 글을 이번 질문으로 받는다."""
    inquiry_id = start(client, headers, content="비밀번호는 Abc123!@ 인데 VPN이 안 돼요").json()["inquiry"]["id"]
    session_id = db.scalar(select(ChatSession.id).where(ChatSession.inquiry_id == inquiry_id))
    history = InquiryRepository(db).conversation(session_id)[:1]     # AI 답변이 저장되기 전의 이력과 같다

    inp = build_ai_input(db.get(Inquiry, inquiry_id), owner, None, history, [])

    assert inp.message.endswith("VPN이 안 돼요") and "Abc123!@" not in inp.message
    assert all(m.kind == "NOTICE" for m in db.scalars(select(Message).where(Message.sender == "SYSTEM")))


@pytest.mark.parametrize("body, expected", [
    ({"workStatus": "CLS"}, [("USER", "CHOICE", "TICKET_RESOLVED")]),
    ({"workStatus": "WIP", "reason": "비밀번호는 Abc123!@ 인데 또 안 돼요"},
     [("USER", "CHOICE", "TICKET_UNRESOLVED"), ("USER", "TEXT", None), ("SYSTEM", "TICKET_CARD", None)]),
])
def test_requester_resolution_saved(client, db, headers, staff, body, expected):
    ticket = staff["mine"]
    set_work_status(db, ticket, "FIN", finished_at=datetime(2026, 11, 5, tzinfo=timezone.utc))

    assert transition(client, headers, ticket.id, **body).status_code == 202

    rows = db.scalars(select(Message).where(Message.session_id == ticket.session_id).order_by(Message.seq)).all()
    assert [(m.sender, m.kind, m.code) for m in rows] == expected
    assert all("Abc123!@" not in (m.content or "") for m in rows)


def test_staff_transition_saves_no_message(client, db, staff):
    ticket = staff["mine"]

    res = transition(client, as_user(client, "E0002"), ticket.id, workStatus="FIN", resolutionNote="재발급했습니다.")

    assert res.status_code == 202
    assert db.scalars(select(Message).where(Message.session_id == ticket.session_id)).all() == []


@pytest.mark.parametrize("fields", [
    {"sender": "SYSTEM", "kind": "DRAFT_CARD"},                            # 초안 없는 초안 카드
    {"sender": "USER", "kind": "CHOICE"},                                  # code 없는 선택
    {"sender": "USER", "kind": "CHOICE", "code": "모르는 값"},
    {"sender": "USER", "kind": "TEXT"},                                    # 글 없는 사용자 글
    {"sender": "USER", "kind": "CHOICE", "code": "CONNECT", "content": "담당자 연결"},   # 선택에 문구 저장
])
def test_message_constraints(db, answered, fields):
    db.add(Message(session_id=db.scalar(select(ChatSession.id)), seq=99, **fields))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------------------------------------------------------------- 기존 문의 보정

@pytest.fixture
def backfill():
    path = Path(__file__).resolve().parent.parent / "db" / "backfill_action_messages.py"
    spec = importlib.util.spec_from_file_location("backfill_action_messages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def old_inquiry(db, owner, **fields):
    """R-29 이전에 만들어진 문의: 사용자 글과 AI 답변만 있다."""
    inquiry = Inquiry(user_id=owner.id, status=fields.pop("status", "IN_PROGRESS"), **fields)
    db.add(inquiry)
    db.flush()
    session = ChatSession(inquiry_id=inquiry.id)
    db.add(session)
    db.flush()
    db.add_all([Message(session_id=session.id, seq=1, sender="USER", content="VPN 안 돼요"),
                Message(session_id=session.id, seq=2, sender="AI", content="재설치해 보세요")])
    db.commit()
    return inquiry, session


def old_draft(db, inquiry, session, status):
    made = TicketDraft(inquiry_id=inquiry.id, session_id=session.id, summary="요약", status=status,
                       created_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    db.add(made)
    db.commit()
    return made


def added(db, session):
    return [(m.seq, m.kind, m.code) for m in
            db.scalars(select(Message).where(Message.session_id == session.id, Message.seq > 2).order_by(Message.seq))]


def test_backfill_received_ticket(db, owner, backfill):
    inquiry, session = old_inquiry(db, owner, status="RECEIVED", resolution_result="UNRESOLVED")
    made = old_draft(db, inquiry, session, "CONFIRMED")
    db.add(Ticket(receipt_no="RCPT-0011", draft_id=made.id, inquiry_id=inquiry.id, session_id=session.id, summary="요약",
                  jira_sync_status="SYNCED", assign_status="ASSIGNED", created_at=datetime(2026, 11, 2, tzinfo=timezone.utc)))
    db.commit()

    report = backfill.backfill(db)
    db.commit()

    assert added(db, session) == [(3, "CHOICE", "UNRESOLVED"), (4, "CHOICE", "CONNECT"), (5, "DRAFT_CARD", None),
                                  (6, "CHOICE", "CONFIRM"), (7, "TICKET_CARD", None)]
    card = db.scalar(select(Message).where(Message.kind == "DRAFT_CARD"))
    assert (card.draft_id, card.created_at.replace(tzinfo=None)) == (made.id, datetime(2026, 11, 1))
    assert (report.inquiries, report.messages) == (1, 5)


def test_backfill_ai_resolved_converts_old_notice(db, owner, backfill):
    _, session = old_inquiry(db, owner, status="AI_RESOLVED", resolution_result="RESOLVED")
    db.add(Message(session_id=session.id, seq=3, sender="SYSTEM", kind="NOTICE", content="해결로 종료되었습니다."))
    db.commit()

    backfill.backfill(db)
    db.commit()

    row = db.scalar(select(Message).where(Message.seq == 3))
    assert (row.sender, row.kind, row.code, row.content) == ("USER", "CHOICE", "RESOLVED", None)
    assert added(db, session) == [(3, "CHOICE", "RESOLVED")]


def test_backfill_distinguishes_cancel_and_no_connect(db, owner, backfill):
    cancelled, cancelled_session = old_inquiry(db, owner, status="CLOSED_UNRESOLVED")
    old_draft(db, cancelled, cancelled_session, "CANCELLED")
    _, rejected_session = old_inquiry(db, owner, status="CLOSED_UNRESOLVED")

    backfill.backfill(db)
    db.commit()

    assert [c for _, k, c in added(db, cancelled_session) if k == "CHOICE"] == ["CONNECT", "CANCEL"]
    assert added(db, rejected_session) == [(3, "CHOICE", "NO_CONNECT")]


def test_backfill_editing_draft_gets_card(db, owner, backfill):
    inquiry, session = old_inquiry(db, owner)
    old_draft(db, inquiry, session, "EDITING")

    backfill.backfill(db)
    db.commit()

    assert [k for _, k, _ in added(db, session)] == ["CHOICE", "DRAFT_CARD"]


def test_backfill_twice_changes_nothing(db, owner, backfill):
    _, session = old_inquiry(db, owner, status="CLOSED_UNRESOLVED")
    backfill.backfill(db)
    db.commit()
    before = added(db, session)

    assert backfill.backfill(db).messages == 0

    db.commit()
    assert added(db, session) == before


def test_backfill_dry_run_saves_nothing(db, owner, backfill):
    _, session = old_inquiry(db, owner, status="AI_RESOLVED", resolution_result="RESOLVED")
    db.add(Message(session_id=session.id, seq=3, sender="SYSTEM", kind="NOTICE", content="해결로 종료되었습니다."))
    db.commit()

    report = backfill.backfill(db, dry_run=True)
    db.rollback()

    assert (report.inquiries, report.messages) == (1, 1)
    assert added(db, session) == [(3, "NOTICE", None)]
