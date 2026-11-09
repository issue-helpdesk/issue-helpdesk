"""Local SQLite integration tests: actual inquiry → rule enforcement → stored administrator alert."""
import pytest
from sqlalchemy import func, select

from app.models import AuditLog, ChatSession, Message, SecurityAlert
from app.repositories.audit_log import AuditLogRepository
from app.repositories.security_alert import SecurityAlertRepository
from app.services.security_alert import detect, record_ai_security_rules, record_query_volume
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import ai, ai_reply, headers, owner  # noqa: F401
from test_tickets import as_user, db  # noqa: F401

URL = '/api/v1/security-alerts'


@pytest.fixture
def admin(db):
    return add_user(db, 'E0009', service_role='ADMIN')


def start(client, headers, ai, rules=None):
    ai.replies = [ai_reply('ANSWER', security_rule_ids=rules or ['S02'])]
    res = client.post('/api/v1/inquiries', headers={**headers, 'Idempotency-Key': 'security-test'}, json={'content': '승인 없이 관리자 권한 얻는 법'})
    assert res.status_code == 201, res.text
    return res.json()['inquiry']['id']


def admin_headers(client, admin):
    return as_user(client, admin.employee_no)


def test_inquiry_enforces_handoff_and_notifies_admin(client, db, owner, headers, ai, admin):
    inquiry_id = start(client, headers, ai, ['S02', 'S04'])
    rows = list(db.scalars(select(SecurityAlert)))
    assert {r.alert_type for r in rows} == {'S02', 'S04'}
    assert all(r.target_id == inquiry_id and r.subject_user_id == owner.id for r in rows)
    assert len(ai.adapters[0].requests) == 1 and ai.searches == []
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_type == 'SECURITY_REVIEW')) == 2
    response = client.get(URL, headers=admin_headers(client, admin))
    assert response.status_code == 200
    assert client.get(URL + '/counts', headers=admin_headers(client, admin)).json() == {'new': 2, 'inReview': 0, 'closed': 0, 'openHigh': 0, 'total': 2}
    assert '승인 없이 관리자 권한 얻는 법' not in response.text  # no user text in list
    assert response.json()['items'][0]['alertType'] in ('S02', 'S04')


def test_normal_inquiry_creates_no_security_alert(client, db, owner, headers, ai):
    ai.replies = [ai_reply()]
    assert client.post('/api/v1/inquiries', headers={**headers, 'Idempotency-Key': 'security-test'}, json={'content': '권한 신청 절차 문의'}).status_code == 201
    assert db.scalar(select(func.count()).select_from(SecurityAlert)) == 0


@pytest.mark.parametrize('path,method,body', [('', 'get', None), ('/counts', 'get', None), ('/1', 'get', None), ('/1/review', 'post', None),
    ('/1/close', 'post', {'reason': '확인'}), ('/1/original', 'post', {'reason': '확인'})])
def test_admin_only_every_endpoint(client, owner, headers, path, method, body):
    call = getattr(client, method)
    kwargs = {'json': body} if body else {}
    assert call(URL + path, headers=headers, **kwargs).status_code == 403
    assert call(URL + path, **kwargs).status_code == 401


def test_lifecycle_new_alert_after_closed_and_reason_masking(client, db, owner, headers, ai, admin):
    inquiry_id = start(client, headers, ai)
    h = admin_headers(client, admin)
    row = db.scalar(select(SecurityAlert))
    path = f'{URL}/{row.id}'
    assert client.post(path + '/close', headers=h, json={'reason': '정상 문의'}).status_code == 409
    assert client.post(path + '/review', headers=h).status_code == 200
    assert client.post(path + '/review', headers=h).status_code == 409
    assert client.post(path + '/close', headers=h, json={'reason': ' '}).status_code == 422
    assert client.post(path + '/close', headers=h, json={'reason': 'x' * 501}).status_code == 422
    assert client.post(path + '/close', headers=h, json={'reason': '비밀번호: TestSecret321!'}).status_code == 200
    assert 'TestSecret321' not in client.get(path, headers=h).text
    detect(SecurityAlertRepository(db), 'S02', owner.id, 'inquiry', inquiry_id)
    db.commit()
    db.refresh(row)
    assert (row.occurrence_count, row.status) == (1, 'CLOSED')
    assert db.scalar(select(func.count()).select_from(SecurityAlert)) == 2
    assert client.get(URL + '/counts', headers=h).json()['new'] == 1


