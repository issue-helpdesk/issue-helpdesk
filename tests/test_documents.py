"""문서 API (DC-01~09). SQLite 메모리 DB 만 쓰고, 적재는 부르는지만 본다."""
import io

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.constants import file as file_constants
from app.main import app
from app.models import (
    AuditLog,
    Category,
    DocumentChunk,
    DocumentVersion,
    Faq,
    KnowledgeDocument,
    SupportGroup,
)
from app.services import document as document_service
from app.services.document_ingest import ingest_submitter
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401
from test_inquiries import create_sqlite_tables

DOCS = "/api/v1/documents"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ["categories", "faqs", "knowledge_documents", "document_versions",
                                           "document_chunks"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def users(client, db):
    add_user(db, "E0001")
    add_user(db, "E0002", service_role="AGENT")
    add_user(db, "E0009", service_role="ADMIN")
    db.add(Category(code="NET", name="VPN·네트워크"))
    db.commit()
    return {name: bearer(login(client, no)) for name, no in (("employee", "E0001"), ("agent", "E0002"), ("admin", "E0009"))}


@pytest.fixture
def submitted():
    calls = []
    app.dependency_overrides[ingest_submitter] = lambda: calls.append
    yield calls
    app.dependency_overrides.pop(ingest_submitter, None)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(document_service, "ROOT", tmp_path)
    monkeypatch.setattr(document_service, "STORAGE_DIR", tmp_path / "storage" / "documents")
    return tmp_path / "storage" / "documents"


def add_doc(db, code="IT-NET-001", doc_type="GUIDE", category="NET", is_active=True, versions=(("v1", "ALL", True),), faqs=()):
    """versions: (버전, 열람 범위, 현행 여부). faqs: 각 버전 청크가 가리키는 FAQ 번호."""
    document = KnowledgeDocument(doc_code=code, doc_type=doc_type, title=f"{code} 제목", category_code=category,
                                 is_active=is_active)
    db.add(document)
    db.flush()
    rows = []
    for version, scope, current in versions:
        row = DocumentVersion(document_id=document.id, version=version, view_scope=scope, transfer_policy="ALLOWED",
                              is_current=current, ingest_status="DONE", file_format="MD")
        db.add(row)
        db.flush()
        rows.append(row)
        if faqs:
            db.add(DocumentChunk(version_id=row.id, content="본문", seq=1, unit_key="u1", chunk_type="FAQ",
                                 meta={"faq_ids": list(faqs)}))
    db.commit()
    return document, rows


def add_faq(db, code, is_active=True):
    faq = Faq(faq_code=code, category_code="NET", question=f"{code} 질문", answer="답", keywords=[], is_active=is_active)
    db.add(faq)
    db.commit()
    return faq


def ids(res):
    return [d["docCode"] for d in res.json()["items"]]


def audit_events(db):
    return [(a.event_type, a.result) for a in db.scalars(select(AuditLog).where(
        AuditLog.event_type.like("DOCUMENT%") | AuditLog.event_type.like("FAQ%")).order_by(AuditLog.id))]


def upload(client, headers, document_id, name="guide.md", content=b"# hi", version="v2", **fields):
    return client.post(f"{DOCS}/{document_id}/versions", headers=headers, files={"file": (name, io.BytesIO(content))},
                       data={"version": version, **fields})


# ------------------------------------------------------------------ DC-01·03 열람 범위


@pytest.fixture
def scoped(db):
    return {
        "all": add_doc(db, "IT-NET-001")[0],
        "agent": add_doc(db, "IT-NET-002", versions=(("v1", "AGENT", True),))[0],
        "admin": add_doc(db, "IT-NET-003", versions=(("v1", "ADMIN", True),))[0],
        "no_current": add_doc(db, "IT-NET-004", versions=(("v1", "ALL", False),))[0],
        "inactive": add_doc(db, "IT-NET-005", is_active=False)[0],
    }


@pytest.mark.parametrize("who, expected", [
    ("employee", ["IT-NET-001"]),
    ("agent", ["IT-NET-001", "IT-NET-002"]),
    ("admin", ["IT-NET-001", "IT-NET-002", "IT-NET-003", "IT-NET-004"]),
])
def test_list_by_scope(client, users, scoped, who, expected):
    assert ids(client.get(DOCS, headers=users[who])) == expected


def test_policy_fields_only_for_admin(client, users, scoped):
    employee = client.get(DOCS, headers=users["employee"]).json()["items"][0]["currentVersion"]
    admin = client.get(DOCS, headers=users["admin"]).json()["items"][0]["currentVersion"]

    assert (employee["viewScope"], employee["transferPolicy"]) == (None, None)
    assert (admin["viewScope"], admin["transferPolicy"]) == ("ALL", "ALLOWED")


@pytest.mark.parametrize("params", [{"isActive": "false"}, {"hasCurrentVersion": "true"}])
def test_admin_only_filters(client, users, scoped, params):
    res = client.get(DOCS, params=params, headers=users["employee"])

    assert (res.status_code, error_code(res)) == (403, "FORBIDDEN")


def test_admin_filters(client, users, scoped):
    assert ids(client.get(DOCS, params={"isActive": "false"}, headers=users["admin"])) == ["IT-NET-005"]
    assert ids(client.get(DOCS, params={"hasCurrentVersion": "false"}, headers=users["admin"])) == ["IT-NET-004"]


def test_search_filter_and_sort(client, db, users):
    add_doc(db, "IT-NET-001")
    add_doc(db, "IT-NET-002", doc_type="MANUAL")

    assert ids(client.get(DOCS, params={"docType": "MANUAL"}, headers=users["employee"])) == ["IT-NET-002"]
    assert ids(client.get(DOCS, params={"q": "NET-001"}, headers=users["employee"])) == ["IT-NET-001"]
    assert ids(client.get(DOCS, params={"sort": "docCode,desc"}, headers=users["employee"])) == ["IT-NET-002", "IT-NET-001"]
    assert client.get(DOCS, params={"docType": "NOPE"}, headers=users["employee"]).status_code == 422


@pytest.mark.parametrize("who, doc, expected", [
    ("employee", "all", 200), ("employee", "agent", 404), ("employee", "no_current", 404), ("employee", "inactive", 404),
    ("agent", "agent", 200), ("agent", "admin", 404),
    ("admin", "admin", 200), ("admin", "no_current", 200), ("admin", "inactive", 200),
])
def test_detail_scope(client, users, scoped, who, doc, expected):
    res = client.get(f"{DOCS}/{scoped[doc].id}", headers=users[who])

    assert res.status_code == expected
    if expected == 404:
        assert error_code(res) == "DOCUMENT_NOT_FOUND"


# ------------------------------------------------------------------ DC-02·04·05


def create(client, headers, **over):
    body = {"docCode": "IT-NET-010", "docType": "GUIDE", "title": "새 문서", "categoryCode": "NET"} | over
    return client.post(DOCS, json=body, headers=headers)


def test_create(client, users):
    res = create(client, users["admin"])

    assert res.status_code == 201
    assert res.json()["currentVersion"] is None and res.json()["category"]["name"] == "VPN·네트워크"
    assert client.post(DOCS, json={}, headers=users["agent"]).status_code == 403


def test_create_duplicate(client, users):
    create(client, users["admin"])

    assert error_code(create(client, users["admin"])) == "DOCUMENT_CODE_DUPLICATE"


@pytest.mark.parametrize("over, reason", [
    ({"categoryCode": None}, "REQUIRED"),
    ({"docType": "STANDARD"}, "NOT_ALLOWED"),
    ({"categoryCode": "NOPE"}, "NOT_FOUND"),
    ({"ownerGroupId": 999}, "NOT_FOUND"),
])
def test_create_validation(client, users, over, reason):
    res = create(client, users["admin"], **over)

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["reason"] == reason


def test_create_bad_code(client, users):
    assert create(client, users["admin"], docCode="bad").status_code == 422


def test_standard_needs_no_category(client, users):
    assert create(client, users["admin"], docCode="IT-STD-001", docType="STANDARD", categoryCode=None).status_code == 201


def test_update_only_sent_fields(client, db, users):
    document, _ = add_doc(db)
    group = SupportGroup(name="네트워크팀")
    db.add(group)
    db.commit()

    res = client.patch(f"{DOCS}/{document.id}", json={"ownerGroupId": group.id}, headers=users["admin"])

    assert res.json()["ownerGroup"]["name"] == "네트워크팀"
    assert res.json()["title"] == "IT-NET-001 제목"


@pytest.mark.parametrize("body", [{"docCode": "IT-NET-009"}, {"docType": "MANUAL"}])
def test_update_rejects_fixed_fields(client, db, users, body):
    document, _ = add_doc(db)

    res = client.patch(f"{DOCS}/{document.id}", json=body, headers=users["admin"])

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["reason"] == "NOT_ALLOWED"


def test_update_category_rule(client, db, users):
    document, _ = add_doc(db)

    res = client.patch(f"{DOCS}/{document.id}", json={"categoryCode": None}, headers=users["admin"])

    assert res.json()["error"]["details"][0]["reason"] == "REQUIRED"


def test_delete_and_restore(client, db, users):
    document, _ = add_doc(db)

    assert client.delete(f"{DOCS}/{document.id}", headers=users["admin"]).status_code == 204
    assert client.delete(f"{DOCS}/{document.id}", headers=users["admin"]).status_code == 204     # 다시 불러도 204
    assert document.is_active is False
    assert client.get(f"{DOCS}/{document.id}", headers=users["employee"]).status_code == 404
    assert audit_events(db) == [("DOCUMENT_DELETE", "IT-NET-001")]

    assert client.patch(f"{DOCS}/{document.id}", json={"isActive": True}, headers=users["admin"]).json()["isActive"] is True
    assert audit_events(db)[-1] == ("DOCUMENT_RESTORE", "IT-NET-001")


def test_delete_permissions(client, db, users):
    document, _ = add_doc(db)

    assert client.delete(f"{DOCS}/{document.id}", headers=users["agent"]).status_code == 403
    assert error_code(client.delete(f"{DOCS}/999", headers=users["admin"])) == "DOCUMENT_NOT_FOUND"


# ------------------------------------------------------------------ DC-06~08


def test_upload_saves_file_and_starts_ingest(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, name="../../evil.MD", content=b"# body", viewScope="ALL", transferPolicy="MASKED")

    assert res.status_code == 202
    body = res.json()
    assert (body["version"], body["fileFormat"], body["ingestStatus"], body["versionState"]) == ("v2", "MD", "PENDING", "DRAFT")
    assert (body["viewScope"], body["transferPolicy"], body["isCurrent"]) == ("ALL", "MASKED", False)
    assert "filePath" not in body
    assert submitted == [body["id"]]
    row = db.get(DocumentVersion, body["id"])
    assert row.file_path.startswith(f"storage/documents/{document.id}/") and "evil" not in row.file_path
    (saved,) = list((storage / str(document.id)).iterdir())
    assert saved.read_bytes() == b"# body"


def test_upload_defaults_to_narrowest_policy(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    body = upload(client, users["admin"], document.id).json()

    assert (body["viewScope"], body["transferPolicy"]) == ("ADMIN", "BLOCKED")


def test_upload_rejects_format(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, name="virus.exe")

    assert (res.status_code, error_code(res)) == (415, "DOCUMENT_FILE_FORMAT_UNSUPPORTED")
    assert submitted == [] and not storage.exists()


def test_upload_size_limit_uses_constant(client, db, users, submitted, storage, monkeypatch):
    document, _ = add_doc(db)
    monkeypatch.setattr(file_constants, "MAX_DOCUMENT_FILE_MB", 1)

    res = upload(client, users["admin"], document.id, content=b"x" * (1024 * 1024 + 1))

    assert (res.status_code, error_code(res)) == (413, "DOCUMENT_FILE_TOO_LARGE")
    assert res.json()["error"]["details"][0]["value"] == "1MB"
    assert list((storage / str(document.id)).iterdir()) == []
    assert submitted == []
    assert upload(client, users["admin"], document.id, content=b"x" * (1024 * 1024)).status_code == 202


def test_upload_over_margin_is_rejected_before_route(client, db, users, submitted, storage, monkeypatch):
    """헤더의 크기만 보고 끝낸다. 파일을 저장하지 않고 안내 형식은 같다."""
    document, _ = add_doc(db)
    monkeypatch.setattr(file_constants, "MAX_DOCUMENT_FILE_MB", 1)

    res = upload(client, users["admin"], document.id, content=b"x" * (3 * 1024 * 1024))

    assert (res.status_code, error_code(res)) == (413, "DOCUMENT_FILE_TOO_LARGE")
    assert res.json()["error"]["details"][0]["value"] == "1MB"
    assert submitted == [] and not storage.exists()


def test_upload_stops_when_size_header_is_missing(monkeypatch):
    """헤더가 없거나 작게 적혀도 넘는 순간 멈춘다. 뒤의 조각은 읽지 않는다."""
    import asyncio

    from app.core.upload_limit import UploadLimitMiddleware

    monkeypatch.setattr(file_constants, "MAX_DOCUMENT_FILE_MB", 1)
    chunks = [b"x" * (1024 * 1024)] * 5
    read, sent = [], []

    async def inner(scope, receive, send):
        try:
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break
        except Exception:                       # FastAPI 는 본문을 읽다 난 오류를 400 으로 바꾼다
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b"parse error"})
            return
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        read.append(1)
        return {"type": "http.request", "body": chunks[len(read) - 1], "more_body": len(read) < len(chunks)}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/v1/documents/1/versions", "headers": [], "query_string": b""}
    asyncio.run(UploadLimitMiddleware(inner)(scope, receive, send))

    assert len(read) == 3                       # 제한(1MB)+여유(1MB)를 넘는 세 번째 조각에서 멈춘다
    assert sent[0]["status"] == 413
    assert b"DOCUMENT_FILE_TOO_LARGE" in sent[1]["body"]


