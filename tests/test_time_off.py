"""연차·반차 일정 API (TO-01~04)와 부재 계산 — SQLite 메모리 DB."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, ChatSession, Inquiry, SupportGroup, SupportGroupMember, Ticket, TicketDraft, TimeOff
from app.services.time_off import current_absentees
from app.utils import datetime_utils
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)

API = "/api/v1/time-off"
TABLES_FOR_RF04 = ["time_off", "categories", "inquiry_types", "member_skills", "inquiries", "chat_sessions",
                   "ticket_drafts", "tickets"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES + TABLES_FOR_RF04])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def people(db):
    """네트워크팀: 팀장 M0001, 담당자 A0001·A0002. 보안팀: 담당자 A0003. 그 밖에 관리자 Z0001, 직원 E0001."""
    net, sec = SupportGroup(name="네트워크팀"), SupportGroup(name="보안팀")
    db.add_all([net, sec])
    db.flush()
    users = {no: add_user(db, no, service_role="AGENT") for no in ("M0001", "A0001", "A0002", "A0003")}
    users["Z0001"] = add_user(db, "Z0001", service_role="ADMIN")
    users["E0001"] = add_user(db, "E0001")
    for no, group, role in (("M0001", net, "MANAGER"), ("A0001", net, "AGENT"), ("A0002", net, "AGENT"), ("A0003", sec, "AGENT")):
        db.add(SupportGroupMember(group_id=group.id, user_id=users[no].id, member_role=role, assignable=True))
    db.commit()
    return users | {"net": net, "sec": sec}


def add_off(db, user, kind="ANNUAL", start=date(2026, 11, 3), end=None):
    row = TimeOff(user_id=user.id, time_off_type=kind, start_date=start, end_date=end or start)
    db.add(row)
    db.commit()
    return row


def auth(client, employee_no):
    return bearer(login(client, employee_no))


def create(client, headers, **body):
    return client.post(API, headers=headers, json={"timeOffType": "ANNUAL", "startDate": "2026-11-03",
                                                   "endDate": "2026-11-03"} | body)


def ids(res):
    return [item["id"] for item in res.json()["items"]]


# ---------------------------------------------------------------- 부재 계산

@pytest.mark.parametrize("kind, hour, minute, absent", [
    ("ANNUAL", 9, 0, True),
    ("HALF_AM", 12, 59, True), ("HALF_AM", 13, 0, False),
    ("HALF_PM", 12, 59, False), ("HALF_PM", 13, 0, True),
])
def test_absence_uses_kst(db, people, kind, hour, minute, absent):
    add_off(db, people["A0001"], kind)
    now = datetime(2026, 11, 3, hour, minute, tzinfo=datetime_utils.KST).astimezone(timezone.utc)

    assert (people["A0001"].id in current_absentees(db, now)) is absent


def test_absence_date_uses_kst_not_utc(db, people):
    add_off(db, people["A0001"])

    assert people["A0001"].id in current_absentees(db, datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))      # KST 11/03 00:00
    assert people["A0001"].id not in current_absentees(db, datetime(2026, 11, 2, 14, 59, tzinfo=timezone.utc))


# ---------------------------------------------------------------- TO-01 조회

def test_agent_lists_only_own(client, db, people):
    mine = add_off(db, people["A0001"])
    add_off(db, people["A0002"])

    assert ids(client.get(API, headers=auth(client, "A0001"))) == [mine.id]


def test_manager_lists_own_group(client, db, people):
    member = add_off(db, people["A0001"])
    add_off(db, people["A0003"])                            # 다른 그룹

    assert ids(client.get(API, headers=auth(client, "M0001"))) == [member.id]


def test_admin_lists_all_with_filters(client, db, people):
    first = add_off(db, people["A0001"], start=date(2026, 11, 3), end=date(2026, 11, 5))
    second = add_off(db, people["A0003"], start=date(2026, 11, 10))
    admin = auth(client, "Z0001")

    assert ids(client.get(API, headers=admin)) == [second.id, first.id]
    assert ids(client.get(API, params={"userId": people["A0003"].id}, headers=admin)) == [second.id]
    assert ids(client.get(API, params={"groupId": people["net"].id}, headers=admin)) == [first.id]
    assert ids(client.get(API, params={"dateFrom": "2026-11-05", "dateTo": "2026-11-06"}, headers=admin)) == [first.id]
    assert ids(client.get(API, params={"groupId": people["net"].id, "userId": people["A0003"].id}, headers=admin)) == []


@pytest.mark.parametrize("who, params", [("A0001", "A0002"), ("M0001", "A0003")])
def test_list_other_user_is_forbidden(client, people, who, params):
    res = client.get(API, params={"userId": people[params].id}, headers=auth(client, who))

    assert res.status_code == 403


def test_list_other_group_is_forbidden(client, people):
    assert client.get(API, params={"groupId": people["sec"].id}, headers=auth(client, "M0001")).status_code == 403


def test_employee_cannot_use_time_off(client, people):
    assert client.get(API, headers=auth(client, "E0001")).status_code == 403


def test_list_rejects_reversed_dates(client, people):
    res = client.get(API, params={"dateFrom": "2026-11-05", "dateTo": "2026-11-01"}, headers=auth(client, "A0001"))

    assert error_code(res) == "INVALID_REQUEST"


# ---------------------------------------------------------------- TO-02 등록

def test_create_own(client, db, people):
    res = create(client, auth(client, "A0001"), note=" 가족 행사 ")

    assert res.status_code == 201
    body = res.json()
    assert (body["userId"], body["timeOffType"], body["startDate"], body["note"]) == (people["A0001"].id, "ANNUAL",
                                                                                     "2026-11-03", "가족 행사")
    assert body["createdBy"]["id"] == people["A0001"].id


@pytest.mark.parametrize("who, target, expected", [
    ("M0001", "A0001", 201),               # 팀장 → 자기 그룹 구성원
    ("M0001", "A0003", 403),               # 팀장 → 다른 그룹
    ("A0001", "A0002", 403),               # 담당자 → 동료
    ("Z0001", "A0003", 201),               # 관리자
    ("E0001", "E0001", 403),               # 일반 직원
])
def test_create_permission(client, people, who, target, expected):
    res = create(client, auth(client, who), userId=people[target].id)

    assert res.status_code == expected


def test_create_for_missing_user(client, people):
    res = create(client, auth(client, "Z0001"), userId=9999)

    assert res.json()["error"]["details"][0]["field"] == "userId"


@pytest.mark.parametrize("body", [
    {"startDate": "2026-11-05", "endDate": "2026-11-03"},
    {"timeOffType": "HALF_AM", "startDate": "2026-11-03", "endDate": "2026-11-04"},
])
def test_create_validates_dates(client, people, body):
    res = create(client, auth(client, "A0001"), **body)

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["field"] == "endDate"


@pytest.mark.parametrize("existing, new, start, end, expected", [
    ("HALF_AM", "HALF_PM", "2026-11-03", "2026-11-03", 201),   # 같은 날 오전 + 오후 반차
    ("HALF_PM", "HALF_PM", "2026-11-03", "2026-11-03", 409),   # 같은 반차 두 번
    ("HALF_AM", "ANNUAL", "2026-11-02", "2026-11-04", 409),    # 반차가 연차 기간 안에
    ("ANNUAL", "HALF_AM", "2026-11-03", "2026-11-03", 409),
    ("ANNUAL", "ANNUAL", "2026-11-03", "2026-11-05", 409),     # 기간 일부 겹침
    ("ANNUAL", "ANNUAL", "2026-11-04", "2026-11-05", 201),     # 바로 다음 날
])
def test_create_overlap(client, db, people, existing, new, start, end, expected):
    row = add_off(db, people["A0001"], existing)

    res = create(client, auth(client, "A0001"), timeOffType=new, startDate=start, endDate=end)

    assert res.status_code == expected
    if expected == 409:
        assert error_code(res) == "TIME_OFF_OVERLAP"
        assert res.json()["error"]["details"][0]["value"] == row.id


# ---------------------------------------------------------------- TO-03 수정

def test_update_only_sent_fields(client, db, people):
    row = add_off(db, people["A0001"])

    res = client.patch(f"{API}/{row.id}", headers=auth(client, "A0001"), json={"endDate": "2026-11-05", "note": "연장"})

    assert res.status_code == 200
    assert (res.json()["startDate"], res.json()["endDate"], res.json()["note"]) == ("2026-11-03", "2026-11-05", "연장")


def test_update_can_clear_note(client, db, people):
    row = add_off(db, people["A0001"])
    row.note = "메모"
    db.commit()

    assert client.patch(f"{API}/{row.id}", headers=auth(client, "A0001"), json={"note": None}).json()["note"] is None


def test_update_does_not_conflict_with_itself(client, db, people):
    row = add_off(db, people["A0001"])

    assert client.patch(f"{API}/{row.id}", headers=auth(client, "A0001"), json={"note": "그대로"}).status_code == 200


def test_update_rejects_overlap(client, db, people):
    add_off(db, people["A0001"], start=date(2026, 11, 5))
    row = add_off(db, people["A0001"])

    res = client.patch(f"{API}/{row.id}", headers=auth(client, "A0001"), json={"endDate": "2026-11-05"})

    assert error_code(res) == "TIME_OFF_OVERLAP"
    assert db.get(TimeOff, row.id).end_date == date(2026, 11, 3)


def test_update_checks_merged_dates(client, db, people):
    row = add_off(db, people["A0001"], end=date(2026, 11, 5))

    res = client.patch(f"{API}/{row.id}", headers=auth(client, "A0001"), json={"timeOffType": "HALF_AM"})

    assert res.json()["error"]["details"][0]["field"] == "endDate"


def test_update_rejects_user_change(client, db, people):
    row = add_off(db, people["A0001"])

    res = client.patch(f"{API}/{row.id}", headers=auth(client, "Z0001"), json={"userId": people["A0002"].id})

    assert res.json()["error"]["details"][0]["reason"] == "NOT_ALLOWED"


@pytest.mark.parametrize("who, expected", [("A0001", 200), ("M0001", 200), ("Z0001", 200), ("A0002", 404), ("A0003", 404)])
def test_update_permission(client, db, people, who, expected):
    row = add_off(db, people["A0001"])

    assert client.patch(f"{API}/{row.id}", headers=auth(client, who), json={"note": "수정"}).status_code == expected


# ---------------------------------------------------------------- TO-04 삭제

@pytest.mark.parametrize("who, expected", [("A0001", 204), ("M0001", 204), ("Z0001", 204), ("A0002", 404)])
def test_delete_permission(client, db, people, who, expected):
    row = add_off(db, people["A0001"])
    row_id = row.id

    res = client.delete(f"{API}/{row_id}", headers=auth(client, who))

    assert res.status_code == expected
    db.expire_all()
    assert (db.scalar(select(TimeOff).where(TimeOff.id == row_id)) is None) is (expected == 204)


def test_delete_missing(client, people):
    assert error_code(client.delete(f"{API}/999", headers=auth(client, "Z0001"))) == "TIME_OFF_NOT_FOUND"


# ---------------------------------------------------------------- RF-04 onLeave

def test_group_members_show_on_leave(client, db, people):
    today = datetime_utils.to_kst(datetime_utils.now()).date()
    add_off(db, people["A0001"], start=today - timedelta(days=1), end=today + timedelta(days=1))

    res = client.get(f"/api/v1/support-groups/{people['net'].id}/members", headers=auth(client, "Z0001"))

    assert {item["user"]["employeeNo"]: item["onLeave"] for item in res.json()["items"]} == {
        "M0001": False, "A0001": True, "A0002": False,
    }


def test_open_ticket_count_includes_reservations(client, db, people):
    inquiry = Inquiry(user_id=people["E0001"].id, status="RECEIVED")
    db.add(inquiry)
    db.flush()
    session = ChatSession(inquiry_id=inquiry.id)
    db.add(session)
    db.flush()
    draft = TicketDraft(inquiry_id=inquiry.id, session_id=session.id, status="CONFIRMED")
    db.add(draft)
    db.flush()
    db.add(Ticket(receipt_no="RCPT-0001", draft_id=draft.id, inquiry_id=inquiry.id, session_id=session.id, summary="VPN",
                  assignee_id=people["A0001"].id, jira_sync_status="SYNCED", assign_status="PENDING", work_status=None))
    db.commit()

    res = client.get(f"/api/v1/support-groups/{people['net'].id}/members", headers=auth(client, "Z0001"))

    assert {i["user"]["employeeNo"]: i["openTicketCount"] for i in res.json()["items"]}["A0001"] == 1
