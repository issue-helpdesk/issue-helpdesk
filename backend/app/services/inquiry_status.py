from sqlalchemy import and_, case

from app.models import Inquiry, Ticket

CLOSED_STATUSES = ("AI_RESOLVED", "CLOSED_UNRESOLVED")
TICKET_DISPLAY = {"RDY": "assigned", "WIP": "progress", "FIN": "awaiting_confirm", "CLS": "resolved"}
STATUS_DISPLAY = {"AI_RESOLVED": "ai_resolved", "CLOSED_UNRESOLVED": "unresolved", "RECEIVED": "received"}


def display_status(inquiry: Inquiry, ticket: Ticket | None) -> str:
    if ticket is not None:
        return TICKET_DISPLAY.get(ticket.work_status, "received")
    if inquiry.status == "IN_PROGRESS" and inquiry.action == "ANSWER" and inquiry.resolution_result is None:
        return "unconfirmed"
    return STATUS_DISPLAY.get(inquiry.status, "in_progress")


def display_status_column():
    return case(
        (Ticket.id.is_not(None), case(
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
