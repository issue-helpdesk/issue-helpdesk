"""문서 API (DC-01~09). SQLite 메모리 DB 만 쓰고, 적재는 부르는지만 본다."""
import importlib.util
import io
import os
import time
import zipfile

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
from app.services import document_file
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
    monkeypatch.setattr(document_file, "ROOT", tmp_path)
    monkeypatch.setattr(document_file, "STORAGE_DIR", tmp_path / "storage" / "documents")
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


def set_active(client, headers, document_id, value):
    return client.patch(f"{DOCS}/{document_id}", json={"isActive": value}, headers=headers)


def test_deactivate_and_activate(client, db, users):
    document, _ = add_doc(db)

    assert set_active(client, users["admin"], document.id, False).json()["isActive"] is False
    assert set_active(client, users["admin"], document.id, False).status_code == 200     # 다시 불러도 200, 기록은 한 번
    assert document.is_active is False
    assert client.get(f"{DOCS}/{document.id}", headers=users["employee"]).status_code == 404
    assert audit_events(db) == [("DOCUMENT_DEACTIVATE", "IT-NET-001")]

    assert set_active(client, users["admin"], document.id, True).json()["isActive"] is True
    assert audit_events(db)[-1] == ("DOCUMENT_ACTIVATE", "IT-NET-001")


def test_deactivate_permissions(client, db, users):
    document, _ = add_doc(db)

    assert set_active(client, users["agent"], document.id, False).status_code == 403
    assert error_code(set_active(client, users["admin"], 999, False)) == "DOCUMENT_NOT_FOUND"


def test_no_delete_api(client, db, users):
    document, _ = add_doc(db)

    assert client.delete(f"{DOCS}/{document.id}", headers=users["admin"]).status_code == 405


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


def office_file(*members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member in members:
            archive.writestr(member, "x")
    return buffer.getvalue()


@pytest.mark.parametrize("name, content", [
    ("fake.pdf", b"this is not a pdf at all"),
    ("fake.docx", b"plain text"),
    ("fake.pptx", b"plain text"),
    ("other.zip.docx", office_file("hello.txt")),               # zip 이지만 Word 문서가 아니다
    ("slides.docx", office_file("ppt/presentation.xml")),       # 확장자와 내용이 다르다
    ("words.pptx", office_file("word/document.xml")),
    ("old.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 encrypted"),
    ("empty.md", b""),
    ("binary.md", b"MZ\x90\x00\x03"),
    ("binary.txt", b"\x00\x01\x02"),
])
def test_upload_rejects_wrong_content_before_saving(client, db, users, submitted, storage, name, content):
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, name=name, content=content)

    assert (res.status_code, error_code(res)) == (415, "DOCUMENT_FILE_FORMAT_UNSUPPORTED")
    assert res.json()["error"]["details"][0]["field"] == "file"
    assert submitted == []
    assert list((storage / str(document.id)).iterdir()) == []       # 임시 파일도 남지 않는다


def test_upload_rejection_message_explains_reason(client, db, users, submitted, storage):
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, name="empty.md", content=b"")

    assert res.json()["error"]["details"][0]["message"] == "빈 파일입니다."


@pytest.mark.parametrize("name, content", [
    ("korean.md", "# 안내".encode("utf-8")),
    ("bom.txt", b"\xef\xbb\xbf# hi"),
    ("old.txt", "안내".encode("cp949")),
    ("real.docx", office_file("word/document.xml")),
    ("real.pptx", office_file("ppt/presentation.xml")),
])
def test_upload_accepts_valid_content(client, db, users, submitted, storage, name, content):
    document, _ = add_doc(db)

    assert upload(client, users["admin"], document.id, name=name, content=content).status_code == 202


