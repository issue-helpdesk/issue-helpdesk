"""FAQ API (FQ-01~05) — SQLite 메모리 DB. 게시 조건은 현행 청크의 meta.faq_ids 로 판단한다."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import AuditLog, Category, DocumentChunk, DocumentVersion, Faq, KnowledgeDocument
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_inquiries import create_sqlite_tables

FAQS = "/api/v1/faqs"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ["categories", "faqs", "knowledge_documents", "document_versions",
                                           "document_chunks"])
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_document(db, doc_code, doc_type="GUIDE", view_scope="ALL", is_current=True, is_active=True, links=()):
    """links: [(위치, [FAQ 번호…])] 청크마다 하나."""
    document = KnowledgeDocument(doc_code=doc_code, doc_type=doc_type, title=f"{doc_code} 가이드", is_active=is_active)
    db.add(document)
    db.flush()
    version = DocumentVersion(document_id=document.id, version="v1.0", view_scope=view_scope, transfer_policy="ALLOWED",
                              is_current=is_current, ingest_status="DONE")
    db.add(version)
    db.flush()
    for seq, (location, codes) in enumerate(links, start=1):
        db.add(DocumentChunk(version_id=version.id, location=location, content="본문", seq=seq, unit_key=f"u{seq}",
                             chunk_type="ITEM", meta={"faq_ids": codes}))
    return document


def add_faq(db, code, category="ACC", is_active=True, question=None, keywords=()):
    faq = Faq(faq_code=code, category_code=category, question=question or f"{code} 질문", answer="답변",
              keywords=list(keywords), is_active=is_active)
    db.add(faq)
    return faq


@pytest.fixture
def faqs(db):
    """FAQ-001 공개 / 002 제한 문서에도 연결 / 003 현행 아님 / 004 비활성 문서 / 005 비게시 초안."""
    db.add_all([Category(code="ACC", name="계정·로그인"), Category(code="NET", name="VPN·네트워크")])
    add_document(db, "IT-ACC-001", links=[("FAQ Q1", ["FAQ-001", "FAQ-002"]), ("3.1", ["FAQ-001"]), ("3.2", [])])
    add_document(db, "IT-ACC-001-M", doc_type="MANUAL", view_scope="AGENT", links=[("2.1", ["FAQ-002"])])
    add_document(db, "IT-NET-001", is_current=False, links=[("1.1", ["FAQ-003"])])
    add_document(db, "IT-NET-002", is_active=False, links=[("1.1", ["FAQ-004"])])
    rows = {
        "FAQ-001": add_faq(db, "FAQ-001", question="비밀번호를 5회 틀려서 계정이 잠겼어요.", keywords=["잠금", "비밀번호"]),
        "FAQ-002": add_faq(db, "FAQ-002"),
        "FAQ-003": add_faq(db, "FAQ-003", category="NET"),
        "FAQ-004": add_faq(db, "FAQ-004", category="NET"),
        "FAQ-005": add_faq(db, "FAQ-005", is_active=False),
    }
    db.commit()
    return rows


@pytest.fixture
def employee(client, db):
    add_user(db, "E0001")
    return bearer(login(client, "E0001"))


@pytest.fixture
def admin(client, db):
    add_user(db, "A0001", name="관리자", service_role="ADMIN")
    return bearer(login(client, "A0001"))


def codes(res):
    return [item["faqCode"] for item in res.json()["items"]]


# ---------------------------------------------------------------- FQ-01 목록

def test_employee_sees_only_publishable_faqs(client, employee, faqs):
    res = client.get(FAQS, headers=employee)

    assert res.status_code == 200
    assert codes(res) == ["FAQ-001"]
    assert res.json()["totalCount"] == 1                    # 조건은 페이지 계산 전에 건다
    item = res.json()["items"][0]
    assert (item["category"], item["keywords"], item["updatedBy"]) == ({"code": "ACC", "name": "계정·로그인"},
                                                                     ["잠금", "비밀번호"], None)


def test_admin_sees_all_and_filters_by_active(client, admin, faqs):
    assert codes(client.get(FAQS, headers=admin)) == ["FAQ-001", "FAQ-002", "FAQ-003", "FAQ-004", "FAQ-005"]
    assert codes(client.get(FAQS, params={"isActive": "false"}, headers=admin)) == ["FAQ-005"]


def test_employee_cannot_filter_by_active(client, employee, faqs):
    res = client.get(FAQS, params={"isActive": "true"}, headers=employee)

    assert res.status_code == 403


@pytest.mark.parametrize("params, expected", [
    ({"q": "계정이 잠겼"}, ["FAQ-001"]),                    # 질문 부분 일치
    ({"q": "비밀번호"}, ["FAQ-001"]),                       # 키워드
    ({"categoryCode": "NET"}, ["FAQ-003", "FAQ-004"]),
    ({"sort": "faqCode,desc", "size": 2}, ["FAQ-005", "FAQ-004"]),
])
def test_list_filters(client, admin, faqs, params, expected):
    assert codes(client.get(FAQS, params=params, headers=admin)) == expected


def test_list_validation(client, employee, faqs):
    assert client.get(FAQS, params={"sort": "question,asc"}, headers=employee).status_code == 422


# ---------------------------------------------------------------- FQ-02 상세

def test_detail_with_sources_in_viewer_scope(client, db, employee, admin, faqs):
    mine = client.get(f"{FAQS}/{faqs['FAQ-001'].id}", headers=employee)

    assert mine.status_code == 200
    assert [(s["docCode"], s["version"], s["location"]) for s in mine.json()["sources"]] == [
        ("IT-ACC-001", "v1.0", "FAQ Q1"), ("IT-ACC-001", "v1.0", "3.1"),
    ]
    restricted = client.get(f"{FAQS}/{faqs['FAQ-002'].id}", headers=admin).json()
    assert [s["docCode"] for s in restricted["sources"]] == ["IT-ACC-001", "IT-ACC-001-M"]     # ADMIN 은 매뉴얼도


@pytest.mark.parametrize("code", ["FAQ-002", "FAQ-003", "FAQ-004", "FAQ-005"])
def test_detail_hides_unpublishable_faq(client, employee, faqs, code):
    res = client.get(f"{FAQS}/{faqs[code].id}", headers=employee)

    assert res.status_code == 404
    assert error_code(res) == "FAQ_NOT_FOUND"


def test_admin_sees_draft_detail(client, admin, faqs):
    res = client.get(f"{FAQS}/{faqs['FAQ-005'].id}", headers=admin)

    assert (res.status_code, res.json()["sources"]) == (200, [])


# ---------------------------------------------------------------- FQ-03 등록

def test_create_draft_with_next_code(client, admin, faqs):
    res = client.post(FAQS, headers=admin, json={"categoryCode": "NET", "question": " VPN 인증 서버 오류 ", "answer": "재설치",
                                                 "keywords": ["VPN"], "isActive": False})

    assert res.status_code == 201
    body = res.json()
    assert (body["faqCode"], body["question"], body["isActive"]) == ("FAQ-006", "VPN 인증 서버 오류", False)
    assert body["updatedBy"]["name"] == "관리자"


def test_create_published_needs_public_source(client, admin, faqs):
    res = client.post(FAQS, headers=admin, json={"categoryCode": "NET", "question": "질문", "answer": "답변"})

    assert res.status_code == 409
    assert error_code(res) == "FAQ_SOURCE_NOT_PUBLIC"


def test_create_published_with_linked_code(client, db, admin, faqs):
    add_document(db, "IT-NET-003", links=[("1.1", ["FAQ-010"])])
    db.commit()

    res = client.post(FAQS, headers=admin, json={"faqCode": "FAQ-010", "categoryCode": "NET", "question": "질문",
                                                 "answer": "답변"})

    assert (res.status_code, res.json()["isActive"]) == (201, True)


def test_create_duplicate_code(client, admin, faqs):
    res = client.post(FAQS, headers=admin, json={"faqCode": "FAQ-001", "categoryCode": "ACC", "question": "질문",
                                                 "answer": "답변"})

    assert res.status_code == 409
    assert error_code(res) == "FAQ_CODE_DUPLICATE"
    assert res.json()["error"]["details"][0]["field"] == "faqCode"


@pytest.mark.parametrize("body, field, reason", [
    ({"categoryCode": "XXX"}, "categoryCode", "NOT_FOUND"),
    ({"faqCode": "Q-1"}, "faqCode", "INVALID_FORMAT"),
    ({"question": "가" * 501}, "question", "TOO_LONG"),
    ({"keywords": ["가" * 31]}, "keywords[0]", "TOO_LONG"),
    ({"keywords": [f"k{i}" for i in range(21)]}, "keywords", "TOO_LONG"),
])
def test_create_validation(client, admin, faqs, body, field, reason):
    res = client.post(FAQS, headers=admin, json={"categoryCode": "ACC", "question": "질문", "answer": "답변",
                                                 "isActive": False} | body)

    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["field"], detail["reason"]) == (field, reason)


def test_create_admin_only(client, employee, faqs):
    res = client.post(FAQS, headers=employee, json={"categoryCode": "ACC", "question": "질문", "answer": "답변"})

    assert res.status_code == 403


# ---------------------------------------------------------------- FQ-04 수정

def test_update_fields(client, db, admin, faqs):
    res = client.patch(f"{FAQS}/{faqs['FAQ-001'].id}", headers=admin, json={"answer": "10분 뒤 풀립니다.", "keywords": []})

    assert res.status_code == 200
    body = res.json()
    assert (body["answer"], body["keywords"], body["question"]) == ("10분 뒤 풀립니다.", [], "비밀번호를 5회 틀려서 계정이 잠겼어요.")
    assert body["updatedAt"] is not None and body["updatedBy"]["name"] == "관리자"


def test_publish_draft_without_source(client, admin, faqs):
    res = client.patch(f"{FAQS}/{faqs['FAQ-005'].id}", headers=admin, json={"isActive": True})

    assert error_code(res) == "FAQ_SOURCE_NOT_PUBLIC"


def test_unpublish_restricted_faq(client, db, admin, faqs):
    res = client.patch(f"{FAQS}/{faqs['FAQ-002'].id}", headers=admin, json={"isActive": False})

    assert (res.status_code, res.json()["isActive"]) == (200, False)


def test_edit_published_faq_that_lost_public_source(client, admin, faqs):
    res = client.patch(f"{FAQS}/{faqs['FAQ-002'].id}", headers=admin, json={"question": "수정"})

    assert error_code(res) == "FAQ_SOURCE_NOT_PUBLIC"


@pytest.mark.parametrize("body, field, reason", [
    ({"faqCode": "FAQ-099"}, "faqCode", "NOT_ALLOWED"),
    ({"categoryCode": "XXX"}, "categoryCode", "NOT_FOUND"),
    ({"answer": "가" * 4001}, "answer", "TOO_LONG"),
])
def test_update_validation(client, admin, faqs, body, field, reason):
    res = client.patch(f"{FAQS}/{faqs['FAQ-001'].id}", headers=admin, json=body)

    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["field"], detail["reason"]) == (field, reason)


def test_update_missing_faq(client, admin, faqs):
    assert error_code(client.patch(f"{FAQS}/999", headers=admin, json={"answer": "x"})) == "FAQ_NOT_FOUND"


# ---------------------------------------------------------------- FQ-05 삭제

def test_delete_faq(client, db, admin, faqs):
    faq_id = faqs["FAQ-005"].id

    res = client.delete(f"{FAQS}/{faq_id}", headers=admin)

    assert res.status_code == 204
    assert db.get(Faq, faq_id) is None
    log = db.scalar(select(AuditLog))
    assert (log.event_type, log.target_type, log.target_id, log.result) == ("FAQ_DELETE", "faq", faq_id, "FAQ-005")


def test_delete_missing_or_by_employee(client, admin, employee, faqs):
    assert error_code(client.delete(f"{FAQS}/999", headers=admin)) == "FAQ_NOT_FOUND"
    assert client.delete(f"{FAQS}/{faqs['FAQ-001'].id}", headers=employee).status_code == 403
