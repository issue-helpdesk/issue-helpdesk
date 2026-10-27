"""인증 API (AU-01~05) — SQLite 메모리 DB 로 돌린다. 공용 DB 에는 쓰지 않는다."""
import os
from datetime import timedelta

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-0123")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.utils import datetime_utils
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, AuthSession, Base, Department, SupportGroup, SupportGroupMember, User

PASSWORD = "Init!Pass123"
NEW_PASSWORD = "New!Passw0rd"
TABLES = ["departments", "users", "support_groups", "support_group_members", "audit_logs", "auth_sessions"]


@compiles(BigInteger, "sqlite")
def bigint_as_integer(type_, compiler, **kw):
    # SQLite 는 INTEGER PRIMARY KEY 만 자동 증가한다
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, base_url="https://testserver")   # Refresh 쿠키는 Secure 라 https 에서만 오간다
    app.dependency_overrides.clear()


def add_user(db, employee_no="E2024017", password=PASSWORD, changed=True, **fields):
    values = {
        "name": "김민지",
        "email": f"{employee_no.lower()}@itssue.example",
        "service_role": "EMPLOYEE",
        "account_status": "ACTIVE",
        "password_changed_at": datetime_utils.now() if changed else None,
        **fields,
    }
    user = User(employee_no=employee_no, password_hash=hash_password(password), **values)
    db.add(user)
    db.commit()
    return user


def login(client, employee_no="E2024017", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"employeeNo": employee_no, "password": password})


def bearer(res):
    return {"Authorization": f"Bearer {res.json()['accessToken']}"}


def error_code(res):
    return res.json()["error"]["code"]


# ---------------------------------------------------------------- AU-01 로그인

def test_login_returns_token_and_me(client, db):
    dept = Department(name="IT운영팀")
    db.add(dept)
    db.flush()
    user = add_user(db, department_id=dept.id, position="팀원")
    group, left = SupportGroup(name="서비스데스크"), SupportGroup(name="네트워크")
    db.add_all([group, left])
    db.flush()
    db.add(SupportGroupMember(group_id=group.id, user_id=user.id, member_role="AGENT", assignable=True))
    db.add(SupportGroupMember(group_id=left.id, user_id=user.id, member_role="AGENT", assignable=True, is_active=False))
    db.commit()

    res = login(client)

    assert res.status_code == 200
    body = res.json()
    assert body["tokenType"] == "Bearer"
    assert body["expiresIn"] == 30 * 60
    me = body["user"]
    assert me["employeeNo"] == "E2024017"
    assert me["department"] == {"id": dept.id, "name": "IT운영팀"}
    assert me["passwordChangeRequired"] is False
    assert me["lastLoginAt"].endswith("+09:00")
    assert me["supportGroups"] == [{"groupId": group.id, "groupName": "서비스데스크", "memberRole": "AGENT", "assignable": True}]
    assert "passwordHash" not in me


def test_login_sets_httponly_refresh_cookie(client, db):
    add_user(db)

    res = login(client)

    cookie = res.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "SameSite=strict" in cookie
    assert "refreshToken" not in res.json()


def test_login_unknown_and_wrong_password_look_the_same(client, db):
    add_user(db)

    unknown = login(client, employee_no="NOPE")
    wrong = login(client, password="Wrong!Pass1")

    assert unknown.status_code == wrong.status_code == 401
    assert error_code(unknown) == error_code(wrong) == "AUTH_INVALID_CREDENTIALS"
    assert unknown.json()["error"]["details"] is None


def test_login_trims_employee_no_but_not_password(client, db):
    add_user(db)

    assert login(client, employee_no="  E2024017 ").status_code == 200
    assert login(client, password=f" {PASSWORD}").status_code == 401


def test_fifth_failure_locks_account(client, db):
    user = add_user(db)

    for _ in range(4):
        assert error_code(login(client, password="Wrong!Pass1")) == "AUTH_INVALID_CREDENTIALS"
    res = login(client, password="Wrong!Pass1")

    assert res.status_code == 403
    assert error_code(res) == "AUTH_ACCOUNT_LOCKED"
    detail = res.json()["error"]["details"][0]
    assert detail["reason"] == "LOCKED_UNTIL" and detail["value"].endswith("+09:00")
    db.refresh(user)
    assert user.account_status == "LOCKED"
    assert db.scalar(select(AuditLog.event_type)) == "ACCOUNT_LOCKED"