def test_same_file_is_rejected_everywhere(client, db, users, submitted, storage):
    first, _ = add_doc(db)
    second, _ = add_doc(db, "IT-NET-002")
    saved = upload(client, users["admin"], first.id, content=b"# same")

    res = upload(client, users["admin"], second.id, content=b"# same", version="v9")

    assert (res.status_code, error_code(res)) == (409, "DOCUMENT_FILE_DUPLICATE")
    assert res.json()["error"]["details"][0]["value"] == {
        "documentId": first.id, "docCode": "IT-NET-001", "versionId": saved.json()["id"], "version": "v2", "ingestStatus": "PENDING",
    }
    assert len(submitted) == 1
    assert not (storage / str(second.id)).exists() or list((storage / str(second.id)).iterdir()) == []


def test_different_file_is_allowed(client, db, users, submitted, storage):
    document, _ = add_doc(db)
    upload(client, users["admin"], document.id, content=b"# one", version="v2")

    assert upload(client, users["admin"], document.id, content=b"# two", version="v3").status_code == 202


def test_duplicate_checked_at_commit_too(client, db, users, submitted, storage, monkeypatch):
    """동시에 올라와 앞의 검사를 지나도 DB 가 막고 파일을 남기지 않는다."""
    from app.services.document import DocumentService

    first, _ = add_doc(db)
    upload(client, users["admin"], first.id, content=b"# same", version="v2")
    real, calls = DocumentService.check_duplicate, []

    def miss_first(self, sha256):
        calls.append(1)
        if len(calls) > 1:
            real(self, sha256)
    monkeypatch.setattr(DocumentService, "check_duplicate", miss_first)

    res = upload(client, users["admin"], first.id, content=b"# same", version="v3")

    assert error_code(res) == "DOCUMENT_FILE_DUPLICATE"
    assert len(list((storage / str(first.id)).iterdir())) == 1


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


# ------------------------------------------------------------------ DC-10


def failed_version(client, db, users, submitted, content=b"# broken"):
    document, _ = add_doc(db)
    body = upload(client, users["admin"], document.id, content=content).json()
    row = db.get(DocumentVersion, body["id"])
    row.ingest_status, row.ingest_error = "FAILED", "파서 오류"
    db.commit()
    submitted.clear()
    return document, row


def retry(client, headers, document, row, name=None, content=None):
    files = {"file": (name, io.BytesIO(content))} if name else None
    return client.post(f"{DOCS}/{document.id}/versions/{row.id}/retry", headers=headers, files=files)


def test_retry_with_same_file(client, db, users, submitted, storage):
    document, row = failed_version(client, db, users, submitted)
    path = row.file_path

    res = retry(client, users["admin"], document, row)

    assert res.status_code == 202
    assert (res.json()["ingestStatus"], res.json()["ingestError"]) == ("PENDING", None)
    assert submitted == [row.id]
    db.expire_all()
    assert row.file_path == path
    assert audit_events(db)[-1] == ("DOCUMENT_VERSION_RETRY", "v2 같은 파일")


def test_retry_replaces_file_and_removes_old(client, db, users, submitted, storage):
    document, row = failed_version(client, db, users, submitted)
    old_path = storage.parent.parent / row.file_path

    res = retry(client, users["admin"], document, row, name="fixed.txt", content=b"# fixed")

    assert res.status_code == 202
    assert res.json()["fileFormat"] == "TEXT"
    db.expire_all()
    assert (storage.parent.parent / row.file_path).read_bytes() == b"# fixed"
    assert not old_path.exists()
    assert audit_events(db)[-1] == ("DOCUMENT_VERSION_RETRY", "v2 파일 교체")
    assert submitted == [row.id]


def test_retry_same_content_does_not_replace(client, db, users, submitted, storage):
    document, row = failed_version(client, db, users, submitted, content=b"# same")
    path = row.file_path

    assert retry(client, users["admin"], document, row, name="again.md", content=b"# same").status_code == 202

    db.expire_all()
    assert row.file_path == path
    assert len(list((storage / str(document.id)).iterdir())) == 1


