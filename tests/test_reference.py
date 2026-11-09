"""기준 정보 API (RF-01~05) — SQLite 메모리 DB."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    Category,
    ChatSession,
    Department,
    Inquiry,
    InquiryType,
    MemberSkill,
    SupportGroup,
    SupportGroupMember,
    Ticket,
    TicketDraft,
)
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)

API = "/api/v1"
REFERENCE_TABLES = TABLES + ["categories", "inquiry_types", "member_skills", "inquiries", "chat_sessions",
                             "ticket_drafts", "tickets", "time_off"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in REFERENCE_TABLES])
    with Session(engine) as session:
        yield session
    engine.dispose()


def headers_for(client, db, employee_no, service_role="EMPLOYEE", **fields):
    add_user(db, employee_no, service_role=service_role, **fields)
    return bearer(login(client, employee_no))


def add(db, *rows):
    db.add_all(rows)
    db.commit()
    return rows


@pytest.fixture
def taxonomy(db):
    net, desk = add(db, SupportGroup(name="네트워크팀", description="VPN, Wi-Fi, LAN"),
                    SupportGroup(name="서비스데스크", is_triage=True))
    add(db, SupportGroup(name="폐지팀", is_active=False),
        Category(code="NET", name="VPN·네트워크", description="VPN, Wi-Fi, LAN, 인터넷 장애"),
        Category(code="ACC", name="계정·로그인"))
    vpn, wifi, _, _ = add(
        db,
        InquiryType(code="NET-01", category_code="NET", name="VPN 접속 불가", request_kind="INCIDENT",
                    default_urgency="P3", default_group_id=net.id),
        InquiryType(code="NET-02", category_code="NET", name="Wi-Fi 연결 불가", request_kind="INCIDENT",
                    default_urgency="P3", default_group_id=net.id),
        InquiryType(code="ACC-01", category_code="ACC", name="비밀번호 초기화", request_kind="REQUEST",
                    default_urgency="P4", default_group_id=desk.id),
        InquiryType(code="NET-99", category_code="NET", name="옛 유형", request_kind="QUESTION",
                    default_urgency="P4", default_group_id=net.id, is_active=False),
    )
    return net, desk, vpn, wifi


# ---------------------------------------------------------------- RF-01 분류

def test_list_categories_sorted_by_code(client, db, taxonomy):
    res = client.get(f"{API}/categories", headers=headers_for(client, db, "E0001"))

    assert res.status_code == 200
    assert res.json() == {"items": [
        {"code": "ACC", "name": "계정·로그인", "description": None},
        {"code": "NET", "name": "VPN·네트워크", "description": "VPN, Wi-Fi, LAN, 인터넷 장애"},
    ]}


def test_reference_requires_token(client):
    assert client.get(f"{API}/categories").status_code == 401


# ---------------------------------------------------------------- RF-02 세부 유형

def codes(res):
    return [item["code"] for item in res.json()["items"]]


def test_list_inquiry_types(client, db, taxonomy):
    net, *_ = taxonomy

    res = client.get(f"{API}/inquiry-types", headers=headers_for(client, db, "E0001"))

    assert res.status_code == 200
    assert codes(res) == ["ACC-01", "NET-01", "NET-02"]
    assert res.json()["items"][1] == {
        "id": res.json()["items"][1]["id"], "code": "NET-01", "categoryCode": "NET", "name": "VPN 접속 불가",
        "requestKind": "INCIDENT", "defaultUrgency": "P3",
        "defaultGroupId": net.id, "defaultGroup": {"id": net.id, "name": "네트워크팀"},
        "isActive": True,
    }


def test_list_inquiry_types_filters(client, db, taxonomy):
    headers = headers_for(client, db, "E0001")

    by_category = client.get(f"{API}/inquiry-types", params={"categoryCode": ["NET", "ACC"]}, headers=headers)
    inactive = client.get(f"{API}/inquiry-types", params={"categoryCode": "NET", "isActive": "false"},
                          headers=headers)

    assert codes(by_category) == ["ACC-01", "NET-01", "NET-02"]
    assert codes(inactive) == ["NET-99"]


def test_list_inquiry_types_unknown_category(client, db, taxonomy):
    res = client.get(f"{API}/inquiry-types", params={"categoryCode": ["NET", "XYZ"]},
                     headers=headers_for(client, db, "E0001"))

    assert res.status_code == 422
    assert error_code(res) == "VALIDATION_ERROR"
    assert res.json()["error"]["details"][0]["field"] == "categoryCode"
    assert res.json()["error"]["details"][0]["reason"] == "NOT_FOUND"


# ---------------------------------------------------------------- RF-03 담당 그룹

def test_list_support_groups(client, db, taxonomy):
    headers = headers_for(client, db, "A0001", "AGENT")

    active = client.get(f"{API}/support-groups", headers=headers)
    inactive = client.get(f"{API}/support-groups", params={"isActive": False}, headers=headers)

    assert active.status_code == 200
    assert [g["name"] for g in active.json()["items"]] == ["네트워크팀", "서비스데스크"]
    assert active.json()["items"][1] == {
        "id": active.json()["items"][1]["id"], "name": "서비스데스크", "departmentId": None, "description": None,
        "isTriage": True, "isActive": True,
    }
    assert [g["name"] for g in inactive.json()["items"]] == ["폐지팀"]


def test_list_support_groups_forbidden_for_employee(client, db, taxonomy):
    res = client.get(f"{API}/support-groups", headers=headers_for(client, db, "E0001"))

    assert res.status_code == 403
    assert error_code(res) == "FORBIDDEN"


# ---------------------------------------------------------------- RF-04 그룹 구성원

def member(group, user, role="AGENT", assignable=True, jira="acc-1", is_active=True):
    return SupportGroupMember(group_id=group.id, user_id=user.id, member_role=role, assignable=assignable,
                              jira_account_id=jira, is_active=is_active)


def add_open_ticket(db, assignee, work_status):
    inquiry = Inquiry(user_id=assignee.id, status="RECEIVED")
    db.add(inquiry)
    db.flush()
    session = ChatSession(inquiry_id=inquiry.id)
    db.add(session)
    db.flush()
    draft = TicketDraft(inquiry_id=inquiry.id, session_id=session.id, status="CONFIRMED")
    db.add(draft)
    db.flush()
    db.add(Ticket(receipt_no=f"R-{draft.id}", draft_id=draft.id, inquiry_id=inquiry.id, session_id=session.id,
                  summary="VPN", assignee_id=assignee.id, jira_sync_status="SYNCED", assign_status="ASSIGNED",
                  work_status=work_status))
    db.commit()


@pytest.fixture
def team(db, taxonomy):
    """네트워크팀: 팀장 1, 배정 가능 1, Jira 없음 1, 배정 제외 1, 비활성 계정 1."""
    net, desk, vpn, wifi = taxonomy
    manager = add_user(db, "M0001", name="가팀장", service_role="AGENT", position="팀장")
    ready = add_user(db, "E1001", name="나배정", service_role="AGENT", position="팀원")
    no_jira = add_user(db, "E1002", name="다지라", service_role="AGENT")
    excluded = add_user(db, "E1003", name="라제외", service_role="AGENT")
    inactive = add_user(db, "E1004", name="마퇴사", service_role="AGENT", account_status="INACTIVE")
    add(db,
        member(net, manager, role="MANAGER"),
        member(net, ready, jira="acc-ready"),
        member(net, no_jira, jira="  "),
        member(net, excluded, assignable=False),
        member(net, inactive),
        MemberSkill(user_id=ready.id, inquiry_type_id=vpn.id),
        MemberSkill(user_id=ready.id, inquiry_type_id=wifi.id),
        MemberSkill(user_id=no_jira.id, inquiry_type_id=wifi.id))
    add_open_ticket(db, ready, "RDY")
    add_open_ticket(db, ready, "WIP")
    add_open_ticket(db, ready, "CLS")
    return net, desk, vpn, wifi


def members_url(group):
    return f"{API}/support-groups/{group.id}/members"


def names(res):
    return [item["user"]["name"] for item in res.json()["items"]]


def test_manager_lists_own_group_members(client, db, team):
    net, _, vpn, wifi = team

    res = client.get(members_url(net), headers=bearer(login(client, "M0001")))

    assert res.status_code == 200
    assert names(res) == ["가팀장", "나배정", "다지라", "라제외", "마퇴사"]
    ready = res.json()["items"][1]
    assert ready == {
        "userId": ready["user"]["id"],
        "user": {"id": ready["user"]["id"], "employeeNo": "E1001", "name": "나배정"},
        "position": "팀원",
        "memberRole": "AGENT",
        "assignable": True,
        "hasJiraAccount": True,
        "jiraAccountId": None,   # MANAGER 에게는 주지 않는다
        "isActive": True,
        "skills": [{"id": vpn.id, "code": "NET-01", "name": "VPN 접속 불가"},
                   {"id": wifi.id, "code": "NET-02", "name": "Wi-Fi 연결 불가"}],
        "openTicketCount": 2,    # CLS 는 세지 않는다
        "onLeave": False,
    }
    assert res.json()["items"][2]["hasJiraAccount"] is False   # 공백만 있는 계정은 없는 것으로 본다


def test_admin_sees_jira_account(client, db, team):
    net, *_ = team

    res = client.get(members_url(net), headers=headers_for(client, db, "A0001", "ADMIN"))

    assert res.status_code == 200
    assert res.json()["items"][1]["jiraAccountId"] == "acc-ready"


def test_list_members_assignable_and_skill_filters(client, db, team):
    net, _, vpn, wifi = team
    headers = bearer(login(client, "M0001"))

    assignable = client.get(members_url(net), params={"assignable": True}, headers=headers)
    by_skill = client.get(members_url(net), params={"inquiryTypeId": wifi.id}, headers=headers)
    both = client.get(members_url(net), params={"assignable": True, "inquiryTypeId": wifi.id}, headers=headers)

    assert names(assignable) == ["가팀장", "나배정"]
    assert names(by_skill) == ["나배정", "다지라"]
    assert names(both) == ["나배정"]


def test_list_members_permission(client, db, team):
    net, desk, *_ = team
    manager = bearer(login(client, "M0001"))
    agent = bearer(login(client, "E1001"))
    employee = headers_for(client, db, "E0001")

    assert client.get(members_url(desk), headers=manager).status_code == 403     # 다른 그룹
    assert client.get(members_url(net), headers=agent).status_code == 403       # 그룹의 AGENT
    assert error_code(client.get(members_url(net), headers=employee)) == "FORBIDDEN"


def test_list_members_group_not_found(client, db, team):
    res = client.get(f"{API}/support-groups/9999/members", headers=headers_for(client, db, "A0001", "ADMIN"))

    assert res.status_code == 404
    assert error_code(res) == "NOT_FOUND"


def test_inactive_group_has_no_assignable_members(client, db, team):
    net, *_ = team
    net.is_active = False
    db.commit()
    headers = headers_for(client, db, "A0001", "ADMIN")

    assert len(client.get(members_url(net), headers=headers).json()["items"]) == 5
    assert client.get(members_url(net), params={"assignable": True}, headers=headers).json()["items"] == []


# ---------------------------------------------------------------- RF-05 부서

def test_list_departments(client, db):
    hq, _ = add(db, Department(name="경영지원본부"), Department(name="폐지부서", is_active=False))
    add(db, Department(name="IT운영팀", parent_id=hq.id))
    headers = headers_for(client, db, "A0001", "ADMIN")

    res = client.get(f"{API}/departments", headers=headers)
    inactive = client.get(f"{API}/departments", params={"isActive": False}, headers=headers)

    assert res.status_code == 200
    assert [(d["name"], d["parentId"]) for d in res.json()["items"]] == [("IT운영팀", hq.id), ("경영지원본부", None)]
    assert set(res.json()["items"][0]) == {"id", "name", "parentId", "isActive"}
    assert [d["name"] for d in inactive.json()["items"]] == ["폐지부서"]


def test_list_departments_forbidden_for_agent(client, db):
    res = client.get(f"{API}/departments", headers=headers_for(client, db, "E0001", "AGENT"))

    assert res.status_code == 403
    assert error_code(res) == "FORBIDDEN"
