"""보안·감사 알림 감지 (06 security_alerts) — SQLite 메모리 DB. 공용 DB 에는 쓰지 않는다."""
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, InquiryAssessment, SecurityAlert
from app.repositories.security_alert import SecurityAlertRepository
from app.services.security_alert import detect, severity_of
from app.utils import datetime_utils
from test_auth import add_user, bearer, client, login  # noqa: F401 (픽스처)
from test_flow_correct import DOC
from test_inquiries import ANSWER, ai, ai_reply, close, db, headers, owner, start, started, taxonomy  # noqa: F401


def alerts(db):
    return db.scalars(select(SecurityAlert).order_by(SecurityAlert.id)).all()


def row(a):
    return (a.alert_type, a.severity, a.status, a.subject_user_id, a.target_type, a.target_id, a.detail,
            a.occurrence_count)


# ---------------------------------------------------------------- 심각도 규칙

@pytest.mark.parametrize("alert_type, detail, expected", [
    ("SENSITIVE_INPUT", {"OTP": 1}, "MEDIUM"),
    ("SENSITIVE_INPUT", {"PASSWORD": 1}, "HIGH"),
    ("SENSITIVE_INPUT", {"OTP": 2, "CARD": 1}, "HIGH"),
    ("BLOCKED_DOC_QUERY", {}, "MEDIUM"),
    ("ACCOUNT_LOCKED", {}, "MEDIUM"),
    ("LOGIN_BLOCKED", {}, "LOW"),
    ("URGENT_CLOSED", {}, "HIGH"),
    ("MASS_QUERY", {}, "MEDIUM"),
])
def test_severity_rule(alert_type, detail, expected):
    assert severity_of(alert_type, detail) == expected


# ---------------------------------------------------------------- 만들기·합치기

def test_detect_creates_new_alert(db, owner):
    repo = SecurityAlertRepository(db)

    detect(repo, "SENSITIVE_INPUT", owner.id, "inquiry", 10, {"OTP": 1})
    db.commit()

    [a] = alerts(db)
    assert row(a) == ("SENSITIVE_INPUT", "MEDIUM", "NEW", owner.id, "inquiry", 10, {"OTP": 1}, 1)
    assert a.first_detected_at == a.last_detected_at


def test_detect_merges_into_open_alert(db, owner, monkeypatch):
    repo = SecurityAlertRepository(db)
    detect(repo, "SENSITIVE_INPUT", owner.id, "inquiry", 10, {"OTP": 1})
    db.commit()
    later = datetime_utils.now() + timedelta(minutes=5)
    monkeypatch.setattr(datetime_utils, "now", lambda: later)

    detect(repo, "SENSITIVE_INPUT", owner.id, "inquiry", 10, {"OTP": 1, "PASSWORD": 2})
    db.commit()

    [a] = alerts(db)
    assert row(a) == ("SENSITIVE_INPUT", "HIGH", "NEW", owner.id, "inquiry", 10, {"OTP": 2, "PASSWORD": 2}, 2)
    assert datetime_utils.as_utc(a.last_detected_at) == later
    assert a.first_detected_at != a.last_detected_at


def test_merge_keeps_reviewing_status(db, owner):
    repo = SecurityAlertRepository(db)
    first = detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    first.status, first.reviewer_id, first.review_started_at = "IN_REVIEW", owner.id, datetime_utils.now()
    db.commit()

    detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    db.commit()

    [a] = alerts(db)
    assert (a.status, a.occurrence_count) == ("IN_REVIEW", 2)


def test_closed_alert_is_not_merged(db, owner):
    repo = SecurityAlertRepository(db)
    first = detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    now = datetime_utils.now()
    first.status, first.reviewer_id, first.review_started_at = "CLOSED", owner.id, now
    first.closed_by, first.closed_at, first.close_reason = owner.id, now, "본인 확인 완료"
    db.commit()

    detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    db.commit()

    assert [(a.status, a.occurrence_count) for a in alerts(db)] == [("CLOSED", 1), ("NEW", 1)]