def test_retry_keeps_dataset_original(client, db, users, submitted, storage):
    """가이드 원본처럼 업로드 폴더 밖의 파일은 교체해도 지우지 않는다."""
    document, row = failed_version(client, db, users, submitted)
    original = storage.parent.parent / "dataset" / "guide.md"
    original.parent.mkdir(parents=True)
    original.write_text("# original")
    row.file_path = "dataset/guide.md"
    db.commit()

    retry(client, users["admin"], document, row, name="fixed.md", content=b"# fixed")

    assert original.exists()


@pytest.mark.parametrize("status", ["PENDING", "DONE"])
def test_retry_only_failed(client, db, users, submitted, storage, status):
    document, row = failed_version(client, db, users, submitted)
    row.ingest_status = status
    db.commit()

    res = retry(client, users["admin"], document, row)

    assert (res.status_code, error_code(res)) == (409, "DOCUMENT_VERSION_NOT_RETRYABLE")
    assert res.json()["error"]["details"][0]["value"] == status
    assert submitted == []


def test_retry_rejects_bad_or_duplicate_file(client, db, users, submitted, storage):
    document, row = failed_version(client, db, users, submitted)
    upload(client, users["admin"], document.id, content=b"# other", version="v3")
    submitted.clear()
    before = sorted(p.name for p in (storage / str(document.id)).iterdir())

    fake = retry(client, users["admin"], document, row, name="fake.pdf", content=b"nope")
    duplicate = retry(client, users["admin"], document, row, name="dup.md", content=b"# other")

    assert error_code(fake) == "DOCUMENT_FILE_FORMAT_UNSUPPORTED"
    assert error_code(duplicate) == "DOCUMENT_FILE_DUPLICATE"
    db.expire_all()
    assert row.ingest_status == "FAILED"
    assert submitted == []
    assert sorted(p.name for p in (storage / str(document.id)).iterdir()) == before


def test_retry_not_found_and_permissions(client, db, users, submitted, storage):
    document, row = failed_version(client, db, users, submitted)
    other, _ = add_doc(db, "IT-NET-002")

    assert retry(client, users["agent"], document, row).status_code == 403
    assert error_code(retry(client, users["admin"], other, row)) == "DOCUMENT_VERSION_NOT_FOUND"
    assert error_code(client.post(f"{DOCS}/999/versions/1/retry", headers=users["admin"])) == "DOCUMENT_NOT_FOUND"


# ------------------------------------------------------------------ 임시 파일 정리