def test_size_limit_applies_only_to_upload_path(client, users, monkeypatch):
    monkeypatch.setattr(file_constants, "MAX_DOCUMENT_FILE_MB", 0)
    body = {"docCode": "IT-NET-010", "docType": "GUIDE", "title": "새 문서", "categoryCode": "NET"}

    assert client.post(DOCS, json=body, headers=users["admin"]).status_code == 201


def test_upload_duplicate_version_removes_file(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, version="v1")

    assert (res.status_code, error_code(res)) == (409, "DOCUMENT_VERSION_DUPLICATE")
    assert list((storage / str(document.id)).iterdir()) == []
    assert submitted == []


@pytest.mark.parametrize("fields", [{"viewScope": "NOPE"}, {"transferPolicy": "NOPE"}, {"version": ""}])
def test_upload_validation(client, db, users, submitted, storage, fields):
    document, _ = add_doc(db)

    assert upload(client, users["admin"], document.id, **{"version": "v2", **fields}).status_code == 422


def test_upload_permissions(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    assert upload(client, users["agent"], document.id).status_code == 403
    assert error_code(upload(client, users["admin"], 999)) == "DOCUMENT_NOT_FOUND"


def test_versions_list_and_detail(client, db, users):
    document, (old, current) = add_doc(db, versions=(("v1", "ALL", False), ("v2", "ALL", True)), faqs=("FAQ-001",))
    old.activated_at = current.registered_at
    db.commit()
    other, (other_version,) = add_doc(db, "IT-NET-002")

    res = client.get(f"{DOCS}/{document.id}/versions", headers=users["admin"])

    assert [(v["version"], v["versionState"], v["chunkCount"]) for v in res.json()["items"]] == [("v2", "CURRENT", 1), ("v1", "EXPIRED", 1)]
    assert client.get(f"{DOCS}/{document.id}/versions/{current.id}", headers=users["admin"]).json()["version"] == "v2"
    assert error_code(client.get(f"{DOCS}/{document.id}/versions/{other_version.id}", headers=users["admin"])) == "DOCUMENT_VERSION_NOT_FOUND"
    assert client.get(f"{DOCS}/{document.id}/versions", headers=users["agent"]).status_code == 403
    assert error_code(client.get(f"{DOCS}/999/versions", headers=users["admin"])) == "DOCUMENT_NOT_FOUND"


# ------------------------------------------------------------------ DC-09


def patch_version(client, headers, document, version, body):
    return client.patch(f"{DOCS}/{document.id}/versions/{version.id}", json=body, headers=headers)


def test_activate_swaps_current(client, db, users):
    document, (old, new) = add_doc(db, versions=(("v1", "ALL", True), ("v2", "ALL", False)))

    res = patch_version(client, users["admin"], document, new, {"isCurrent": True})

    assert res.json()["versionState"] == "CURRENT"
    db.expire_all()
    assert (old.is_current, new.is_current) == (False, True)
    assert new.activated_at is not None
    assert audit_events(db) == [("DOCUMENT_VERSION_ACTIVATE", "v1 → v2")]


def test_activate_keeps_first_time_and_is_idempotent(client, db, users):
    document, (current,) = add_doc(db)

    patch_version(client, users["admin"], document, current, {"isCurrent": True})

    assert audit_events(db) == []


@pytest.mark.parametrize("status", ["PENDING", "FAILED"])
def test_activate_requires_done(client, db, users, status):
    document, (old, new) = add_doc(db, versions=(("v1", "ALL", True), ("v2", "ALL", False)))
    new.ingest_status = status
    db.commit()

    res = patch_version(client, users["admin"], document, new, {"isCurrent": True})

    assert (res.status_code, error_code(res)) == (409, "DOCUMENT_VERSION_NOT_READY")
    assert res.json()["error"]["details"][0]["value"] == status
    db.expire_all()
    assert old.is_current is True


def test_is_current_false_rejected(client, db, users):
    document, (current,) = add_doc(db)

    assert patch_version(client, users["admin"], document, current, {"isCurrent": False}).status_code == 422
    assert patch_version(client, users["admin"], document, current, {"isCurrent": None}).status_code == 422


def test_policy_change_logged(client, db, users):
    document, (current,) = add_doc(db)

    res = patch_version(client, users["admin"], document, current, {"transferPolicy": "BLOCKED"})

    assert (res.json()["viewScope"], res.json()["transferPolicy"]) == ("ALL", "BLOCKED")
    assert audit_events(db) == [("DOCUMENT_POLICY_CHANGE", "v1 ALL/ALLOWED → ALL/BLOCKED")]
    patch_version(client, users["admin"], document, current, {"transferPolicy": "BLOCKED"})
    assert len(audit_events(db)) == 1           # 같은 값이면 기록하지 않는다


def test_version_of_other_document(client, db, users):
    document, _ = add_doc(db)
    _, (other,) = add_doc(db, "IT-NET-002")

    assert error_code(patch_version(client, users["admin"], document, other, {"viewScope": "ALL"})) == "DOCUMENT_VERSION_NOT_FOUND"


def test_version_patch_permissions(client, db, users):
    document, (current,) = add_doc(db)

    assert patch_version(client, users["agent"], document, current, {"viewScope": "ALL"}).status_code == 403


# ------------------------------------------------------------------ FAQ 재검사


def unpublished(db):
    return [a.result for a in db.scalars(select(AuditLog).where(AuditLog.event_type == "FAQ_AUTO_UNPUBLISH"))]


def test_narrowing_scope_unpublishes_linked_faq(client, db, users):
    document, (current,) = add_doc(db, faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")

    patch_version(client, users["admin"], document, current, {"viewScope": "AGENT"})

    db.expire_all()
    assert faq.is_active is False
    assert unpublished(db) == ["FAQ-001"]


def test_transfer_policy_does_not_touch_faq(client, db, users):
    document, (current,) = add_doc(db, faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")

    patch_version(client, users["admin"], document, current, {"transferPolicy": "BLOCKED"})

    db.expire_all()
    assert faq.is_active is True


def test_deleting_document_unpublishes_linked_faq(client, db, users):
    document, _ = add_doc(db, faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")

    client.delete(f"{DOCS}/{document.id}", headers=users["admin"])

    db.expire_all()
    assert faq.is_active is False


def test_faq_with_other_public_source_stays(client, db, users):
    document, _ = add_doc(db, faqs=("FAQ-001",))
    add_doc(db, "IT-NET-002", faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")

    client.delete(f"{DOCS}/{document.id}", headers=users["admin"])

    db.expire_all()
    assert faq.is_active is True


def test_activating_version_without_link_unpublishes(client, db, users):
    """새 현행 청크에 연결이 없으면 공개 출처가 사라진다. 이전 버전 연결로 관련 FAQ 를 찾는다."""
    document, (old, new) = add_doc(db, versions=(("v1", "ALL", True), ("v2", "ALL", False)))
    db.add(DocumentChunk(version_id=old.id, content="본문", seq=1, unit_key="u1", chunk_type="FAQ", meta={"faq_ids": ["FAQ-001"]}))
    faq = add_faq(db, "FAQ-001")

    patch_version(client, users["admin"], document, new, {"isCurrent": True})

    db.expire_all()
    assert faq.is_active is False


def test_unrelated_faq_is_not_touched(client, db, users):
    """출처가 없는 다른 FAQ 를 이 변경이 비게시로 바꾸지 않는다."""
    document, (current,) = add_doc(db, faqs=("FAQ-001",))
    add_faq(db, "FAQ-001")
    other = add_faq(db, "FAQ-040")

    patch_version(client, users["admin"], document, current, {"viewScope": "AGENT"})

    db.expire_all()
    assert other.is_active is True


def test_restoring_does_not_republish(client, db, users):
    document, _ = add_doc(db, faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")
    client.delete(f"{DOCS}/{document.id}", headers=users["admin"])

    client.patch(f"{DOCS}/{document.id}", json={"isActive": True}, headers=users["admin"])

    db.expire_all()
    assert faq.is_active is False


# ------------------------------------------------------------------ 백그라운드 적재


class FakeConn:
    def __init__(self):
        self.executed, self.committed = [], 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def commit(self):
        self.committed += 1


@pytest.fixture
def ingest_env(monkeypatch):
    from types import SimpleNamespace

    from app.services import document_ingest

    conn = FakeConn()
    monkeypatch.setattr(document_ingest, "get_settings", lambda: SimpleNamespace(dsn="postgresql://x"))
    monkeypatch.setattr(document_ingest, "connect", lambda dsn, allow_remote: conn)
    return document_ingest, conn


def test_run_ingest_calls_upload_ingest(ingest_env, monkeypatch):
    module, conn = ingest_env
    embedder, calls = object(), []
    monkeypatch.setattr(module, "get_embedder", lambda: embedder)
    monkeypatch.setattr(module, "ingest_version", lambda c, version_id, e: calls.append((c, version_id, e)))

    module.run_ingest(7)

    assert calls == [(conn, 7, embedder)]


def test_run_ingest_marks_failed_when_model_cannot_open(ingest_env, monkeypatch):
    """모델이 없어도 PENDING 으로 멈춰 있지 않고 관리자에게 사유가 보인다."""
    module, conn = ingest_env

    def no_model():
        raise FileNotFoundError("models")
    monkeypatch.setattr(module, "get_embedder", no_model)

    module.run_ingest(7)

    ((sql, params),) = conn.executed
    assert "FAILED" in sql and params[1] == 7
    assert conn.committed == 1


def test_run_ingest_survives_errors(ingest_env, monkeypatch):
    """실행기 스레드가 죽으면 다음 적재를 못 한다."""
    module, _ = ingest_env

    def boom(*_):
        raise RuntimeError("db down")
    monkeypatch.setattr(module, "connect", boom)

    module.run_ingest(7)
    module.run_resume()