def test_different_target_makes_separate_alert(db, owner):
    repo = SecurityAlertRepository(db)

    detect(repo, "SENSITIVE_INPUT", owner.id, "inquiry", 10, {"OTP": 1})
    detect(repo, "SENSITIVE_INPUT", owner.id, "inquiry", 11, {"OTP": 1})
    detect(repo, "URGENT_CLOSED", owner.id, "inquiry", 10)
    db.commit()

    assert [(a.alert_type, a.target_id) for a in alerts(db)] == [
        ("SENSITIVE_INPUT", 10), ("SENSITIVE_INPUT", 11), ("URGENT_CLOSED", 10),
    ]


def test_detect_merges_when_other_request_created_first(db, owner, monkeypatch):
    """조회 뒤 다른 요청이 먼저 넣어 UNIQUE 에 걸리면, 호출자 트랜잭션은 살리고 그 알림에 합친다."""
    repo = SecurityAlertRepository(db)
    detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    db.commit()
    original = repo.open_for_update
    calls = []

    def miss_first(*key):
        calls.append(key)
        return None if len(calls) == 1 else original(*key)

    monkeypatch.setattr(repo, "open_for_update", miss_first)
    db.add(AuditLog(event_type="LOGIN_BLOCKED", target_type="user", target_id=owner.id))   # 같은 트랜잭션의 원천 기록

    detect(repo, "LOGIN_BLOCKED", owner.id, "user", owner.id)
    db.commit()

    assert len(calls) == 2
    assert [(a.status, a.occurrence_count) for a in alerts(db)] == [("NEW", 2)]
    assert db.scalar(select(AuditLog.event_type)) == "LOGIN_BLOCKED"


# ---------------------------------------------------------------- 원천 기록 5곳

def test_secret_input_creates_alert_for_writer(client, db, owner, headers):
    inquiry_id = start(client, headers, content="비밀번호는 Abc123!@ 이고 주민번호 900101-1234567 이에요").json()["inquiry"]["id"]

    [a] = alerts(db)
    assert row(a) == ("SENSITIVE_INPUT", "HIGH", "NEW", owner.id, "inquiry", inquiry_id, {"PASSWORD": 1, "RRN": 1}, 1)
    assert "Abc123" not in str(a.detail)


def test_plain_input_creates_no_alert(client, db, headers):
    start(client, headers)

    assert alerts(db) == []


def test_all_blocked_creates_blocked_doc_query_alert(client, db, owner, headers, ai, taxonomy):
    ai.replies = [ai_reply("ANSWER"), ANSWER]
    ai.documents = (replace(DOC, transfer_policy="BLOCKED"),)

    inquiry_id = start(client, headers).json()["inquiry"]["id"]

    assert [row(a) for a in alerts(db)] == [
        ("BLOCKED_DOC_QUERY", "MEDIUM", "NEW", owner.id, "inquiry", inquiry_id, {}, 1),
    ]


def test_answer_with_evidence_creates_no_alert(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply("ANSWER", inquiry_type_code="NET-02"), ANSWER]
    ai.documents = (DOC,)

    start(client, headers)

    assert alerts(db) == []


def test_urgent_close_creates_alert_for_inquiry_owner(client, db, owner, headers):
    inquiry_id = started(client, db, headers, action="ESCALATE")
    db.add(InquiryAssessment(inquiry_id=inquiry_id, urgent_signal=True, action="ESCALATE", override_reasons=[]))
    db.commit()

    close(client, headers, inquiry_id)

    assert [row(a) for a in alerts(db)] == [("URGENT_CLOSED", "HIGH", "NEW", owner.id, "inquiry", inquiry_id, {}, 1)]


def test_normal_close_creates_no_alert(client, db, headers):
    inquiry_id = started(client, db, headers, action="ESCALATE")

    close(client, headers, inquiry_id)

    assert alerts(db) == []


def test_fifth_failure_creates_account_locked_alert(client, db):
    user = add_user(db)

    for _ in range(5):
        login(client, password="Wrong!Pass1")

    assert [row(a) for a in alerts(db)] == [("ACCOUNT_LOCKED", "MEDIUM", "NEW", user.id, "user", user.id, {}, 1)]


def test_blocked_login_attempts_merge_into_one_alert(client, db):
    user = add_user(db, account_status="INACTIVE")

    login(client)
    login(client)

    assert [row(a) for a in alerts(db)] == [("LOGIN_BLOCKED", "LOW", "NEW", user.id, "user", user.id, {}, 2)]


def test_successful_login_creates_no_alert(client, db):
    add_user(db)

    assert bearer(login(client))
    assert alerts(db) == []