def touch(path, age_hours=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    mtime = time.time() - age_hours * 3600
    os.utime(path, (mtime, mtime))


def test_cleanup_removes_only_old_temp_files(storage):
    old, recent, stored = storage / "1" / "a.part", storage / "1" / "b.part", storage / "1" / "c.pdf"
    touch(old, age_hours=2)
    touch(recent)
    touch(stored, age_hours=2)

    assert document_file.cleanup_temp_files() == 1

    assert not old.exists() and recent.exists() and stored.exists()


def test_cleanup_logs_unknown_file_without_deleting(storage, caplog):
    known, unknown = storage / "1" / "known.pdf", storage / "1" / "unknown.pdf"
    touch(known, age_hours=2)
    touch(unknown, age_hours=2)

    document_file.cleanup_temp_files(known_paths={document_file.to_stored_path(known)})

    assert known.exists() and unknown.exists()
    assert "unknown.pdf" in caplog.text and "known.pdf" not in caplog.text.replace("unknown.pdf", "")


def test_cleanup_without_folder_does_nothing(storage):
    assert document_file.cleanup_temp_files() == 0


def test_run_cleanup_survives_errors(monkeypatch):
    from app.services import document_ingest

    def boom(**_):
        raise OSError("disk")
    monkeypatch.setattr(document_ingest, "cleanup_temp_files", boom)

    document_ingest.run_cleanup()


# ------------------------------------------------------------------ 기존 행 해시 채우기


def load_backfill():
    spec = importlib.util.spec_from_file_location(
        "backfill_document_hashes", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "backfill_document_hashes.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_fills_and_reports(db, tmp_path):
    import hashlib

    backfill = load_backfill().backfill
    (tmp_path / "a.md").write_bytes(b"# a")
    (tmp_path / "same.md").write_bytes(b"# a")
    (tmp_path / "b.md").write_bytes(b"# b")
    _, (filled, duplicate, missing, no_path, done) = add_doc(db, versions=[(f"v{i}", "ALL", False) for i in range(5)])
    filled.file_path, duplicate.file_path, missing.file_path, no_path.file_path = "a.md", "same.md", "gone.md", None
    done.file_path, done.file_sha256 = "b.md", "already"
    db.commit()

    dry = backfill(db, tmp_path, dry_run=True)

    assert dry.filled == [filled.id] and filled.file_sha256 is None

    report = backfill(db, tmp_path)
    db.commit()

    assert report.filled == [filled.id]
    assert report.duplicates == [(duplicate.id, filled.id)]
    assert report.missing == [missing.id, no_path.id]
    assert filled.file_sha256 == hashlib.sha256(b"# a").hexdigest()
    assert (duplicate.file_sha256, done.file_sha256) == (None, "already")
    assert backfill(db, tmp_path).filled == []          # 다시 돌려도 된다


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


# ------------------------------------------------------------------ 비활성 문서 목록


def test_list_include_inactive(client, users, scoped):
    res = client.get(DOCS, headers=users["admin"], params={"includeInactive": "true"})

    assert ids(res) == ["IT-NET-001", "IT-NET-002", "IT-NET-003", "IT-NET-004", "IT-NET-005"]
    assert res.json()["items"][4]["isActive"] is False


def test_list_is_active_wins_over_include_inactive(client, users, scoped):
    res = client.get(DOCS, headers=users["admin"], params={"includeInactive": "true", "isActive": "false"})

    assert ids(res) == ["IT-NET-005"]


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_list_include_inactive_admin_only(client, users, scoped, who):
    assert client.get(DOCS, headers=users[who], params={"includeInactive": "true"}).status_code == 403


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

    set_active(client, users["admin"], document.id, False)

    db.expire_all()
    assert faq.is_active is False


def test_faq_with_other_public_source_stays(client, db, users):
    document, _ = add_doc(db, faqs=("FAQ-001",))
    add_doc(db, "IT-NET-002", faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")

    set_active(client, users["admin"], document.id, False)

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


def test_activating_does_not_republish(client, db, users):
    document, _ = add_doc(db, faqs=("FAQ-001",))
    faq = add_faq(db, "FAQ-001")
    set_active(client, users["admin"], document.id, False)

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


def test_size_limit_covers_retry_path(client, db, users, submitted, storage, monkeypatch):
    document, row = failed_version(client, db, users, submitted)
    monkeypatch.setattr(file_constants, "MAX_DOCUMENT_FILE_MB", 1)

    res = retry(client, users["admin"], document, row, name="big.md", content=b"x" * (3 * 1024 * 1024))

    assert (res.status_code, error_code(res)) == (413, "DOCUMENT_FILE_TOO_LARGE")


def test_upload_accepts_real_pdf(client, db, users, submitted, storage):
    from pypdf import PdfWriter

    writer, buffer = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    document, _ = add_doc(db)

    assert upload(client, users["admin"], document.id, name="real.pdf", content=buffer.getvalue()).status_code == 202


def test_upload_rejects_password_pdf(client, db, users, submitted, storage):
    from pypdf import PdfWriter

    writer, buffer = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret", algorithm="RC4-128")
    writer.write(buffer)
    document, _ = add_doc(db)

    res = upload(client, users["admin"], document.id, name="locked.pdf", content=buffer.getvalue())

    assert error_code(res) == "DOCUMENT_FILE_FORMAT_UNSUPPORTED"
    assert "암호" in res.json()["error"]["details"][0]["message"]
