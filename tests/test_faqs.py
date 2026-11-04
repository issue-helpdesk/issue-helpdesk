"""FAQ API (FQ-01~05) — SQLite 메모리 DB. 게시 조건은 현행 청크의 meta.faq_ids 와 직접 지정한 문서로 판단한다."""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import AuditLog, Category, DocumentChunk, DocumentVersion, Faq, FaqSourceDocument, KnowledgeDocument
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_inquiries import create_sqlite_tables

FAQS = "/api/v1/faqs"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ["categories", "faqs", "knowledge_documents", "document_versions",
                                           "document_chunks", "faq_source_documents"])
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


# ---------------------------------------------------------------- 출처 직접 지정 (R-41·R-35)

def direct_ids(db, faq_id):
    db.expire_all()
    return sorted(db.scalars(select(FaqSourceDocument.document_id).where(FaqSourceDocument.faq_id == faq_id)))


@pytest.fixture
def guide(db, faqs):
    document = add_document(db, "IT-SW-001")
    db.commit()
    return document


NEW_FAQ = {"categoryCode": "ACC", "question": "질문", "answer": "답변"}


def test_create_published_with_source_document(client, db, admin, employee, guide):
    """새 FAQ 도 등록과 동시에 게시까지 이어지고, 직원에게 출처와 함께 보인다."""
    res = client.post(FAQS, json={**NEW_FAQ, "sourceDocumentIds": [guide.id, guide.id]}, headers=admin)
    assert res.status_code == 201
    faq_id = res.json()["id"]
    assert direct_ids(db, faq_id) == [guide.id]

    assert res.json()["faqCode"] in codes(client.get(FAQS, headers=employee))
    assert client.get(f"{FAQS}/{faq_id}", headers=employee).json()["sources"] == [
        {"documentId": guide.id, "docCode": "IT-SW-001", "title": "IT-SW-001 가이드", "version": "v1.0",
         "location": None, "excerpt": None},
    ]


@pytest.mark.parametrize("kwargs", [
    {"view_scope": "AGENT"},
    {"is_current": False},
    {"is_active": False},
    {"doc_type": "MANUAL"},
])
def test_source_must_be_public_current_guide(client, db, admin, faqs, kwargs):
    document = add_document(db, "IT-BAD-001", **kwargs)
    db.commit()
    before = db.scalar(select(func.count()).select_from(Faq))

    for body in ({**NEW_FAQ, "sourceDocumentIds": [document.id]}, {**NEW_FAQ, "isActive": False, "sourceDocumentIds": [document.id]}):
        res = client.post(FAQS, json=body, headers=admin)
        assert res.status_code == 422
        detail = res.json()["error"]["details"][0]
        assert (detail["field"], detail["reason"], detail["value"]) == ("sourceDocumentIds", "NOT_PUBLIC_GUIDE", [document.id])
    assert db.scalar(select(func.count()).select_from(Faq)) == before


def test_source_document_not_found(client, admin, faqs):
    assert client.post(FAQS, json={**NEW_FAQ, "sourceDocumentIds": [9999]}, headers=admin).status_code == 422


def test_update_replaces_sources_only_when_sent(client, db, admin, faqs, guide):
    other = add_document(db, "IT-SW-002")
    db.commit()
    draft = faqs["FAQ-005"].id
    url = f"{FAQS}/{draft}"

    assert client.patch(url, json={"sourceDocumentIds": [guide.id]}, headers=admin).status_code == 200
    assert direct_ids(db, draft) == [guide.id]
    assert client.patch(url, json={"answer": "새 답변"}, headers=admin).status_code == 200
    assert direct_ids(db, draft) == [guide.id]
    assert client.patch(url, json={"sourceDocumentIds": [other.id]}, headers=admin).status_code == 200
    assert direct_ids(db, draft) == [other.id]
    assert client.patch(url, json={"sourceDocumentIds": []}, headers=admin).status_code == 200
    assert direct_ids(db, draft) == []


def test_publish_draft_after_linking_source(client, db, admin, faqs, guide):
    url = f"{FAQS}/{faqs['FAQ-005'].id}"
    res = client.patch(url, json={"isActive": True, "sourceDocumentIds": [guide.id]}, headers=admin)
    assert res.status_code == 200 and res.json()["isActive"] is True


