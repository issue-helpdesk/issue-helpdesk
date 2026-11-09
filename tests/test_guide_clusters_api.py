"""해결 사례 가이드화 묶음 API (GC-01~07). SQLite 메모리 DB 만 쓴다."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import AuditLog, Category, DocumentVersion, GuideCluster, KnowledgeDocument, TicketGuideState, User
from app.rag.case_guide import CaseGuideError
from app.services.document_ingest import ingest_submitter
from app.services.guide_cluster import guide_assembler, guide_rebaser
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401
from test_dashboard import add_ticket
from test_inquiries import create_sqlite_tables

API = "/api/v1/guide-clusters"
DAY = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ["categories", "inquiries", "tickets", "knowledge_documents",
                                           "document_versions", "document_chunks", "faqs", "faq_source_documents",
                                           "guide_clusters", "ticket_guide_states"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def users(client, db):
    for no, role in (("E0001", "EMPLOYEE"), ("E0002", "AGENT"), ("E0009", "ADMIN")):
        add_user(db, no, service_role=role)
    db.add_all([Category(code="NET", name="VPN·네트워크"), Category(code="SEC", name="보안")])
    db.commit()
    return {name: bearer(login(client, no)) for name, no in (("employee", "E0001"), ("agent", "E0002"), ("admin", "E0009"))}


@pytest.fixture
def guide(db):
    """IT-NET-001: v2.0 현행, v2.1 등록한 초안."""
    document = KnowledgeDocument(doc_code="IT-NET-001", doc_type="GUIDE", title="VPN 접속 장애 대응 가이드",
                                 category_code="NET", is_active=True)
    db.add(document)
    db.flush()
    current = DocumentVersion(document_id=document.id, version="v2.0", view_scope="ALL", transfer_policy="ALLOWED",
                              is_current=True, ingest_status="DONE")
    draft = DocumentVersion(document_id=document.id, version="v2.1", view_scope="ALL", transfer_policy="ALLOWED",
                            is_current=False, ingest_status="PENDING")
    db.add_all([current, draft])
    db.commit()
    return document, current, draft


def add_cluster(db, tickets=0, created_days=0, **fields):
    """tickets 건의 CLS 티켓을 이 묶음에 넣는다. 돌려주는 값은 (묶음, 티켓들)."""
    status = fields.pop("status", "REVIEWING")
    values = {"category_code": "NET", "judgment": "ADD_ITEM", "title": "VPN 연결 시 인터넷 끊김",
              "created_at": DAY + timedelta(days=created_days), **fields}
    cluster = GuideCluster(status=status, reject_reason="이미 매뉴얼에 있음" if status == "REJECTED" else None, **values)
    db.add(cluster)
    db.flush()
    owner = db.query(User).filter_by(employee_no="E0001").one().id
    rows = []
    for i in range(tickets):
        t = add_ticket(db, owner, work="CLS")
        t.closed_at = DAY - timedelta(days=tickets - i)
        db.add(TicketGuideState(ticket_id=t.id, status=status, cluster_id=cluster.id))
        rows.append(t)
    db.commit()
    return cluster, rows


def items(res):
    return [c["id"] for c in res.json()["items"]]


# ------------------------------------------------------------------ 권한


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_admin_only(client, users, db, who):
    cluster, _ = add_cluster(db)
    assert error_code(client.get(API, headers=users[who])) == "FORBIDDEN"
    assert error_code(client.get(f"{API}/{cluster.id}", headers=users[who])) == "FORBIDDEN"
    assert error_code(client.post(f"{API}/{cluster.id}/reject", headers=users[who], json={"reason": "x"})) == "FORBIDDEN"
    assert error_code(client.post(f"{API}/{cluster.id}/apply", headers=users[who])) == "FORBIDDEN"
    assert error_code(client.patch(f"{API}/{cluster.id}", headers=users[who],
                                   json={"draftMd": "# x", "draftRevision": 0})) == "FORBIDDEN"
    db.expire_all()
    assert cluster.status == "REVIEWING"


# ------------------------------------------------------------------ GC-01 목록


def test_list_sorted_by_ticket_count_then_newest(client, users, db, guide):
    few, _ = add_cluster(db, tickets=1, created_days=2)
    many, _ = add_cluster(db, tickets=3)
    older_same, _ = add_cluster(db, tickets=1, created_days=1)
    sec, _ = add_cluster(db, category_code="SEC", judgment="SEC_MANUAL")    # 티켓 0건도 나온다

    res = client.get(API, headers=users["admin"])

    assert res.status_code == 200
    assert items(res) == [many.id, few.id, older_same.id, sec.id]
    body = res.json()
    assert (body["totalCount"], body["page"], body["size"]) == (4, 1, 20)
    assert body["items"][0]["ticketCount"] == 3


def test_list_item_fields(client, users, db, guide):
    document, current, draft = guide
    cluster, _ = add_cluster(db, tickets=2, target_document_id=document.id, base_version_id=current.id,
                             registered_version_id=draft.id, draft_basis={"base_md": "# 원본"})

    item = client.get(API, headers=users["admin"]).json()["items"][0]

    assert item == {
        "id": cluster.id, "category": {"code": "NET", "name": "VPN·네트워크"}, "judgment": "ADD_ITEM",
        "status": "REVIEWING", "title": "VPN 연결 시 인터넷 끊김", "ticketCount": 2,
        "targetDocument": {"id": document.id, "docCode": "IT-NET-001", "title": "VPN 접속 장애 대응 가이드"},
        "registeredVersion": {"id": draft.id, "version": "v2.1", "isCurrent": False, "ingestStatus": "PENDING"},
        "createdAt": "2026-11-14T09:00:00+09:00", "updatedAt": None,
    }


def test_list_filters(client, users, db):
    net, _ = add_cluster(db)
    sec, _ = add_cluster(db, category_code="SEC", judgment="SEC_MANUAL")
    manual, _ = add_cluster(db, judgment="MANUAL_CANDIDATE")
    rejected, _ = add_cluster(db, status="REJECTED")
    admin = users["admin"]

    assert set(items(client.get(API, headers=admin, params={"categoryCode": "SEC"}))) == {sec.id}
    assert set(items(client.get(API, headers=admin, params={"judgment": ["SEC_MANUAL", "MANUAL_CANDIDATE"]}))) == {sec.id, manual.id}
    assert set(items(client.get(API, headers=admin, params={"status": "REVIEWING"}))) == {net.id, sec.id, manual.id}
    assert set(items(client.get(API, headers=admin, params={"status": "REJECTED"}))) == {rejected.id}
    assert client.get(API, headers=admin, params={"status": "WAITING"}).status_code == 422   # 대기는 티켓 상태


def test_list_paging(client, users, db):
    for days in range(3):
        add_cluster(db, created_days=days)
    res = client.get(API, headers=users["admin"], params={"page": 2, "size": 2})
    assert len(res.json()["items"]) == 1 and res.json()["totalPages"] == 2


# ------------------------------------------------------------------ GC-02 상세


def test_detail(client, users, db, guide):
    document, current, draft = guide
    cluster, tickets = add_cluster(db, tickets=2, target_document_id=document.id, base_version_id=current.id,
                                   registered_version_id=draft.id, draft_md="### 3.8 VPN을 연결하면 인터넷이 끊김",
                                   draft_revision=3, review_info={"reason": "공유기 설정은 다루지 않음"},
                                   compared_items=[{"docCode": "IT-NET-001", "version": "v2.0", "sectionNo": "3.3"}],
                                   draft_basis={"base_md": "# 원본", "version": "v2.1"})
    tickets[0].resolution_note = "공유기 VPN 패스스루 설정을 켬"
    db.commit()

    res = client.get(f"{API}/{cluster.id}", headers=users["admin"])

    assert res.status_code == 200
    body = res.json()
    assert "draftBasis" not in body                    # 등록 검사용 기준은 내려 주지 않는다
    assert (body["targetSection"], body["targetMd"]) == (None, None)
    assert (body["draftMd"], body["draftRevision"]) == ("### 3.8 VPN을 연결하면 인터넷이 끊김", 3)
    assert body["reviewInfo"] == {"reason": "공유기 설정은 다루지 않음"}
    assert body["comparedItems"][0]["sectionNo"] == "3.3"
    assert body["baseVersion"]["version"] == "v2.0" and body["currentVersion"]["id"] == current.id
    assert body["baseChanged"] is False
    assert body["registeredVersion"]["version"] == "v2.1"
    assert [t["receiptNo"] for t in body["tickets"]] == [t.receipt_no for t in tickets]   # 해결 확인 순
    assert body["tickets"][0]["resolutionNote"] == "공유기 VPN 패스스루 설정을 켬"
    assert body["ticketCount"] == 2


def test_detail_change_shows_existing_item(client, users, db, guide):
    cluster, _ = add_cluster(db, judgment="CHANGE", draft_basis={
        "base_md": "# 원본 전체", "target_section": "3.3", "target_md": "### 3.3 집에서 VPN이 자주 끊김\n본문"})

    body = client.get(f"{API}/{cluster.id}", headers=users["admin"]).json()

    assert (body["targetSection"], body["targetMd"]) == ("3.3", "### 3.3 집에서 VPN이 자주 끊김\n본문")
    assert "# 원본 전체" not in str(body)               # 문서 전체 원문은 내려 주지 않는다


def test_detail_base_changed(client, users, db, guide):
    document, current, draft = guide
    cluster, _ = add_cluster(db, target_document_id=document.id, base_version_id=current.id)
    current.is_current, draft.is_current, draft.ingest_status = False, True, "DONE"   # 그사이 다른 버전이 현행
    db.commit()

    assert client.get(f"{API}/{cluster.id}", headers=users["admin"]).json()["baseChanged"] is True


def test_detail_rejected_and_new_guide(client, users, db):
    admin_id = db.query(User).filter_by(employee_no="E0009").one().id
    rejected, _ = add_cluster(db, status="REJECTED", reviewed_by=admin_id, reviewed_at=DAY)
    new_guide, _ = add_cluster(db, judgment="NEW_GUIDE")

    body = client.get(f"{API}/{rejected.id}", headers=users["admin"]).json()
    assert body["rejectReason"] == "이미 매뉴얼에 있음" and body["reviewedBy"]["employeeNo"] == "E0009"

    body = client.get(f"{API}/{new_guide.id}", headers=users["admin"]).json()
    assert (body["targetDocument"], body["baseVersion"], body["currentVersion"], body["baseChanged"]) == (None, None, None, False)


def test_detail_not_found(client, users):
    res = client.get(f"{API}/999", headers=users["admin"])
    assert (res.status_code, error_code(res)) == (404, "GUIDE_CLUSTER_NOT_FOUND")


# ------------------------------------------------------------------ GC-03 거절 · GC-04 반영 표시


def guide_states(db):
    return {s.ticket_id: s.status for s in db.scalars(select(TicketGuideState))}


def audits(db):
    return [(a.event_type, a.target_id, a.result, a.reason) for a in db.scalars(
        select(AuditLog).where(AuditLog.event_type.like("GUIDE_CLUSTER%")).order_by(AuditLog.id))]


def reject(client, users, cluster, reason="이미 매뉴얼 3.2에 있는 절차"):
    return client.post(f"{API}/{cluster.id}/reject", headers=users["admin"], json={"reason": reason})


def test_reject(client, users, db):
    cluster, tickets = add_cluster(db, tickets=2)
    _, (untouched,) = add_cluster(db, tickets=1)          # 다른 묶음의 티켓은 그대로

    res = reject(client, users, cluster, "  이미 매뉴얼 3.2에 있는 절차  ")

    assert res.status_code == 200
    body = res.json()
    assert (body["status"], body["rejectReason"]) == ("REJECTED", "이미 매뉴얼 3.2에 있는 절차")
    assert body["reviewedBy"]["employeeNo"] == "E0009" and body["reviewedAt"] is not None
    assert guide_states(db) == {tickets[0].id: "REJECTED", tickets[1].id: "REJECTED", untouched.id: "REVIEWING"}
    assert audits(db) == [("GUIDE_CLUSTER_REJECT", cluster.id, "ADD_ITEM REVIEWING → REJECTED", "이미 매뉴얼 3.2에 있는 절차")]


def test_reject_registered_cluster_blocks_activation(client, users, db, guide):
    """등록한 뒤에도 현행 전환 전이면 거절할 수 있고, 거절하면 그 버전의 현행 전환이 막힌다."""
    document, current, draft = guide
    draft.ingest_status = "DONE"
    cluster, _ = add_cluster(db, tickets=1, target_document_id=document.id, base_version_id=current.id,
                             registered_version_id=draft.id)

    assert reject(client, users, cluster).json()["registeredVersion"]["id"] == draft.id   # 등록 버전은 남긴다
    res = client.patch(f"/api/v1/documents/{document.id}/versions/{draft.id}", headers=users["admin"],
                       json={"isCurrent": True})
    assert (res.status_code, error_code(res)) == (409, "DOCUMENT_VERSION_HAS_REJECTED_CLUSTER")


def test_reject_requires_reason(client, users, db):
    cluster, _ = add_cluster(db)
    for body in ({}, {"reason": "   "}, {"reason": "x" * 501}):
        assert client.post(f"{API}/{cluster.id}/reject", headers=users["admin"], json=body).status_code == 422


@pytest.mark.parametrize("status", ["APPLIED", "REJECTED"])
def test_reject_and_apply_only_reviewing(client, users, db, status):
    cluster, _ = add_cluster(db, status=status)
    for res in (reject(client, users, cluster), client.post(f"{API}/{cluster.id}/apply", headers=users["admin"])):
        assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_NOT_REVIEWING")
        assert res.json()["error"]["details"][0]["value"] == status
    assert audits(db) == []


def test_apply_manual_candidate(client, users, db):
    cluster, tickets = add_cluster(db, tickets=2, judgment="MANUAL_CANDIDATE")

    res = client.post(f"{API}/{cluster.id}/apply", headers=users["admin"])

    assert res.status_code == 200
    assert (res.json()["status"], res.json()["reviewedBy"]["employeeNo"]) == ("APPLIED", "E0009")
    assert guide_states(db) == {t.id: "APPLIED" for t in tickets}
    assert audits(db) == [("GUIDE_CLUSTER_APPLY", cluster.id, "MANUAL_CANDIDATE REVIEWING → APPLIED", None)]


def test_apply_registered_cluster_refused(client, users, db, guide):
    """등록한 묶음은 현행 전환으로만 반영한다 (거절·기준 버전 검사를 건너뛰지 않게)."""
    document, current, draft = guide
    cluster, _ = add_cluster(db, target_document_id=document.id, base_version_id=current.id,
                             registered_version_id=draft.id)

    res = client.post(f"{API}/{cluster.id}/apply", headers=users["admin"])

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_REGISTERED")
    db.expire_all()
    assert cluster.status == "REVIEWING"


def test_reject_and_apply_not_found(client, users):
    assert error_code(client.post(f"{API}/999/reject", headers=users["admin"], json={"reason": "x"})) == "GUIDE_CLUSTER_NOT_FOUND"
    assert error_code(client.post(f"{API}/999/apply", headers=users["admin"])) == "GUIDE_CLUSTER_NOT_FOUND"


# ------------------------------------------------------------------ GC-05 초안 수정 저장


def save(client, users, cluster, md="### 3.8 고친 초안", revision=0):
    return client.patch(f"{API}/{cluster.id}", headers=users["admin"], json={"draftMd": md, "draftRevision": revision})


def test_save_draft_increments_revision(client, users, db):
    cluster, _ = add_cluster(db, draft_md="### 3.8 AI 초안")

    first = save(client, users, cluster, "### 3.8 한 번 고침", 0)
    second = save(client, users, cluster, "### 3.8 두 번 고침", 1)

    assert first.status_code == 200 and first.json()["draftRevision"] == 1
    assert (second.json()["draftMd"], second.json()["draftRevision"]) == ("### 3.8 두 번 고침", 2)
    assert second.json()["updatedAt"] is not None
    assert audits(db) == []                                 # 상태 변경이 아니라 기록하지 않는다


def test_save_draft_conflict(client, users, db):
    """두 관리자가 같은 번호(0)로 열었다. 먼저 저장한 쪽만 들어가고 나중 쪽은 지금 번호를 받는다."""
    cluster, _ = add_cluster(db, draft_md="### 3.8 AI 초안")
    assert save(client, users, cluster, "### 3.8 관리자 A", 0).status_code == 200

    res = save(client, users, cluster, "### 3.8 관리자 B", 0)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_DRAFT_CONFLICT")
    assert res.json()["error"]["details"][0] == {"field": "draftRevision", "reason": "STALE",
                                                 "message": "지금 초안 번호", "value": 1}
    db.expire_all()
    assert (cluster.draft_md, cluster.draft_revision) == ("### 3.8 관리자 A", 1)


def test_save_draft_refused_after_registration(client, users, db, guide):
    document, current, draft = guide
    cluster, _ = add_cluster(db, draft_md="### 3.8 등록한 초안", target_document_id=document.id,
                             base_version_id=current.id, registered_version_id=draft.id)

    res = save(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_DRAFT_LOCKED")
    assert res.json()["error"]["details"][0]["value"] == draft.id
    db.expire_all()
    assert (cluster.draft_md, cluster.draft_revision) == ("### 3.8 등록한 초안", 0)


def test_save_draft_refused_for_manual_candidate(client, users, db):
    cluster, _ = add_cluster(db, judgment="MANUAL_CANDIDATE")
    assert error_code(save(client, users, cluster)) == "GUIDE_CLUSTER_NO_DRAFT"


@pytest.mark.parametrize("status", ["APPLIED", "REJECTED"])
def test_save_draft_only_reviewing(client, users, db, status):
    cluster, _ = add_cluster(db, status=status, draft_md="### 3.8")
    assert error_code(save(client, users, cluster)) == "GUIDE_CLUSTER_NOT_REVIEWING"


@pytest.mark.parametrize("body", [{"draftMd": "# x"}, {"draftRevision": 0}, {"draftMd": "", "draftRevision": 0},
                                  {"draftMd": "# x", "draftRevision": -1},
                                  {"draftMd": "# x", "draftRevision": 0, "targetDocumentId": 3}])
def test_save_draft_validation(client, users, db, body):
    """넣을 문서 변경(targetDocumentId)은 아직 받지 않는다."""
    cluster, _ = add_cluster(db, draft_md="### 3.8")
    assert client.patch(f"{API}/{cluster.id}", headers=users["admin"], json=body).status_code == 422


def test_save_draft_not_found(client, users):
    res = client.patch(f"{API}/999", headers=users["admin"], json={"draftMd": "# x", "draftRevision": 0})
    assert error_code(res) == "GUIDE_CLUSTER_NOT_FOUND"


# ------------------------------------------------------------------ GC-06 초안 등록


@pytest.fixture
def assembled(client, db, tmp_path):
    """조립 함수와 적재 시작을 바꿔 끼운다. 실제 조립은 Postgres·파일이 필요해 rag 쪽 테스트가 본다."""
    calls, ingests = [], []

    def fake(conn, document_id, clusters, draft_version_id, *, view_scope, transfer_policy, actor_id):
        calls.append({"document_id": document_id, "clusters": clusters, "version_id": draft_version_id,
                      "view_scope": view_scope, "transfer_policy": transfer_policy, "actor_id": actor_id})
        path = tmp_path / f"{len(calls)}.md"
        path.write_text("조립 결과", encoding="utf-8")
        if draft_version_id is None:
            row = DocumentVersion(document_id=document_id, version=f"v3.{len(calls)}", view_scope=view_scope,
                                  transfer_policy=transfer_policy, is_current=False, ingest_status="PENDING")
            db.add(row)
            db.flush()
        else:
            row = db.get(DocumentVersion, draft_version_id)
        row.file_path = str(path)
        sections = {c["id"]: c["draft_basis"].get("section_no") or f"3.{9 + len(calls)}"
                    for c in clusters if c["judgment"] != "CHANGE"}
        return {"version_id": row.id, "version": row.version, "file_path": str(path), "sections": sections,
                "warnings": ["개인정보로 보이는 글이 있습니다"]}

    app.dependency_overrides[guide_assembler] = lambda: fake
    app.dependency_overrides[ingest_submitter] = lambda: ingests.append
    return calls, ingests


def ready_cluster(db, guide, tickets=1, **fields):
    """등록할 수 있는 묶음. 기준은 현행 v2.0."""
    document, current, _ = guide
    values = {"target_document_id": document.id, "base_version_id": current.id, "draft_md": "### 3.N 제목\n본문",
              "draft_basis": {"schema": 1, "base_version_id": current.id}, **fields}
    return add_cluster(db, tickets=tickets, **values)


def register(client, users, cluster, revision=0, view_scope="AGENT", policy="BLOCKED", who="admin"):
    return client.post(f"{API}/{cluster.id}/register", headers=users[who],
                       json={"draftRevision": revision, "viewScope": view_scope, "transferPolicy": policy})


def test_register_makes_new_version(client, users, db, guide, assembled):
    calls, ingests = assembled
    document, *_ = guide
    cluster, tickets = ready_cluster(db, guide, tickets=2)

    res = register(client, users, cluster)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "REVIEWING"                    # 현행 전환 때 APPLIED 가 된다
    assert body["registeredVersion"]["version"] == "v3.1"
    assert body["warnings"] == ["개인정보로 보이는 글이 있습니다"]
    assert "draftBasis" not in body
    admin = db.query(User).filter_by(employee_no="E0009").one()
    assert len(calls) == 1
    call = calls[0]
    assert (call["document_id"], call["version_id"]) == (document.id, None)
    assert (call["view_scope"], call["transfer_policy"], call["actor_id"]) == ("AGENT", "BLOCKED", admin.id)
    assert call["clusters"][0]["receipts"] == [t.receipt_no for t in tickets]
    db.expire_all()
    assert cluster.registered_version_id == body["registeredVersion"]["id"]
    assert cluster.draft_basis["section_no"] == "3.10"
    assert cluster.draft_basis["schema"] == 1
    assert ingests == [cluster.registered_version_id]
    log = db.scalars(select(AuditLog).where(AuditLog.event_type == "GUIDE_CLUSTER_REGISTER")).one()
    assert (log.target_id, log.actor_id, log.result) == (cluster.id, admin.id, "ADD_ITEM → v3.1")


def test_register_continues_pending_version(client, users, db, guide, assembled):
    calls, _ = assembled
    first, _ = ready_cluster(db, guide)
    second, _ = ready_cluster(db, guide)
    register(client, users, first)
    db.expire_all()
    version_id = first.registered_version_id

    res = register(client, users, second)

    assert res.status_code == 200
    assert calls[1]["version_id"] == version_id
    assert [c["id"] for c in calls[1]["clusters"]] == [first.id, second.id]
    assert calls[1]["clusters"][0]["draft_basis"]["section_no"] == "3.10"   # 앞 묶음 번호를 유지한다
    db.expire_all()
    assert second.registered_version_id == version_id


def test_register_does_not_touch_uploaded_version(client, users, db, guide, assembled):
    """관리자가 올린 v2.1 은 묶음이 없어 이어 쓰지 않는다."""
    calls, _ = assembled
    cluster, _ = ready_cluster(db, guide)

    assert register(client, users, cluster).status_code == 200
    assert calls[0]["version_id"] is None


def test_register_skips_pending_version_with_old_base(client, users, db, guide, assembled):
    """기준이 지난 대기 버전에 이어 쓰면 조립이 거부되어 새 묶음까지 막힌다."""
    calls, _ = assembled
    document, current, draft = guide
    older = DocumentVersion(document_id=document.id, version="v1.0", view_scope="ALL", transfer_policy="ALLOWED",
                            is_current=False, ingest_status="DONE")
    db.add(older)
    db.commit()
    add_cluster(db, target_document_id=document.id, base_version_id=older.id, registered_version_id=draft.id)
    cluster, _ = ready_cluster(db, guide)

    assert register(client, users, cluster).status_code == 200
    assert calls[0]["version_id"] is None
    assert [c["id"] for c in calls[0]["clusters"]] == [cluster.id]


def test_reregister_after_reject_reuses_version(client, users, db, guide, assembled):
    calls, ingests = assembled
    kept, _ = ready_cluster(db, guide)
    dropped, _ = ready_cluster(db, guide)
    register(client, users, kept)
    register(client, users, dropped)
    db.expire_all()
    version_id = kept.registered_version_id
    assert reject(client, users, dropped).status_code == 200

    res = register(client, users, kept)

    assert res.status_code == 200
    assert calls[-1]["version_id"] == version_id
    assert [c["id"] for c in calls[-1]["clusters"]] == [kept.id]
    db.expire_all()
    assert kept.registered_version_id == version_id
    assert dropped.registered_version_id is None
    assert dropped.status == "REJECTED"
    assert ingests[-1] == version_id


def test_reregister_without_reject_refused(client, users, db, guide, assembled):
    calls, _ = assembled
    cluster, _ = ready_cluster(db, guide)
    register(client, users, cluster)

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_REGISTERED")
    assert len(calls) == 1


def test_register_reuses_version_with_only_rejected_clusters(client, users, db, guide, assembled):
    calls, _ = assembled
    dropped, _ = ready_cluster(db, guide)
    register(client, users, dropped)
    db.expire_all()
    version_id = dropped.registered_version_id
    reject(client, users, dropped)
    cluster, _ = ready_cluster(db, guide)

    assert register(client, users, cluster).status_code == 200
    assert calls[-1]["version_id"] == version_id
    assert [c["id"] for c in calls[-1]["clusters"]] == [cluster.id]
    db.expire_all()
    assert dropped.registered_version_id is None


@pytest.mark.parametrize("judgment", ["NEW_GUIDE", "MANUAL_CANDIDATE"])
def test_register_refuses_unsupported_judgment(client, users, db, guide, assembled, judgment):
    cluster, _ = ready_cluster(db, guide, judgment=judgment)

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_NOT_REGISTRABLE")
    assert res.json()["error"]["details"][0]["reason"] == "JUDGMENT"
    assert assembled[0] == []


@pytest.mark.parametrize("missing", ["draft_md", "draft_basis"])
def test_register_refuses_cluster_without_draft(client, users, db, guide, assembled, missing):
    cluster, _ = ready_cluster(db, guide, judgment="SEC_MANUAL", **{missing: None})

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_NOT_REGISTRABLE")
    assert res.json()["error"]["details"][0]["reason"] == "NO_DRAFT"


def test_register_stale_revision(client, users, db, guide, assembled):
    cluster, _ = ready_cluster(db, guide, draft_revision=2)

    res = register(client, users, cluster, revision=1)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_DRAFT_CONFLICT")
    assert assembled[0] == []


def test_register_base_changed(client, users, db, guide, assembled):
    _, _, draft = guide
    cluster, _ = ready_cluster(db, guide, base_version_id=draft.id)

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_BASE_CHANGED")
    assert assembled[0] == []


@pytest.mark.parametrize("status", ["APPLIED", "REJECTED"])
def test_register_only_reviewing(client, users, db, guide, assembled, status):
    cluster, _ = ready_cluster(db, guide, status=status)

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_NOT_REVIEWING")


def test_register_assemble_refused(client, users, db, guide, assembled):
    _, ingests = assembled

    def refuse(*args, **kwargs):
        raise CaseGuideError(["묶음 1: 기준 원문이 지금 현행 파일과 다릅니다. 다시 맞춰 주세요"])

    app.dependency_overrides[guide_assembler] = lambda: refuse
    cluster, _ = ready_cluster(db, guide)

    res = register(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_ASSEMBLE_FAILED")
    assert res.json()["error"]["details"][0]["message"].startswith("묶음 1:")
    db.expire_all()
    assert cluster.registered_version_id is None
    assert ingests == []


def test_register_removes_file_when_save_fails(client, users, db, guide, assembled, tmp_path, monkeypatch):
    _, ingests = assembled
    cluster, _ = ready_cluster(db, guide)
    original = db.commit
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("저장 실패")))

    with pytest.raises(RuntimeError):
        register(client, users, cluster)

    monkeypatch.setattr(db, "commit", original)
    assert not (tmp_path / "1.md").exists()
    assert ingests == []
    db.expire_all()
    assert cluster.registered_version_id is None


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_register_admin_only(client, users, db, guide, assembled, who):
    cluster, _ = ready_cluster(db, guide)

    assert error_code(register(client, users, cluster, who=who)) == "FORBIDDEN"


@pytest.mark.parametrize("body", [
    {"viewScope": "ALL", "transferPolicy": "BLOCKED"},
    {"draftRevision": 0, "transferPolicy": "BLOCKED"},
    {"draftRevision": 0, "viewScope": "ALL"},
    {"draftRevision": 0, "viewScope": "EVERYONE", "transferPolicy": "BLOCKED"},
    {"draftRevision": 0, "viewScope": "ALL", "transferPolicy": "OPEN"},
])
def test_register_validation(client, users, db, guide, assembled, body):
    cluster, _ = ready_cluster(db, guide)

    res = client.post(f"{API}/{cluster.id}/register", headers=users["admin"], json=body)

    assert (res.status_code, error_code(res)) == (422, "VALIDATION_ERROR")


def test_register_not_found(client, users, assembled):
    res = client.post(f"{API}/999/register", headers=users["admin"],
                      json={"draftRevision": 0, "viewScope": "ALL", "transferPolicy": "BLOCKED"})

    assert (res.status_code, error_code(res)) == (404, "GUIDE_CLUSTER_NOT_FOUND")


# ------------------------------------------------------------------ GC-07 다시 맞추기


@pytest.fixture
def rebased(client, guide):
    """다시 맞추기 함수를 바꿔 끼운다. conflicts 에 넣으면 충돌을 돌려준다."""
    _, current, _ = guide
    state = {"calls": [], "conflicts": []}

    def fake(conn, document_id, cluster):
        state["calls"].append({"document_id": document_id, "cluster": cluster})
        basis = {"schema": 1, "judgment": cluster["judgment"], "base_version_id": current.id, "base_md": "새 현행",
                 "section_no": None}
        if state["conflicts"]:
            basis["conflicts"] = {"revision": None, "items": copy.deepcopy(state["conflicts"])}
        return {"draft_basis": basis, "conflicts": state["conflicts"], "warnings": ["이미 반영된 접수 번호입니다"]}

    app.dependency_overrides[guide_rebaser] = lambda: fake
    return state


CONFLICT = {"section": "3.3", "kind": "TARGET_CHANGED", "message": "3.3 이 새 현행에서 바뀌었습니다",
            "old_md": "### 3.3 예전", "new_md": "### 3.3 새 현행"}


def stale_cluster(db, guide, tickets=1, **fields):
    """기준이 v2.1 인 묶음. 지금 현행은 v2.0 이라 기준이 바뀐 상태다."""
    _, _, draft = guide
    return ready_cluster(db, guide, tickets=tickets, base_version_id=draft.id, draft_revision=2,
                         draft_basis={"schema": 1, "base_version_id": draft.id, "base_md": "옛 현행", "section_no": "3.9"},
                         **fields)


def rebase(client, users, cluster, revision=2, who="admin"):
    return client.post(f"{API}/{cluster.id}/rebase", headers=users[who], json={"draftRevision": revision})


def test_rebase_moves_basis_to_current(client, users, db, guide, rebased):
    document, current, draft = guide
    cluster, tickets = stale_cluster(db, guide, tickets=2)

    res = rebase(client, users, cluster)

    assert res.status_code == 200
    body = res.json()
    assert (body["draftRevision"], body["baseChanged"], body["conflicts"]) == (3, False, [])
    assert body["baseVersion"]["id"] == current.id
    assert body["draftMd"] == "### 3.N 제목\n본문"             # 초안 글은 그대로다
    assert body["warnings"] == ["이미 반영된 접수 번호입니다"]
    call = rebased["calls"][0]
    assert call["document_id"] == document.id
    assert call["cluster"]["draft_revision"] == 2
    assert call["cluster"]["receipts"] == [t.receipt_no for t in tickets]
    db.expire_all()
    assert cluster.base_version_id == current.id
    assert cluster.draft_basis["section_no"] is None
    admin = db.query(User).filter_by(employee_no="E0009").one()
    log = db.scalars(select(AuditLog).where(AuditLog.event_type == "GUIDE_CLUSTER_REBASE")).one()
    assert (log.target_id, log.actor_id) == (cluster.id, admin.id)
    assert log.result == f"ADD_ITEM 기준 버전 {draft.id} → {current.id}, 충돌 0건"


def test_rebase_releases_registered_version_then_registers(client, users, db, guide, rebased, assembled):
    calls, _ = assembled
    _, _, draft = guide
    cluster, _ = stale_cluster(db, guide, registered_version_id=draft.id)
    assert error_code(register(client, users, cluster, revision=2)) == "GUIDE_CLUSTER_BASE_CHANGED"

    assert rebase(client, users, cluster).json()["registeredVersion"] is None

    res = register(client, users, cluster, revision=3)
    assert res.status_code == 200
    assert calls[0]["version_id"] is None                       # 옛 기준 버전에 이어 쓰지 않는다
    assert res.json()["registeredVersion"]["id"] != draft.id


def test_conflict_blocks_register_until_draft_saved(client, users, db, guide, rebased, assembled):
    calls, _ = assembled
    rebased["conflicts"] = [CONFLICT]
    cluster, _ = stale_cluster(db, guide, judgment="CHANGE")

    res = rebase(client, users, cluster)

    assert res.json()["conflicts"][0] == {"section": "3.3", "kind": "TARGET_CHANGED", "message": CONFLICT["message"],
                                          "oldMd": "### 3.3 예전", "newMd": "### 3.3 새 현행"}
    db.expire_all()
    assert cluster.draft_basis["conflicts"]["revision"] == 3    # 올린 번호를 기록한다
    assert client.get(f"{API}/{cluster.id}", headers=users["admin"]).json()["conflicts"][0]["section"] == "3.3"

    blocked = register(client, users, cluster, revision=3)
    assert (blocked.status_code, error_code(blocked)) == (409, "GUIDE_CLUSTER_CONFLICT_UNRESOLVED")
    assert blocked.json()["error"]["details"][0]["value"] == "3.3"
    assert calls == []

    assert save(client, users, cluster, revision=3).json()["conflicts"] == []
    assert register(client, users, cluster, revision=4).status_code == 200


@pytest.mark.parametrize("judgment", ["NEW_GUIDE", "MANUAL_CANDIDATE"])
def test_rebase_refuses_unsupported_judgment(client, users, db, guide, rebased, judgment):
    cluster, _ = stale_cluster(db, guide, judgment=judgment)

    res = rebase(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_NOT_REGISTRABLE")
    assert rebased["calls"] == []


def test_rebase_stale_revision(client, users, db, guide, rebased):
    cluster, _ = stale_cluster(db, guide)

    res = rebase(client, users, cluster, revision=1)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_DRAFT_CONFLICT")
    assert rebased["calls"] == []


@pytest.mark.parametrize("status", ["APPLIED", "REJECTED"])
def test_rebase_only_reviewing(client, users, db, guide, rebased, status):
    cluster, _ = stale_cluster(db, guide, status=status)

    assert error_code(rebase(client, users, cluster)) == "GUIDE_CLUSTER_NOT_REVIEWING"


def test_rebase_refused_changes_nothing(client, users, db, guide, rebased):
    _, _, draft = guide

    def refuse(*args, **kwargs):
        raise CaseGuideError(["바꿀 항목 3.3이 새 현행에 없습니다"])

    app.dependency_overrides[guide_rebaser] = lambda: refuse
    cluster, _ = stale_cluster(db, guide, judgment="CHANGE", registered_version_id=draft.id)

    res = rebase(client, users, cluster)

    assert (res.status_code, error_code(res)) == (409, "GUIDE_CLUSTER_REBASE_FAILED")
    assert res.json()["error"]["details"][0]["message"] == "바꿀 항목 3.3이 새 현행에 없습니다"
    db.expire_all()
    assert (cluster.draft_revision, cluster.registered_version_id) == (2, draft.id)


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_rebase_admin_only(client, users, db, guide, rebased, who):
    cluster, _ = stale_cluster(db, guide)

    assert error_code(rebase(client, users, cluster, who=who)) == "FORBIDDEN"


@pytest.mark.parametrize("body", [{}, {"draftRevision": -1}, {"draftRevision": 0, "extra": 1}])
def test_rebase_validation(client, users, db, guide, rebased, body):
    cluster, _ = stale_cluster(db, guide)

    res = client.post(f"{API}/{cluster.id}/rebase", headers=users["admin"], json=body)

    assert (res.status_code, error_code(res)) == (422, "VALIDATION_ERROR")


def test_rebase_not_found(client, users, rebased):
    res = client.post(f"{API}/999/rebase", headers=users["admin"], json={"draftRevision": 0})

    assert (res.status_code, error_code(res)) == (404, "GUIDE_CLUSTER_NOT_FOUND")