def test_locked_account_rejects_correct_password_and_logs_attempt(client, db):
    add_user(db, account_status="LOCKED", failed_login_count=5, locked_until=datetime_utils.now() + timedelta(minutes=10))

    res = login(client)

    assert error_code(res) == "AUTH_ACCOUNT_LOCKED"
    log = db.scalars(select(AuditLog)).one()
    assert (log.event_type, log.result) == ("LOGIN_BLOCKED", "LOCKED")


def test_lock_expires_after_ten_minutes(client, db, monkeypatch):
    user = add_user(db, account_status="LOCKED", failed_login_count=5, locked_until=datetime_utils.now() + timedelta(minutes=10))
    later = datetime_utils.now() + timedelta(minutes=11)
    monkeypatch.setattr(datetime_utils, "now", lambda: later)

    res = login(client)

    assert res.status_code == 200
    db.refresh(user)
    assert (user.account_status, user.failed_login_count, user.locked_until) == ("ACTIVE", 0, None)


def test_inactive_account_cannot_login(client, db):
    add_user(db, account_status="INACTIVE")

    res = login(client)

    assert res.status_code == 403
    assert error_code(res) == "AUTH_ACCOUNT_INACTIVE"


def test_login_validation_error_uses_camel_case_field(client):
    res = client.post("/api/v1/auth/login", json={"password": "x"})

    assert res.status_code == 422
    assert res.json()["error"]["details"] == [{"field": "employeeNo", "reason": "REQUIRED", "message": "필수 입력값입니다."}]


def test_success_resets_failed_count(client, db):
    user = add_user(db)
    login(client, password="Wrong!Pass1")

    login(client)

    db.refresh(user)
    assert user.failed_login_count == 0


# ---------------------------------------------------------------- 인증 공통

def test_protected_api_requires_token(client):
    res = client.get("/api/v1/users/me")

    assert res.status_code == 401
    assert error_code(res) == "UNAUTHORIZED"
    assert res.json()["error"]["traceId"] == res.headers["X-Request-Id"]


def test_invalid_token_is_rejected(client):
    res = client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-token"})

    assert error_code(res) == "UNAUTHORIZED"


def test_expired_token_returns_token_expired(client):
    token, _ = create_access_token(1, 1, datetime_utils.now() - timedelta(hours=1))

    res = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert error_code(res) == "TOKEN_EXPIRED"


def test_inactive_after_login_blocks_next_request(client, db):
    user = add_user(db)
    headers = bearer(login(client))
    user.account_status = "INACTIVE"
    db.commit()

    res = client.get("/api/v1/users/me", headers=headers)

    assert res.status_code == 403
    assert error_code(res) == "AUTH_ACCOUNT_INACTIVE"


# ---------------------------------------------------------------- AU-03 · 임시 비밀번호

def test_me_works_with_temporary_password(client, db):
    add_user(db, changed=False)
    res = login(client)
    assert res.json()["user"]["passwordChangeRequired"] is True

    me = client.get("/api/v1/users/me", headers=bearer(res))

    assert me.status_code == 200
    assert me.json()["passwordChangeRequired"] is True


def test_temporary_password_blocks_other_apis(client, db):
    from app.api.deps import CurrentAuth

    @app.get("/api/v1/_test/protected")
    def protected(auth: CurrentAuth):
        return {"ok": True}

    try:
        add_user(db, changed=False)
        res = client.get("/api/v1/_test/protected", headers=bearer(login(client)))
    finally:
        app.router.routes.pop()

    assert res.status_code == 403
    assert error_code(res) == "AUTH_PASSWORD_CHANGE_REQUIRED"


# ---------------------------------------------------------------- AU-04 비밀번호 변경

def change(client, headers, current=PASSWORD, new=NEW_PASSWORD):
    return client.put("/api/v1/users/me/password", headers=headers, json={"currentPassword": current, "newPassword": new})


