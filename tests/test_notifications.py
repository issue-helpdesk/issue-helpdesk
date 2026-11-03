"""화면 알림 (NT-01~04). SQLite 메모리 DB 만 사용한다."""
import pytest
from sqlalchemy import select

from app.models import Notification
from app.services.jira_webhook import sync_assignee, sync_work_status
from app.utils import datetime_utils
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import admin, as_user, db, make_ticket, staff, team  # noqa: F401

URL = "/api/v1/notifications"
FREE_ACCOUNT = "acc-E0006"


def notify(db, ticket, recipient, kind="FIN"):
    row = Notification(ticket_id=ticket.id, recipient_id=recipient.id, kind=kind)
    db.add(row)
    db.commit()
    return row


def test_list_only_mine_newest_first(client, db, owner, headers, team):
    first = notify(db, team["mine"], owner)
    second = notify(db, team["secret"], owner)
    notify(db, team["others"], team["agent"])

    res = client.get(URL, headers=headers)

    assert res.status_code == 200
    assert [n["id"] for n in res.json()["items"]] == [second.id, first.id]
    assert res.json()["totalCount"] == 2
    item = res.json()["items"][1]
    assert set(item) == {"id", "kind", "ticketId", "inquiryId", "receiptNo", "summary", "readAt", "createdAt"}
    assert (item["ticketId"], item["inquiryId"]) == (team["mine"].id, team["mine"].inquiry_id)
    assert item["readAt"] is None


def test_unread_only_filter(client, db, owner, headers, team):
    read = notify(db, team["mine"], owner)
    read.read_at = datetime_utils.now()
    unread = notify(db, team["secret"], owner)
    db.commit()

    res = client.get(URL, params={"unreadOnly": "true"}, headers=headers)

    assert [n["id"] for n in res.json()["items"]] == [unread.id]


def test_unread_count_with_tickets(client, db, owner, headers, team):
    notify(db, team["mine"], owner)
    notify(db, team["mine"], owner)
    notify(db, team["secret"], owner)

    body = client.get(f"{URL}/unread-count", headers=headers).json()

    assert body["count"] == 3
    assert body["ticketIds"] == sorted([team["mine"].id, team["secret"].id])


def test_reassigned_notification_is_hidden(client, db, team):
    """재배정되면 이전 담당자의 배정 알림은 보이지 않고 개수에도 안 들어간다."""
    ticket = team["mine"]
    ticket.assignee_id = team["busy"].id
    row = notify(db, ticket, team["busy"], "ASSIGNED")
    headers = as_user(client, "E0005")
    assert client.get(f"{URL}/unread-count", headers=headers).json()["count"] == 1

    ticket.assignee_id = team["free"].id
    db.commit()

    assert client.get(f"{URL}/unread-count", headers=headers).json()["count"] == 0
    assert client.get(URL, headers=headers).json()["items"] == []
    assert error_code(client.put(f"{URL}/{row.id}/read", headers=headers)) == "NOTIFICATION_NOT_FOUND"


def test_mark_read_keeps_first_time(client, db, owner, headers, team):
    row = notify(db, team["mine"], owner)

    first = client.put(f"{URL}/{row.id}/read", headers=headers).json()
    second = client.put(f"{URL}/{row.id}/read", headers=headers).json()

    assert first["readAt"] is not None and second["readAt"] == first["readAt"]
    assert client.get(f"{URL}/unread-count", headers=headers).json() == {"count": 0, "ticketIds": []}


def test_cannot_read_others_notification(client, db, owner, team):
    row = notify(db, team["mine"], owner)

    res = client.put(f"{URL}/{row.id}/read", headers=as_user(client, "E0003"))

    assert (res.status_code, error_code(res)) == (404, "NOTIFICATION_NOT_FOUND")
    assert row.read_at is None


def test_mark_ticket_read(client, db, owner, headers, team):
    mine = notify(db, team["mine"], owner)
    other_ticket = notify(db, team["secret"], owner)
    other_person = notify(db, team["mine"], team["agent"])

    res = client.post(f"{URL}/read", json={"ticketId": team["mine"].id}, headers=headers)

    assert res.json() == {"updatedCount": 1}
    db.expire_all()
    assert mine.read_at is not None
    assert other_ticket.read_at is None and other_person.read_at is None
    assert client.post(f"{URL}/read", json={"ticketId": team["mine"].id}, headers=headers).json() == {"updatedCount": 0}


def test_requires_login(client):
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/unread-count").status_code == 401


def test_get_ticket_does_not_mark_read(client, db, owner, headers, team):
    row = notify(db, team["mine"], owner)

    client.get(f"/api/v1/tickets/{team['mine'].id}", headers=headers)

    db.expire_all()
    assert row.read_at is None


# ------------------------------------------------------------------ 만드는 곳: 웹훅·동기화


def rows(db, ticket):
    return [(n.recipient_id, n.kind) for n in db.scalars(select(Notification).where(Notification.ticket_id == ticket.id))]


def test_fin_from_jira_notifies_requester(db, owner, team):
    ticket = team["mine"]

    sync_work_status(db, ticket, {"work_status": "FIN", "final_result": "해결"}, None, datetime_utils.now())
    sync_work_status(db, ticket, {"work_status": "FIN", "final_result": "해결"}, None, datetime_utils.now())

    assert rows(db, ticket) == [(owner.id, "FIN")]


def test_fin_without_note_does_not_notify(db, team):
    ticket = team["mine"]

    sync_work_status(db, ticket, {"work_status": "FIN", "final_result": ""}, None, datetime_utils.now())

    assert rows(db, ticket) == []


def test_other_status_does_not_notify(db, team):
    ticket = team["mine"]
    ticket.work_status = "RDY"

    sync_work_status(db, ticket, {"work_status": "WIP", "final_result": ""}, None, datetime_utils.now())

    assert rows(db, ticket) == []


def test_assign_from_jira_notifies_new_assignee_only(db, team):
    ticket = team["mine"]
    ticket.assignee_id = team["busy"].id

    sync_assignee(db, ticket, FREE_ACCOUNT, datetime_utils.now())
    sync_assignee(db, ticket, FREE_ACCOUNT, datetime_utils.now())

    assert rows(db, ticket) == [(team["free"].id, "ASSIGNED")]


def test_invalid_assignee_does_not_notify(db, team):
    ticket = team["mine"]
    ticket.assignee_id = team["busy"].id

    sync_assignee(db, ticket, "unknown", datetime_utils.now())

    assert rows(db, ticket) == []
