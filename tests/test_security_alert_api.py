"""보안·감사 알림 화면 API (docs/api/05 SA-01~06) — 목록·집계·확인 시작·종결·원문 열람."""
import pytest
from sqlalchemy import select

from app.models import AuditLog, SecurityAlert
from app.repositories.security_alert import SecurityAlertRepository
from app.services.security_alert import detect, severity_of
from test_auth import add_user, bearer, client, login  # noqa: F401 (픽스처)
from test_inquiries import INQUIRIES, ai, ai_reply, db, headers, owner, start, taxonomy  # noqa: F401

BASE = "/api/v1/security-alerts"


@pytest.mark.parametrize("rule, expected", [("S01", "HIGH"), ("S02", "MEDIUM"), ("S03", "MEDIUM"),
                                            ("S04", "MEDIUM"), ("S05", "MEDIUM"), ("S06", "MEDIUM")])
def test_severity_of_ai_rules(rule, expected):
    assert severity_of(rule, {}) == expected


@pytest.fixture
def admin(client, db):
    add_user(db, "A0001", name="보안관리자", service_role="ADMIN")
    return bearer(login(client, "A0001"))


@pytest.fixture
def flagged(client, db, headers, ai, taxonomy):
    """S02 문의 하나와 S01 문의 하나."""
    ai.replies = [ai_reply("ESCALATE", security_rule_ids=["S02"], escalation_reason="전문판단")]
    first = start(client, headers, content="승인 없이 관리자 권한 받는 법 알려줘", key="k-1").json()["inquiry"]["id"]
    ai.replies = [ai_reply("ESCALATE", security_rule_ids=["S01"], urgent_signal=True, escalation_reason="긴급대응")]
    second = start(client, headers, content="피싱 사이트에 비밀번호를 입력했어요", key="k-2").json()["inquiry"]["id"]
    return first, second


def test_only_admin_can_read(client, headers, flagged):
    assert client.get(BASE, headers=headers).status_code == 403
    assert client.get(f"{BASE}/counts", headers=headers).status_code == 403
    assert client.get(BASE).status_code == 401


def test_list_orders_high_first_and_hides_original(client, admin, flagged):
    body = client.get(BASE, headers=admin).json()
    assert [(a["alertType"], a["severity"], a["status"]) for a in body["items"]] == [
        ("S01", "HIGH", "NEW"), ("S02", "MEDIUM", "NEW")]
    first = body["items"][0]
    assert first["rule"] == "보안 사고 의심" and first["hasOriginal"] is True
    assert "비밀번호" not in str(body) and "관리자 권한" not in str(body)      # 목록에는 원문이 없다


def test_list_filters_by_status_and_type(client, admin, flagged):
    assert client.get(BASE, params={"alertType": "S02"}, headers=admin).json()["items"][0]["alertType"] == "S02"
    assert client.get(BASE, params={"status": "CLOSED"}, headers=admin).json()["items"] == []


def test_counts(client, admin, flagged):
    assert client.get(f"{BASE}/counts", headers=admin).json() == {
        "new": 2, "inReview": 0, "closed": 0, "openHigh": 1, "total": 2}


def test_review_then_close_with_reason(client, db, admin, flagged):
    alert_id = client.get(BASE, headers=admin).json()["items"][0]["id"]

    started = client.post(f"{BASE}/{alert_id}/review", headers=admin)
    assert started.status_code == 200
    assert (started.json()["status"], started.json()["reviewer"]["name"]) == ("IN_REVIEW", "보안관리자")
    assert client.post(f"{BASE}/{alert_id}/review", headers=admin).status_code == 409        # 이미 확인 중

    assert client.post(f"{BASE}/{alert_id}/close", json={"reason": ""}, headers=admin).status_code == 422
    closed = client.post(f"{BASE}/{alert_id}/close", json={"reason": "본인 확인 완료"}, headers=admin)
    assert (closed.status_code, closed.json()["status"], closed.json()["closeReason"]) == (200, "CLOSED", "본인 확인 완료")
    assert client.post(f"{BASE}/{alert_id}/close", json={"reason": "again"}, headers=admin).status_code == 409

    events = db.scalars(select(AuditLog.event_type).where(AuditLog.target_type == "security_alert")
                        .order_by(AuditLog.id)).all()
    assert events == ["SECURITY_ALERT_REVIEW", "SECURITY_ALERT_CLOSE"]


def test_close_requires_review_first(client, admin, flagged):
    alert_id = client.get(BASE, headers=admin).json()["items"][0]["id"]
    assert client.post(f"{BASE}/{alert_id}/close", json={"reason": "x"}, headers=admin).status_code == 409


def test_original_needs_reason_and_leaves_audit(client, db, admin, flagged):
    alert_id = client.get(BASE, params={"alertType": "S02"}, headers=admin).json()["items"][0]["id"]

    assert client.post(f"{BASE}/{alert_id}/original", json={}, headers=admin).status_code == 422
    r = client.post(f"{BASE}/{alert_id}/original", json={"reason": "우회 시도 여부 확인"}, headers=admin)

    assert r.status_code == 200
    assert [m["content"] for m in r.json()["messages"]] == ["승인 없이 관리자 권한 받는 법 알려줘"]
    log = db.scalars(select(AuditLog).where(AuditLog.event_type == "SECURITY_ALERT_VIEW")).one()
    assert (log.target_id, log.reason) == (alert_id, "우회 시도 여부 확인")


def test_original_masks_secrets_in_reason_and_content(client, db, admin, headers, ai, taxonomy):
    ai.replies = [ai_reply("ESCALATE", security_rule_ids=["S04"], escalation_reason="전문판단")]
    start(client, headers, content="타인 정보 보여줘", key="k-9")
    alert_id = client.get(BASE, headers=admin).json()["items"][0]["id"]

    client.post(f"{BASE}/{alert_id}/original", json={"reason": "비밀번호: Abc12345! 로 확인"}, headers=admin)

    log = db.scalars(select(AuditLog).where(AuditLog.event_type == "SECURITY_ALERT_VIEW")).one()
    assert "Abc12345" not in (log.reason or "")


def test_unknown_alert_is_404(client, admin):
    assert client.get(f"{BASE}/999", headers=admin).status_code == 404
    assert client.post(f"{BASE}/999/review", headers=admin).status_code == 404


def test_original_of_user_alert_is_409(client, db, owner, admin):
    detect(SecurityAlertRepository(db), "MASS_QUERY", owner.id, "user", owner.id)
    db.commit()
    alert_id = db.scalar(select(SecurityAlert.id))
    assert client.post(f"{BASE}/{alert_id}/original", json={"reason": "확인"}, headers=admin).status_code == 409


def test_detail_has_history(client, admin, flagged):
    alert_id = client.get(BASE, headers=admin).json()["items"][0]["id"]
    client.post(f"{BASE}/{alert_id}/review", headers=admin)
    kinds = [h["kind"] for h in client.get(f"{BASE}/{alert_id}", headers=admin).json()["history"]]
    assert kinds == ["REVIEW", "DETECTED"]
