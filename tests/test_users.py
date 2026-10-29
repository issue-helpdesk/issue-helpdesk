"""사용자 관리 API (US-01~05) — test_auth 의 SQLite 메모리 DB 픽스처를 그대로 쓴다."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, AuthSession, Department, User
from app.repositories.user import UserRepository
from app.utils import datetime_utils
from test_auth import PASSWORD, add_user, bearer, client, db, error_code, login  # noqa: F401 (픽스처)

USERS = "/api/v1/users"
NEW_USER = {
    "employeeNo": "E2026101",
    "name": "이도윤",
    "email": "doyun.lee@itssue.example",
    "position": "팀원",
    "serviceRole": "EMPLOYEE",
}


@pytest.fixture
def admin(db):
    return add_user(db, "A0001", name="관리자", service_role="ADMIN")


@pytest.fixture
def headers(client, admin):
    return bearer(login(client, "A0001"))


def add_department(db, name="IT운영팀", **fields):
    dept = Department(name=name, **fields)
    db.add(dept)
    db.commit()
    return dept


def audit_logs(db, event_type):
    return db.scalars(select(AuditLog).where(AuditLog.event_type == event_type)).all()


def detail(res):
    return res.json()["error"]["details"][0]


# ---------------------------------------------------------------- 권한 공통

@pytest.mark.parametrize("method, path", [
    ("get", ""),
    ("post", ""),
    ("get", "/1"),
    ("patch", "/1"),
    ("post", "/1/temporary-password"),
])
def test_non_admin_is_forbidden(client, db, method, path):
    add_user(db, service_role="AGENT")

    res = client.request(method.upper(), USERS + path, json={}, headers=bearer(login(client)))

    assert res.status_code == 403
    assert error_code(res) == "FORBIDDEN"


def test_admin_api_requires_token(client):
    assert client.get(USERS).status_code == 401


# ---------------------------------------------------------------- US-01 목록

@pytest.fixture
def members(db, admin):
    it, fin = add_department(db), add_department(db, "재무팀")
    add_user(db, "E0001", name="김민지", department_id=it.id, service_role="AGENT", last_login_at=datetime_utils.now())
    add_user(db, "E0002", name="김도윤", department_id=fin.id, account_status="INACTIVE")
    add_user(db, "E0003", name="박서준", email="park_100%@itssue.example")
    return it, fin


def employee_nos(res):
    return [u["employeeNo"] for u in res.json()["items"]]


def test_list_users_default_sort_and_page(client, headers, members):
    res = client.get(USERS, headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert [u["name"] for u in body["items"]] == ["관리자", "김도윤", "김민지", "박서준"]
    assert (body["page"], body["size"], body["totalCount"], body["totalPages"]) == (1, 20, 4, 1)
    assert set(body["items"][0]) == {
        "id", "employeeNo", "name", "email", "department", "position", "serviceRole", "accountStatus", "lastLoginAt",
    }


def test_list_users_search(client, headers, members):
    assert employee_nos(client.get(USERS, params={"q": "김"}, headers=headers)) == ["E0002", "E0001"]
    assert client.get(USERS, params={"q": "e000"}, headers=headers).json()["totalCount"] == 3
    assert employee_nos(client.get(USERS, params={"q": "%"}, headers=headers)) == ["E0003"]


def test_list_users_filters(client, headers, members):
    it, _ = members

    by_dept = client.get(USERS, params={"departmentId": it.id}, headers=headers).json()["items"]
    by_roles = client.get(USERS, params={"serviceRole": ["AGENT", "ADMIN"]}, headers=headers)
    by_status = client.get(USERS, params={"accountStatus": "INACTIVE"}, headers=headers)

    assert [u["department"] for u in by_dept] == [{"id": it.id, "name": "IT운영팀"}]
    assert employee_nos(by_roles) == ["A0001", "E0001"]
    assert employee_nos(by_status) == ["E0002"]


def test_list_users_sort(client, headers, members):
    by_no = client.get(USERS, params={"sort": "employeeNo,desc"}, headers=headers)
    by_login = client.get(USERS, params={"sort": "lastLoginAt,desc"}, headers=headers).json()["items"]

    assert employee_nos(by_no) == ["E0003", "E0002", "E0001", "A0001"]
    assert [u["lastLoginAt"] is None for u in by_login] == [False, False, True, True]   # null 은 항상 뒤


def test_list_users_paging(client, headers, members):
    second = client.get(USERS, params={"size": 3, "page": 2}, headers=headers).json()
    beyond = client.get(USERS, params={"page": 9}, headers=headers).json()

    assert (len(second["items"]), second["totalPages"]) == (1, 2)
    assert beyond["items"] == []


def test_list_users_ignores_unknown_query(client, headers):
    assert client.get(USERS, params={"_": "123"}, headers=headers).status_code == 200


@pytest.mark.parametrize("params, field, reason", [
    ({"sort": "password,asc"}, "sort[0]", "INVALID_FORMAT"),
    ({"sort": "name"}, "sort[0]", "INVALID_FORMAT"),
    ({"serviceRole": "ROOT"}, "serviceRole[0]", "INVALID_VALUE"),
    ({"size": 101}, "size", "OUT_OF_RANGE"),
    ({"page": 0}, "page", "OUT_OF_RANGE"),
])
def test_list_users_validation(client, headers, params, field, reason):
    res = client.get(USERS, params=params, headers=headers)

    assert res.status_code == 422
    assert error_code(res) == "VALIDATION_ERROR"
    assert (detail(res)["field"], detail(res)["reason"]) == (field, reason)


# ---------------------------------------------------------------- US-02 계정 생성

def test_create_user(client, db, admin, headers):
    dept = add_department(db, "재무팀")

    res = client.post(USERS, json={**NEW_USER, "employeeNo": " E2026101 ", "departmentId": dept.id}, headers=headers)

    assert res.status_code == 201
    user = res.json()["user"]
    assert user["employeeNo"] == "E2026101"
    assert user["department"] == {"id": dept.id, "name": "재무팀"}
    assert (user["accountStatus"], user["passwordChangeRequired"], user["passwordChangedAt"]) == ("ACTIVE", True, None)
    assert "passwordHash" not in user
    (log,) = audit_logs(db, "USER_CREATE")
    assert (log.target_id, log.actor_id, log.result) == (user["id"], admin.id, "EMPLOYEE")


def test_created_user_logs_in_with_temporary_password(client, db, headers):
    res = client.post(USERS, json=NEW_USER, headers=headers)
    temporary = res.json()["temporaryPassword"]

    login_res = login(client, "E2026101", temporary)

    assert len(temporary) == 12
    assert db.get(User, res.json()["user"]["id"]).password_hash != temporary
    assert login_res.status_code == 200
    assert login_res.json()["user"]["passwordChangeRequired"] is True


@pytest.mark.parametrize("override, code, field", [
    ({"email": "other@itssue.example"}, "USER_EMPLOYEE_NO_DUPLICATE", "employeeNo"),
    ({"employeeNo": "E9999"}, "USER_EMAIL_DUPLICATE", "email"),
])
def test_create_user_duplicate(client, headers, override, code, field):
    client.post(USERS, json=NEW_USER, headers=headers)

    res = client.post(USERS, json={**NEW_USER, **override}, headers=headers)

    assert res.status_code == 409
    assert error_code(res) == code
    assert (detail(res)["field"], detail(res)["reason"]) == (field, "DUPLICATE")


def test_create_user_duplicate_on_concurrent_insert(client, db, headers, monkeypatch):
    # 중복 확인을 통과한 뒤 같은 사번이 먼저 저장된 경우 → unique 위반을 409 로 바꾼다
    add_user(db, NEW_USER["employeeNo"])
    calls = []
    real = UserRepository.exists_employee_no

    def miss_first(self, employee_no):
        calls.append(employee_no)
        return False if len(calls) == 1 else real(self, employee_no)

    monkeypatch.setattr(UserRepository, "exists_employee_no", miss_first)

    res = client.post(USERS, json={**NEW_USER, "email": "new@itssue.example"}, headers=headers)

    assert res.status_code == 409
    assert error_code(res) == "USER_EMPLOYEE_NO_DUPLICATE"
    assert audit_logs(db, "USER_CREATE") == []


@pytest.mark.parametrize("department", ["missing", "inactive"])
def test_create_user_unknown_department(client, db, headers, department):
    dept_id = 999 if department == "missing" else add_department(db, "폐지팀", is_active=False).id

    res = client.post(USERS, json={**NEW_USER, "departmentId": dept_id}, headers=headers)

    assert res.status_code == 422
    assert (detail(res)["field"], detail(res)["reason"]) == ("departmentId", "NOT_FOUND")


def test_create_user_validation(client, headers):
    res = client.post(USERS, json={"employeeNo": "", "email": "bad", "serviceRole": "ROOT"}, headers=headers)

    assert res.status_code == 422
    reasons = {d["field"]: d["reason"] for d in res.json()["error"]["details"]}
    assert reasons == {"employeeNo": "TOO_SHORT", "name": "REQUIRED", "email": "INVALID_FORMAT", "serviceRole": "INVALID_VALUE"}


# ---------------------------------------------------------------- US-03 상세

def test_get_user(client, db, headers):
    dept = add_department(db)
    user = add_user(db, "E0001", department_id=dept.id, changed=False)

    res = client.get(f"{USERS}/{user.id}", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["department"] == {"id": dept.id, "name": "IT운영팀"}
    assert (body["passwordChangeRequired"], body["failedLoginCount"], body["lockedUntil"]) == (True, 0, None)
    assert body["createdAt"].endswith("+09:00")
    assert "passwordHash" not in body


def test_get_user_not_found(client, headers):
    res = client.get(f"{USERS}/999", headers=headers)

    assert res.status_code == 404
    assert error_code(res) == "USER_NOT_FOUND"


def test_users_me_is_not_captured_by_user_id_route(client, headers):
    assert client.get(f"{USERS}/me", headers=headers).json()["employeeNo"] == "A0001"


# ---------------------------------------------------------------- US-04 정보·상태 변경

@pytest.fixture
def member(db):
    return add_user(db, "E0001", department_id=add_department(db).id, position="팀원")


def test_update_user_changes_only_sent_fields(client, db, headers, member):
    res = client.patch(f"{USERS}/{member.id}", json={"name": " 김민지2 ", "departmentId": None}, headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert (body["name"], body["department"], body["position"]) == ("김민지2", None, "팀원")
    assert body["updatedAt"] is not None


def test_update_role_and_status_requires_reason(client, db, headers, member):
    res = client.patch(f"{USERS}/{member.id}", json={"serviceRole": "AGENT"}, headers=headers)

    assert res.status_code == 422
    assert error_code(res) == "USER_STATUS_REASON_REQUIRED"
    assert (detail(res)["field"], detail(res)["reason"]) == ("reason", "REQUIRED")


def test_update_role_and_status_logs_each(client, db, admin, headers, member):
    body = {"serviceRole": "AGENT", "accountStatus": "INACTIVE", "reason": "퇴사"}

    res = client.patch(f"{USERS}/{member.id}", json=body, headers=headers)

    assert (res.json()["serviceRole"], res.json()["accountStatus"]) == ("AGENT", "INACTIVE")
    (role_log,) = audit_logs(db, "USER_ROLE_CHANGE")
    (status_log,) = audit_logs(db, "USER_STATUS_CHANGE")
    assert (role_log.result, role_log.reason, role_log.actor_id) == ("AGENT", "퇴사", admin.id)
    assert (status_log.result, status_log.reason) == ("INACTIVE", "퇴사")


def test_update_same_role_is_not_a_change(client, db, headers, member):
    res = client.patch(f"{USERS}/{member.id}", json={"serviceRole": "EMPLOYEE", "name": "김민지"}, headers=headers)

    assert res.status_code == 200
    assert audit_logs(db, "USER_ROLE_CHANGE") == []


def test_update_locked_to_active_unlocks(client, db, headers, member):
    member.account_status, member.failed_login_count = "LOCKED", 5
    member.locked_until = datetime_utils.now() + timedelta(minutes=5)
    db.commit()

    res = client.patch(f"{USERS}/{member.id}", json={"accountStatus": "ACTIVE", "reason": "본인 확인"}, headers=headers)

    body = res.json()
    assert (body["accountStatus"], body["failedLoginCount"], body["lockedUntil"]) == ("ACTIVE", 0, None)


def test_update_email_duplicate(client, db, headers, member):
    other = add_user(db, "E0002")

    duplicate = client.patch(f"{USERS}/{member.id}", json={"email": other.email}, headers=headers)
    own = client.patch(f"{USERS}/{member.id}", json={"email": member.email}, headers=headers)

    assert duplicate.status_code == 409
    assert error_code(duplicate) == "USER_EMAIL_DUPLICATE"
    assert own.status_code == 200


@pytest.mark.parametrize("body, field, reason", [
    ({"accountStatus": "LOCKED", "reason": "x"}, "accountStatus", "INVALID_VALUE"),
    ({"employeeNo": "X"}, "employeeNo", "NOT_ALLOWED"),
    ({"name": None}, "name", "INVALID_VALUE"),
    ({"departmentId": 999}, "departmentId", "NOT_FOUND"),
])
def test_update_user_validation(client, headers, member, body, field, reason):
    res = client.patch(f"{USERS}/{member.id}", json=body, headers=headers)

    assert res.status_code == 422
    assert (detail(res)["field"], detail(res)["reason"]) == (field, reason)


def test_update_self_role_is_not_allowed(client, admin, headers):
    role = client.patch(f"{USERS}/{admin.id}", json={"serviceRole": "EMPLOYEE", "reason": "x"}, headers=headers)
    name = client.patch(f"{USERS}/{admin.id}", json={"name": "관리자2"}, headers=headers)

    assert role.status_code == 409
    assert error_code(role) == "USER_SELF_CHANGE_NOT_ALLOWED"
    assert name.status_code == 200


def test_update_user_not_found(client, headers):
    assert error_code(client.patch(f"{USERS}/999", json={"name": "x"}, headers=headers)) == "USER_NOT_FOUND"


def test_demoted_admin_loses_access_immediately(client, db, headers):
    other = add_user(db, "A0002", service_role="ADMIN")
    other_headers = bearer(login(client, "A0002"))

    client.patch(f"{USERS}/{other.id}", json={"serviceRole": "EMPLOYEE", "reason": "권한 회수"}, headers=headers)

    assert client.get(USERS, headers=other_headers).status_code == 403


# ---------------------------------------------------------------- US-05 임시 비밀번호 재발급

def reset(client, user_id, headers, **kwargs):
    return client.post(f"{USERS}/{user_id}/temporary-password", headers=headers, **kwargs)


def test_reset_password_unlocks_and_revokes_sessions(client, db, admin, headers, member):
    old_headers = bearer(login(client, "E0001"))
    member.account_status, member.failed_login_count = "LOCKED", 5
    member.locked_until = datetime_utils.now() + timedelta(minutes=10)
    db.commit()

    res = reset(client, member.id, headers, json={"reason": "비밀번호 분실"})

    assert res.status_code == 201
    assert set(res.json()) == {"temporaryPassword"}
    db.refresh(member)
    assert (member.account_status, member.failed_login_count, member.locked_until) == ("ACTIVE", 0, None)
    assert member.password_changed_at is None
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == member.id)).all()
    assert sessions and all(s.revoke_reason == "PASSWORD_RESET" for s in sessions)
    assert client.get(f"{USERS}/me", headers=old_headers).status_code == 401
    (log,) = audit_logs(db, "PASSWORD_RESET")
    assert (log.target_id, log.actor_id, log.result, log.reason) == (member.id, admin.id, "ACTIVE", "비밀번호 분실")


def test_reset_password_replaces_password(client, db, headers, member):
    temporary = reset(client, member.id, headers).json()["temporaryPassword"]

    assert login(client, "E0001", PASSWORD).status_code == 401
    res = login(client, "E0001", temporary)
    assert res.status_code == 200
    assert res.json()["user"]["passwordChangeRequired"] is True


def test_reset_password_keeps_inactive(client, db, headers):
    user = add_user(db, "E0002", account_status="INACTIVE")

    res = reset(client, user.id, headers)

    assert res.status_code == 201
    db.refresh(user)
    assert user.account_status == "INACTIVE"


def test_reset_password_rejects_empty_reason(client, headers, member):
    assert reset(client, member.id, headers, json={"reason": ""}).status_code == 422


def test_reset_password_not_found(client, headers):
    assert error_code(reset(client, 999, headers)) == "USER_NOT_FOUND"
