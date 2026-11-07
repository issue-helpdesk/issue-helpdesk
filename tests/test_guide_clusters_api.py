"""해결 사례 가이드화 묶음 API (GC-01~04). SQLite 메모리 DB 만 쓴다."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import AuditLog, Category, DocumentVersion, GuideCluster, KnowledgeDocument, TicketGuideState, User
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
    assert (body["draftMd"], body["draftRevision"]) == ("### 3.8 VPN을 연결하면 인터넷이 끊김", 3)
    assert body["reviewInfo"] == {"reason": "공유기 설정은 다루지 않음"}
    assert body["comparedItems"][0]["sectionNo"] == "3.3"
    assert body["baseVersion"]["version"] == "v2.0" and body["currentVersion"]["id"] == current.id
    assert body["baseChanged"] is False
    assert body["registeredVersion"]["version"] == "v2.1"
    assert [t["receiptNo"] for t in body["tickets"]] == [t.receipt_no for t in tickets]   # 해결 확인 순
    assert body["tickets"][0]["resolutionNote"] == "공유기 VPN 패스스루 설정을 켬"
    assert body["ticketCount"] == 2


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