def test_removing_last_source_of_published_faq_is_rejected(client, db, admin, faqs, guide):
    """거절되면 연결도 바뀌지 않는다."""
    res = client.post(FAQS, json={**NEW_FAQ, "sourceDocumentIds": [guide.id]}, headers=admin)
    faq_id = res.json()["id"]

    res = client.patch(f"{FAQS}/{faq_id}", json={"sourceDocumentIds": []}, headers=admin)

    assert error_code(res) == "FAQ_SOURCE_NOT_PUBLIC" and res.status_code == 409
    assert direct_ids(db, faq_id) == [guide.id]


def test_published_create_without_source_saves_nothing(client, db, admin, faqs):
    before = db.scalar(select(func.count()).select_from(Faq))
    assert error_code(client.post(FAQS, json=NEW_FAQ, headers=admin)) == "FAQ_SOURCE_NOT_PUBLIC"
    assert db.scalar(select(func.count()).select_from(Faq)) == before


def test_direct_source_does_not_override_restricted_link(client, db, admin, employee, faqs, guide):
    """FAQ-002 는 제한 문서에도 연결돼 있어, 공개 가이드를 직접 지정해도 게시 조건을 채우지 못한다."""
    url = f"{FAQS}/{faqs['FAQ-002'].id}"
    res = client.patch(url, json={"sourceDocumentIds": [guide.id]}, headers=admin)
    assert error_code(res) == "FAQ_SOURCE_NOT_PUBLIC"
    assert "FAQ-002" not in codes(client.get(FAQS, headers=employee))


def test_direct_source_lost_after_document_narrowed_hides_faq(client, db, admin, employee, guide):
    """문서 변경 API 를 거치지 않고 범위가 좁아져도 직원 조회는 제한 문서 연결을 보고 숨긴다."""
    res = client.post(FAQS, json={**NEW_FAQ, "sourceDocumentIds": [guide.id]}, headers=admin)
    body = res.json()
    version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == guide.id))
    version.view_scope = "AGENT"
    db.commit()

    assert body["faqCode"] not in codes(client.get(FAQS, headers=employee))
    assert client.get(f"{FAQS}/{body['id']}", headers=employee).status_code == 404


# ---------------------------------------------------------------- 출처 본문 (R-30)

def test_detail_gives_excerpt_of_linked_chunks(client, db, employee, faqs):
    document = add_document(db, "IT-SW-003", links=[("Q1", ["FAQ-001"]), ("Q1", ["FAQ-001"]), ("Q2", ["FAQ-009"])])
    db.flush()
    chunks = list(db.scalars(select(DocumentChunk).join(DocumentVersion).where(DocumentVersion.document_id == document.id)
                             .order_by(DocumentChunk.seq)))
    chunks[0].content, chunks[1].content, chunks[2].content = "앞 조각", "뒤 조각", "다른 FAQ 본문"
    db.commit()

    sources = client.get(f"{FAQS}/{faqs['FAQ-001'].id}", headers=employee).json()["sources"]

    assert [s["excerpt"] for s in sources if s["docCode"] == "IT-SW-003"] == ["앞 조각\n뒤 조각"]


def test_excerpt_of_restricted_document_stays_in_scope():
    """열람 범위 밖 문서는 출처째로 빠지므로 본문도 나오지 않는다."""
    from app.repositories.faq import FaqLink
    from app.services.faq import sources_of

    def link(scope, text):
        return FaqLink(("FAQ-001",), "GUIDE", scope, 1, f"DOC-{scope}", "제목", "v1.0", scope, text)

    links = [link("ALL", "공개 본문"), link("ADMIN", "관리자 본문")]

    assert [s.excerpt for s in sources_of("FAQ-001", links, ("ALL",))] == ["공개 본문"]
    assert [s.excerpt for s in sources_of("FAQ-001", links, ("ALL", "AGENT", "ADMIN"))] == ["공개 본문", "관리자 본문"]


def test_direct_source_hidden_when_document_has_located_source(client, db, admin, faqs):
    """같은 문서에 위치를 아는 출처가 있으면 문서 단위 연결을 또 내지 않는다."""
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.doc_code == "IT-ACC-001"))
    faq = faqs["FAQ-001"]
    db.add(FaqSourceDocument(faq_id=faq.id, document_id=document.id))
    db.commit()

    sources = client.get(f"{FAQS}/{faq.id}", headers=admin).json()["sources"]

    assert [s["location"] for s in sources] == ["FAQ Q1", "3.1"]


def test_list_does_not_read_chunk_body(db, faqs):
    from app.repositories.faq import FaqRepository

    assert {link.excerpt for link in FaqRepository(db).links()} == {None}
    assert {link.excerpt for link in FaqRepository(db).links(with_excerpt=True) if link.location} == {"본문"}