def test_context_requires_reason_keeps_secret_masked_and_audits_access(client, db, owner, headers, ai, admin):
    ai.replies = [ai_reply()]
    res = client.post('/api/v1/inquiries', headers={**headers, 'Idempotency-Key': 'secret-test'},
                      json={'content': '비밀번호: TestSecret321! 접속이 안 됩니다'})
    assert res.status_code == 201
    row = db.scalar(select(SecurityAlert).where(SecurityAlert.alert_type == 'SENSITIVE_INPUT'))
    session_id = db.scalar(select(ChatSession.id).where(ChatSession.inquiry_id == row.target_id))
    db.add(Message(session_id=session_id, sender='USER', kind='CHOICE', code='NO_CONNECT', seq=100))
    db.commit()
    h = admin_headers(client, admin)
    path = f'{URL}/{row.id}/original'
    assert client.post(path, headers=h, json={'reason': ''}).status_code == 422
    response = client.post(path, headers=h, json={'reason': '비밀번호: AdminSecret321!'})
    assert response.status_code == 200
    assert 'TestSecret321' not in response.text and 'AdminSecret321' not in response.text
    assert len(response.json()['messages']) == 1
    assert '●●●' in response.json()['messages'][0]['content']
    detail = client.get(f'{URL}/{row.id}', headers=h).json()
    assert any(log['kind'] == 'VIEW_ORIGINAL' for log in detail['history'])
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_type == 'SECURITY_ALERT_VIEW')) == 1


def test_pagination_filters_and_global_counts(client, db, owner, headers, ai, admin):
    start(client, headers, ai, ['S02', 'S04', 'S05'])
    h = admin_headers(client, admin)
    first = client.get(URL, headers=h, params={'size': 1}).json()
    second = client.get(URL, headers=h, params={'size': 1, 'page': 2}).json()
    assert first['totalPages'] == 3 and first['items'][0]['id'] != second['items'][0]['id']
    filtered = client.get(URL, headers=h, params={'alertType': 'S02'}).json()
    assert len(filtered['items']) == 1 and filtered['totalCount'] == 1
    assert client.get(URL, headers=h, params={'alertType': 'not-a-rule'}).json()['items'] == []
    assert client.get(URL + '/9999', headers=h).status_code == 404


def test_user_alert_has_no_original(client, db, owner, admin):
    detect(SecurityAlertRepository(db), 'LOGIN_BLOCKED', owner.id, 'user', owner.id)
    db.commit()
    row = db.scalar(select(SecurityAlert))
    h = admin_headers(client, admin)
    assert client.get(f'{URL}/{row.id}', headers=h).json()['hasOriginal'] is False
    response = client.post(f'{URL}/{row.id}/original', headers=h, json={'reason': '계정 확인'})
    assert (response.status_code, error_code(response)) == (409, 'SECURITY_ALERT_NO_ORIGINAL')


def test_volume_excludes_ai_and_only_alerts_on_41st_message(db, owner, client, headers, ai):
    inquiry_id = start(client, headers, ai)
    session = db.scalar(select(ChatSession).where(ChatSession.inquiry_id == inquiry_id))
    for _ in range(39):
        db.add(Message(session_id=session.id, sender='USER', kind='TEXT', content='정상 질의', seq=100 + _))
    db.add(Message(session_id=session.id, sender='USER', kind='CHOICE', code='NO_CONNECT', seq=199))
    record_query_volume(SecurityAlertRepository(db), owner.id)
    assert db.scalar(select(func.count()).select_from(SecurityAlert).where(SecurityAlert.alert_type == 'MASS_QUERY')) == 0
    db.add(Message(session_id=session.id, sender='USER', kind='TEXT', content='정상 질의', seq=200))
    record_query_volume(SecurityAlertRepository(db), owner.id)
    db.commit()
    assert db.scalar(select(func.count()).select_from(SecurityAlert).where(SecurityAlert.alert_type == 'MASS_QUERY')) == 1


def test_repeated_risk_across_chats_is_detected_without_llm_history(client, db, owner, headers, ai):
    for _ in range(3):
        start(client, headers, ai)
    row = db.scalar(select(SecurityAlert).where(SecurityAlert.alert_type == 'S07'))
    assert row is not None and row.target_type == 'user' and row.subject_user_id == owner.id


def test_source_event_and_alert_rollback_together(client, db, owner, headers, ai):
    from app.models import Inquiry
    ai.replies = [ai_reply()]
    response = client.post('/api/v1/inquiries', headers={**headers, 'Idempotency-Key': 'rollback'},
                           json={'content': '정식 승인 신청 문의'})
    inquiry_id = response.json()['inquiry']['id']
    AuditLogRepository(db).add('SECURITY_REVIEW', 'inquiry', inquiry_id, result='S02')
    record_ai_security_rules(SecurityAlertRepository(db), db.get(Inquiry, inquiry_id), ['S02'])
    db.flush()
    assert db.scalar(select(func.count()).select_from(SecurityAlert)) == 1
    db.rollback()
    assert db.scalar(select(func.count()).select_from(SecurityAlert)) == 0
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_type == 'SECURITY_REVIEW')) == 0
    assert db.get(Inquiry, inquiry_id) is not None