def test_change_password_revokes_all_sessions(client, db):
    user = add_user(db, changed=False)
    first = bearer(login(client))
    second = bearer(login(client))

    res = change(client, first)

    assert res.status_code == 204
    db.refresh(user)
    assert user.password_changed_at is not None
    assert error_code(client.get("/api/v1/users/me", headers=first)) == "UNAUTHORIZED"
    assert error_code(client.get("/api/v1/users/me", headers=second)) == "UNAUTHORIZED"
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_change_password_wrong_current(client, db):
    add_user(db)

    res = change(client, bearer(login(client)), current="Wrong!Pass1")

    assert res.status_code == 400
    assert error_code(res) == "AUTH_CURRENT_PASSWORD_MISMATCH"


@pytest.mark.parametrize("new, reasons", [
    ("Ab1!", ["TOO_SHORT"]),
    ("Aa1!" * 17, ["TOO_LONG"]),
    ("abcdefgh1", ["INVALID_VALUE"]),
    ("E2024017", ["INVALID_VALUE", "DUPLICATE"]),
    (PASSWORD, ["DUPLICATE"]),
])
def test_change_password_policy(client, db, new, reasons):
    add_user(db)

    res = change(client, bearer(login(client)), new=new)

    assert res.status_code == 422
    assert error_code(res) == "AUTH_PASSWORD_POLICY_VIOLATION"
    assert [d["reason"] for d in res.json()["error"]["details"]] == reasons


# ---------------------------------------------------------------- AU-02 로그아웃

def test_logout_revokes_only_current_session(client, db):
    add_user(db)
    first = bearer(login(client))
    second = bearer(login(client))

    res = client.post("/api/v1/auth/logout", headers=first)

    assert res.status_code == 204
    assert 'refresh_token=""' in res.headers["set-cookie"]
    assert error_code(client.get("/api/v1/users/me", headers=first)) == "UNAUTHORIZED"
    assert client.get("/api/v1/users/me", headers=second).status_code == 200


# ---------------------------------------------------------------- AU-05 토큰 재발급

def test_refresh_rotates_token(client, db):
    add_user(db)
    login(client)
    old = client.cookies["refresh_token"]

    res = client.post("/api/v1/auth/refresh")

    assert res.status_code == 200
    assert res.json()["user"]["employeeNo"] == "E2024017"
    assert client.cookies["refresh_token"] != old
    assert client.get("/api/v1/users/me", headers=bearer(res)).status_code == 200


def test_refresh_reuse_revokes_session(client, db):
    add_user(db)
    access = bearer(login(client))
    old = client.cookies["refresh_token"]
    client.post("/api/v1/auth/refresh")

    client.cookies.set("refresh_token", old, path="/api/v1/auth")
    reused = client.post("/api/v1/auth/refresh")

    assert error_code(reused) == "AUTH_REFRESH_TOKEN_INVALID"
    assert db.scalar(select(AuthSession.revoke_reason)) == "TOKEN_REUSE"
    assert error_code(client.get("/api/v1/users/me", headers=access)) == "UNAUTHORIZED"


def test_refresh_without_cookie(client):
    res = client.post("/api/v1/auth/refresh")

    assert res.status_code == 401
    assert error_code(res) == "AUTH_REFRESH_TOKEN_INVALID"


def test_refresh_after_logout_fails(client, db):
    add_user(db)
    headers = bearer(login(client))
    token = client.cookies["refresh_token"]
    client.post("/api/v1/auth/logout", headers=headers)

    client.cookies.set("refresh_token", token, path="/api/v1/auth")
    res = client.post("/api/v1/auth/refresh")

    assert error_code(res) == "AUTH_REFRESH_TOKEN_INVALID"


def test_refresh_expired_session(client, db, monkeypatch):
    add_user(db)
    login(client)
    later = datetime_utils.now() + timedelta(days=8)
    monkeypatch.setattr(datetime_utils, "now", lambda: later)

    res = client.post("/api/v1/auth/refresh")

    assert error_code(res) == "AUTH_REFRESH_TOKEN_INVALID"
