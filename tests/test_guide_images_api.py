"""가이드 그림 API (DC-11)와 출처 응답의 images — SQLite 메모리 DB. 파일은 임시 폴더에 둔다."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Category, DocumentChunk, DocumentVersion, Faq, KnowledgeDocument, Message, MessageSource
from app.services import guide_image
from app.utils import datetime_utils
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_inquiries import INQUIRY_TABLES, create_sqlite_tables

IMAGES = "/api/v1/guide-images"
PNG = b"\x89PNG\r\n\x1a\nfake"
KEY = "SW/sw001_home.png"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, list(dict.fromkeys(INQUIRY_TABLES + ["faqs", "faq_source_documents"])))
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def image_dir(tmp_path, monkeypatch):
    (tmp_path / "SW").mkdir()
    (tmp_path / "SW" / "sw001_home.png").write_bytes(PNG)
    (tmp_path / "SW" / "sw001_other.jpg").write_bytes(b"jpg")
    (tmp_path / "SW" / "unused.png").write_bytes(PNG)
    (tmp_path / "index.csv").write_text("이름표")
    (tmp_path.parent / "secret.png").write_bytes(PNG)
    monkeypatch.setattr(guide_image, "IMAGE_DIR", tmp_path)
    return tmp_path


def image(key=KEY, caption="그림 1. 포털 홈"):
    return {"key": key, "caption": caption}


def add_chunk(db, doc_code="IT-SW-001", scope="ALL", images=(image(),), is_active=True, status="DONE", faq_ids=(), location="3.1", seq=1):
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.doc_code == doc_code))
    if document is None:
        document = KnowledgeDocument(doc_code=doc_code, doc_type="GUIDE", title=doc_code, is_active=is_active)
        db.add(document)
        db.flush()
    version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
    if version is None:
        version = DocumentVersion(document_id=document.id, version="v1.0", view_scope=scope, transfer_policy="ALLOWED",
                                  is_current=status == "DONE", ingest_status=status)
        db.add(version)
        db.flush()
    chunk = DocumentChunk(version_id=version.id, location=location, content=f"[그림] {seq}", seq=seq, unit_key=f"u{location}", part=seq,
                          chunk_type="ITEM", meta={"images": list(images), "faq_ids": list(faq_ids)})
    db.add(chunk)
    db.commit()
    return chunk


@pytest.fixture
def employee(client, db):
    add_user(db, "E0001")
    return bearer(login(client, "E0001"))


@pytest.fixture
def agent(client, db):
    add_user(db, "G0001", service_role="AGENT")
    return bearer(login(client, "G0001"))


@pytest.fixture
def admin(client, db):
    add_user(db, "A0001", service_role="ADMIN")
    return bearer(login(client, "A0001"))


def test_employee_gets_image_of_public_guide(client, db, employee):
    add_chunk(db)

    res = client.get(f"{IMAGES}/{KEY}", headers=employee)

    assert res.status_code == 200 and res.content == PNG
    assert res.headers["content-type"] == "image/png"
    assert res.headers["cache-control"] == "private, max-age=3600"


def test_image_needs_login(client, db):
    add_chunk(db)
    assert client.get(f"{IMAGES}/{KEY}").status_code == 401


@pytest.mark.parametrize("scope, headers, status", [
    ("AGENT", "employee", 404), ("AGENT", "agent", 200), ("AGENT", "admin", 200),
    ("ADMIN", "agent", 404), ("ADMIN", "admin", 200),
])
def test_image_follows_view_scope(client, db, request, scope, headers, status):
    add_chunk(db, scope=scope)
    assert client.get(f"{IMAGES}/{KEY}", headers=request.getfixturevalue(headers)).status_code == status


def test_image_used_by_public_and_restricted_documents_is_visible(client, db, employee):
    add_chunk(db, "IT-SW-001-M", scope="AGENT")
    add_chunk(db, "IT-SW-001", scope="ALL")
    assert client.get(f"{IMAGES}/{KEY}", headers=employee).status_code == 200


@pytest.mark.parametrize("kwargs", [{"is_active": False}, {"status": "FAILED"}, {"status": "PENDING"}])
def test_image_of_unusable_document_is_hidden(client, db, employee, kwargs):
    add_chunk(db, **kwargs)
    assert client.get(f"{IMAGES}/{KEY}", headers=employee).status_code == 404


def test_file_no_chunk_uses_is_hidden(client, db, employee):
    add_chunk(db)
    res = client.get(f"{IMAGES}/SW/unused.png", headers=employee)
    assert (res.status_code, error_code(res)) == (404, "GUIDE_IMAGE_NOT_FOUND")


def test_key_must_match_exactly(client, db, employee):
    """글자가 이름표 일부에만 들어 있는 청크로는 권한을 얻지 못한다."""
    add_chunk(db, images=[image("SW/sw001_home.png.bak")])
    assert client.get(f"{IMAGES}/{KEY}", headers=employee).status_code == 404


def test_key_in_other_meta_field_gives_no_access(client, db, employee):
    chunk = add_chunk(db, images=[])
    chunk.meta = {"images": [], "note": KEY}
    db.commit()
    assert client.get(f"{IMAGES}/{KEY}", headers=employee).status_code == 404


@pytest.mark.parametrize("path", [
    "SW/secret.gif", "sw/sw001_home.png", "SW/.hidden.png", "SW/index.csv", "..%2Fsecret.png", "SW/..%2F..%2Fsecret.png",
])
def test_bad_key_is_rejected(client, db, employee, path):
    add_chunk(db, images=[image("SW/../../secret.png")])
    assert client.get(f"{IMAGES}/{path}", headers=employee).status_code == 404


def test_listed_file_missing_on_disk(client, db, employee):
    add_chunk(db, images=[image("SW/gone.png")])
    assert client.get(f"{IMAGES}/SW/gone.png", headers=employee).status_code == 404


def test_every_key_format_in_dataset_is_accepted():
    import csv

    from app.core.config import ROOT
    with open(ROOT / "dataset" / "guide_images" / "index.csv", encoding="utf-8-sig") as f:
        keys = [row["이름표"] for row in csv.DictReader(f)]
    assert keys and all(guide_image.KEY_RE.fullmatch(key) for key in keys)


# ---------------------------------------------------------------- FAQ 출처

def test_faq_source_gives_images_of_linked_chunks(client, db, employee):
    db.add(Category(code="SW", name="SW"))
    faq = Faq(faq_code="FAQ-001", category_code="SW", question="질문", answer="답변")
    db.add(faq)
    db.commit()
    other = image("SW/sw001_other.jpg", "그림 2. 목록")
    add_chunk(db, faq_ids=["FAQ-001"], images=[image()], seq=1)
    add_chunk(db, faq_ids=["FAQ-001"], images=[other, image()], seq=2)
    add_chunk(db, faq_ids=["FAQ-002"], images=[image("SW/unused.png")], location="3.2", seq=3)

    source = client.get(f"/api/v1/faqs/{faq.id}", headers=employee).json()["sources"][0]

    assert source["images"] == [image(), other]


# ---------------------------------------------------------------- 채팅 출처

@pytest.fixture
def ai_message(db, employee):
    from app.models import ChatSession, Inquiry, User
    owner = db.scalar(select(User).where(User.employee_no == "E0001"))
    inquiry = Inquiry(user_id=owner.id, status="IN_PROGRESS", updated_at=datetime_utils.now())
    db.add(inquiry)
    db.flush()
    session = ChatSession(inquiry_id=inquiry.id)
    db.add(session)
    db.flush()
    message = Message(session_id=session.id, seq=1, sender="AI", content="답변")
    db.add(message)
    db.commit()
    return inquiry, message


def add_source(db, message, chunk, doc_code="IT-SW-001", location="3.1", rank=1):
    db.add(MessageSource(message_id=message.id, source_kind="DOCUMENT", chunk_id=chunk.id if chunk else None, doc_code=doc_code,
                         version="v1.0", location=location, excerpt="[그림] 그림 1. 포털 홈", rank=rank))
    db.commit()


def message_sources(client, inquiry, headers):
    return client.get(f"/api/v1/inquiries/{inquiry.id}/messages", headers=headers).json()["items"][0]["sources"]


def test_chat_source_gives_images_of_whole_unit(client, db, employee, ai_message):
    """같은 위치의 조각은 한 항목으로 합쳐지고 단위 전체의 그림을 준다 (R-44). 다른 위치의 그림은 섞지 않는다."""
    inquiry, message = ai_message
    other = image("SW/sw001_other.jpg", "그림 2. 목록")
    add_source(db, message, add_chunk(db, images=[image()], seq=1))
    add_source(db, message, add_chunk(db, images=[other], seq=2))
    add_source(db, message, add_chunk(db, images=[image("SW/unused.png")], location="3.2", seq=3), location="3.2", rank=2)

    sources = message_sources(client, inquiry, employee)

    assert [s["images"] for s in sources] == [[image(), other], [image("SW/unused.png")]]


def test_chat_source_without_chunk_has_no_images(client, db, employee, ai_message):
    """문서를 다시 적재해 청크가 사라진 옛 출처는 그림 없이 본문만 준다."""
    inquiry, message = ai_message
    add_chunk(db)
    add_source(db, message, None)
    assert message_sources(client, inquiry, employee)[0]["images"] == []


def test_chat_source_outside_scope_gives_no_images(client, db, employee, admin, ai_message):
    inquiry, message = ai_message
    add_source(db, message, add_chunk(db, "IT-SW-001-M", scope="AGENT"), doc_code="IT-SW-001-M")

    assert message_sources(client, inquiry, employee) == []
    assert message_sources(client, inquiry, admin)[0]["images"] == [image()]
