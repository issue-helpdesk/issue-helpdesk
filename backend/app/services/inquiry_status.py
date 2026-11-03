from sqlalchemy import and_, case

from app.models import Inquiry, Ticket

CLOSED_STATUSES = ("AI_RESOLVED", "CLOSED_UNRESOLVED")
TICKET_DISPLAY = {"RDY": "assigned", "WIP": "progress", "FIN": "awaiting_confirm", "CLS": "resolved"}
STATUS_DISPLAY = {"AI_RESOLVED": "ai_resolved", "CLOSED_UNRESOLVED": "unresolved", "RECEIVED": "received"}


def display_status(inquiry: Inquiry, ticket: Ticket | None) -> str:
    if ticket is not None:
        return ticket_display_status(ticket)
    if inquiry.status == "IN_PROGRESS" and inquiry.action == "ANSWER" and inquiry.resolution_result is None:
        return "unconfirmed"
    return STATUS_DISPLAY.get(inquiry.status, "in_progress")


def ticket_display_status(ticket: Ticket) -> str:
    """접수가 있으면 업무 상태로 정한다. Jira 생성 전(null)은 접수됨.

    RDY 라도 담당자가 아직 정해지지 않았으면(assign_status 가 ASSIGNED 가 아니면) 접수됨이다 (R-34).
    RDY 는 Jira 에 티켓이 만들어졌다는 뜻이지 담당자 배정이 끝났다는 뜻이 아니다.
    """
    if ticket.work_status == "RDY" and ticket.assign_status != "ASSIGNED":
        return "received"
    return TICKET_DISPLAY.get(ticket.work_status, "received")


def display_status_column():
    """ticket_display_status 와 같은 기준의 SQL 식. 목록 필터와 목록의 표시 값이 상세와 어긋나지 않게 한다."""
    return case(
        (Ticket.id.is_not(None), case(
            (and_(Ticket.work_status == "RDY", Ticket.assign_status != "ASSIGNED"), "received"),
            *[(Ticket.work_status == work, shown) for work, shown in TICKET_DISPLAY.items()],
            else_="received",
        )),
        (and_(Inquiry.status == "IN_PROGRESS", Inquiry.action == "ANSWER", Inquiry.resolution_result.is_(None)),
         "unconfirmed"),
        *[(Inquiry.status == status, shown) for status, shown in STATUS_DISPLAY.items()],
        else_="in_progress",
    )


def next_actions(inquiry: Inquiry) -> list[str]:
    if inquiry.status in CLOSED_STATUSES:
        return ["START_NEW"]
    if inquiry.status != "IN_PROGRESS":
        return []
    if inquiry.resolution_result == "UNRESOLVED" or inquiry.action in ("ESCALATE", "OUT_OF_SCOPE"):
        return ["DECIDE_HANDOFF"]
    if inquiry.action == "ANSWER":
        return ["CONFIRM_RESOLUTION"]
    return ["REPLY"]


def resume_actions(inquiry: Inquiry, ticket: Ticket | None) -> list[str]:
    """IQ-06 이어가기 대상이면 다음 행동, 아니면 빈 목록.

    AI 미확인(CONFIRM_RESOLUTION)·AI 미해결(DECIDE_HANDOFF)·Ticket 해결 확인 대기(FIN)만 이어간다.
    """
    if ticket is not None:
        return ["CONFIRM_TICKET_RESOLUTION"] if ticket.work_status == "FIN" else []
    actions = next_actions(inquiry)
    return actions if actions in (["CONFIRM_RESOLUTION"], ["DECIDE_HANDOFF"]) else []
