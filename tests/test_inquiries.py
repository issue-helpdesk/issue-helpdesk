"""문의·상담 API (IQ) — SQLite 메모리 DB. AI 는 Mock 모델과 가짜 검색으로 판단 흐름을 그대로 돌린다."""
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import Text, TypeDecorator, create_engine, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent.llm import LLMError, MockAdapter
from app.agent.sensitive import BLOCKED_NOTICE
from app.main import app
from app.rag.search import SearchResponse
from app.rag.search.runtime import get_search_fn
from app.services.ai_responder import ask_more_counts, build_ai_input, get_llm_port_factory

from app.models import (
    Base,
    Category,
    ChatSession,
    DocumentVersion,
    Inquiry,
    InquiryAssessment,
    InquiryType,
    KnowledgeDocument,
    LegacyInquiry,
    Message,
    MessageSource,
    SupportGroup,
    SupportGroupMember,
    Ticket,
    TicketDraft,
)
from app.utils import datetime_utils
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_flow_correct import DOC, QUOTE

INQUIRIES = "/api/v1/inquiries"
INQUIRY_TABLES = TABLES + ["categories", "inquiry_types", "inquiries", "chat_sessions", "messages",
                           "ticket_drafts", "tickets", "knowledge_documents", "document_versions",
                           "legacy_inquiries", "message_sources", "inquiry_assessments"]
VPN = "어제 업데이트 이후로 VPN 접속이 안 돼요.\n재택 중이라 업무를 못 하고 있습니다."
FACTS = {"summary": "업데이트 이후 VPN 접속 불가", "target_system": "사내 VPN", "symptom": None, "occurred_at": "어제",
         "impact_scope": "PERSONAL", "work_stopped": "full", "has_workaround": None, "time_constraint": None,
         "business_impact": None, "security_suspected": False, "tried_actions": []}


# ---------------------------------------------------------------- SQLite 에서 Postgres 전용 칸 쓰기

class ListAsJson(TypeDecorator):
    """text[] 칸을 SQLite 에서는 JSON 글로 저장한다."""
    impl = Text
    cache_ok = True

    def __init__(self, *args, **kwargs):
        super().__init__()

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)


SQLiteDialect_pysqlite.colspecs = {**SQLiteDialect_pysqlite.colspecs, ARRAY: ListAsJson}


@compiles(ARRAY, "sqlite")
def array_as_text(type_, compiler, **kw):
    return "TEXT"


def create_sqlite_tables(engine, names):
    """Postgres 전용 기본값('[]'::jsonb)은 테이블을 만드는 동안만 빼고 되돌린다."""
    tables = [Base.metadata.tables[name] for name in names]
    removed = [(c, c.server_default) for t in tables for c in t.columns
               if "::" in str(getattr(c.server_default, "arg", ""))]
    for column, _ in removed:
        column.server_default = None
    try:
        Base.metadata.create_all(engine, tables=tables)
    finally:
        for column, default in removed:
            column.server_default = default


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, INQUIRY_TABLES)
    with Session(engine) as session:
        yield session
    engine.dispose()


# ---------------------------------------------------------------- Mock 모델·가짜 검색

def ai_reply(action="ASK_MORE", **fields):
    """Mock 모델이 돌려줄 AI 출력 (docs/08 2장)."""
    output = {"schema_version": "1.0", "action": action, "urgent_signal": False, "title": "업데이트 이후 VPN 접속 불가",
              "category_code": "NET", "inquiry_type_code": None, "request_kind": "INCIDENT", "urgency_suggested": "P3",
              "facts": FACTS, "rationale": {"category": "", "urgency_reasons": ["재택 중 VPN 불가"], "action": ""},
              "reply": "접속할 때 화면에 나오는 오류 메시지가 있나요?", "evidence": [],
              "missing_items": ["symptom"] if action == "ASK_MORE" else [], "escalation_reason": None,
              "confidence": 0.8}
    return json.dumps(output | fields, ensure_ascii=False)


class FakeAi:
    """요청마다 새 MockAdapter 를 만든다. replies 는 한 요청 안에서 1차·2차 판단 순서로 쓴다."""

    def __init__(self):
        self.replies = [ai_reply()]
        self.broken = False
        self.adapters = []
        self.searches = []
        self.documents = ()

    def port(self):
        if self.broken:
            raise RuntimeError("model down")
        self.adapters.append(MockAdapter(self.replies))
        return self.adapters[-1]

    def search(self, request):
        self.searches.append(request)
        return SearchResponse(query=request.query, model="test", threshold=0.6, documents=self.documents)


@pytest.fixture(autouse=True)
def ai(client):
    fake = FakeAi()
    app.dependency_overrides[get_llm_port_factory] = lambda: fake.port
    app.dependency_overrides[get_search_fn] = lambda: fake.search
    return fake


@pytest.fixture
def owner(db):
    return add_user(db, "E0001", name="김민지")


@pytest.fixture
def headers(client, owner):
    return bearer(login(client, "E0001"))


def start(client, headers, content=VPN, key="key-1"):
    return client.post(INQUIRIES, json={"content": content}, headers={**headers, "Idempotency-Key": key})


def add_ticket(db, inquiry_id, group_id=None, work_status=None):
    session_id = db.scalar(select(ChatSession.id).where(ChatSession.inquiry_id == inquiry_id))
    draft = TicketDraft(inquiry_id=inquiry_id, session_id=session_id, status="CONFIRMED")
    db.add(draft)
    db.flush()
    ticket = Ticket(receipt_no=f"RCPT-{inquiry_id:04d}", draft_id=draft.id, inquiry_id=inquiry_id, session_id=session_id,
                    summary="VPN 접속 불가", group_id=group_id, jira_sync_status="SYNCED", assign_status="ASSIGNED",
                    work_status=work_status)
    db.add(ticket)
    db.commit()
    return ticket


# ---------------------------------------------------------------- IQ-01 새 문의 시작

def test_start_inquiry_saves_inquiry_session_and_messages(client, db, owner, headers):
    res = start(client, headers)

    assert res.status_code == 201
    body = res.json()
    inquiry = body["inquiry"]
    assert inquiry["user"] == {"id": owner.id, "employeeNo": "E0001", "name": "김민지"}
    assert (inquiry["status"], inquiry["displayStatus"], inquiry["action"]) == ("IN_PROGRESS", "in_progress", "ASK_MORE")
    assert inquiry["title"] == "업데이트 이후 VPN 접속 불가"
    assert [(m["seq"], m["sender"]) for m in body["messages"]] == [(1, "USER"), (2, "AI")]
    assert body["messages"][0]["content"] == VPN
    assert all(m["sessionId"] == inquiry["currentSessionId"] for m in body["messages"])
    assert body["messages"][1]["content"] == "접속할 때 화면에 나오는 오류 메시지가 있나요?"
    assert body["assessment"]["action"] == "ASK_MORE"
    assert body["nextActions"] == ["REPLY"]

    saved = db.scalars(select(Message).order_by(Message.seq)).all()
    assert [(m.seq, m.sender) for m in saved] == [(1, "USER"), (2, "AI")]


def test_start_inquiry_trims_content(client, headers):
    res = start(client, headers, content="  VPN 안 돼요  ")

    assert res.json()["messages"][0]["content"] == "VPN 안 돼요"


@pytest.mark.parametrize("content, reason", [("   ", "TOO_SHORT"), ("가" * 4001, "TOO_LONG")])
def test_start_inquiry_validates_content(client, headers, content, reason):
    res = start(client, headers, content=content)

    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["field"], detail["reason"]) == ("content", reason)


def test_start_inquiry_requires_idempotency_key(client, headers):
    res = client.post(INQUIRIES, json={"content": VPN}, headers=headers)

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["field"] == "Idempotency-Key"


def test_start_inquiry_keeps_user_message_when_ai_fails(client, db, headers, ai):
    ai.broken = True

    res = start(client, headers)

    assert res.status_code == 503
    assert error_code(res) == "AI_UNAVAILABLE"
    inquiry_id = db.scalar(select(Inquiry.id))
    assert res.json()["error"]["details"] == [{"reason": "INQUIRY_ID", "message": "저장된 문의", "value": inquiry_id}]
    assert [m.sender for m in db.scalars(select(Message))] == ["USER"]


def test_start_inquiry_requires_login(client):
    assert client.post(INQUIRIES, json={"content": VPN}, headers={"Idempotency-Key": "k"}).status_code == 401


# ---------------------------------------------------------------- IQ-01·08 AI 판단 흐름

@pytest.fixture
def taxonomy(db):
    """분류 NET, 세부 유형 NET-02(기본 그룹 네트워크팀, 기본 긴급도 P3), 서비스데스크."""
    net, desk = SupportGroup(name="네트워크팀"), SupportGroup(name="서비스데스크", is_triage=True)
    db.add_all([Category(code="NET", name="VPN·네트워크"), net, desk])
    db.flush()
    vpn = InquiryType(code="NET-02", category_code="NET", name="개인 VPN 접속 장애", request_kind="INCIDENT",
                      default_urgency="P3", default_group_id=net.id)
    db.add(vpn)
    db.commit()
    return net, desk, vpn


ANSWER = ai_reply("ANSWER", inquiry_type_code="NET-02", reply="VPN 클라이언트를 업데이트해 보세요.",
                  evidence=[{"kind": "DOCUMENT", "source_id": DOC.unit_key, "quote": QUOTE}])


def assessments(db):
    return db.scalars(select(InquiryAssessment).order_by(InquiryAssessment.id)).all()


def test_answer_after_search(client, db, headers, ai, taxonomy):
    net, _, vpn = taxonomy
    ai.replies = [ai_reply("ANSWER", inquiry_type_code="NET-02"), ANSWER]
    ai.documents = (DOC,)

    body = start(client, headers).json()

    assert len(ai.searches) == 1 and ai.searches[0].service_role == "EMPLOYEE"
    assert body["messages"][1]["content"] == "VPN 클라이언트를 업데이트해 보세요."
    inquiry = body["inquiry"]
    assert (inquiry["action"], inquiry["displayStatus"]) == ("ANSWER", "unconfirmed")
    assert (inquiry["categoryCode"], inquiry["inquiryTypeId"], inquiry["recommendedGroupId"]) == ("NET", vpn.id, net.id)
    assert body["nextActions"] == ["CONFIRM_RESOLUTION"]

    (saved,) = assessments(db)
    assert (saved.action, saved.urgency, saved.inquiry_type_id, saved.missing_items) == ("ANSWER", "P3", vpn.id, [])
    assert saved.urgency_reason == "재택 중 VPN 불가"         # 규칙이 긴급도를 바꾸지 않았으면 AI 가 든 이유
    assert saved.facts["summary"] == "업데이트 이후 VPN 접속 불가"
    assert saved.ai_output["action"] == "ANSWER"
    assert body["assessment"] == {"missingItems": [], "urgentSignal": False, "categoryCode": "NET",
                                  "inquiryTypeId": vpn.id, "urgency": saved.urgency,
                                  "urgencyReason": saved.urgency_reason, "action": "ANSWER"}


def test_urgency_rule_reason_is_saved(client, db, headers, ai, taxonomy):
    no_workaround = {**FACTS, "has_workaround": False}
    ai.replies = [ai_reply(inquiry_type_code="NET-02", facts=no_workaround)]

    body = start(client, headers).json()

    assert body["assessment"]["urgency"] == "P2"
    assert body["assessment"]["urgencyReason"] == "개인 업무 전면 중단, 대체 방법 없음"


def test_answer_without_evidence_offers_handoff(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply("ANSWER"), ai_reply("ANSWER")]

    body = start(client, headers).json()

    assert body["inquiry"]["action"] == "ESCALATE"
    assert body["nextActions"] == ["DECIDE_HANDOFF"]
    assert [o["rule"] for o in assessments(db)[0].override_reasons if o["field"] == "action"] == ["NO_EVIDENCE"]


def test_urgent_signal_skips_search(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply("ANSWER", urgent_signal=True)]

    body = start(client, headers).json()

    assert ai.searches == []
    assert (body["inquiry"]["action"], body["assessment"]["urgentSignal"]) == ("ESCALATE", True)


def test_out_of_scope_recommends_service_desk(client, db, headers, ai, taxonomy):
    _, desk, _ = taxonomy
    ai.replies = [ai_reply("OUT_OF_SCOPE", category_code=None), ai_reply("OUT_OF_SCOPE", category_code=None)]

    body = start(client, headers).json()

    assert (body["inquiry"]["action"], body["inquiry"]["recommendedGroupId"]) == ("OUT_OF_SCOPE", desk.id)


def test_model_error_offers_handoff_instead_of_failing(client, db, headers, ai, taxonomy):
    ai.replies = [LLMError("TIMEOUT")]

    res = start(client, headers)

    assert res.status_code == 201
    assert res.json()["inquiry"]["action"] == "ESCALATE"
    assert assessments(db)[0].ai_output is None


def test_all_blocked_evidence_shows_notice(client, db, headers, ai, taxonomy):
    ai.replies = [ai_reply("ANSWER"), ANSWER]
    ai.documents = (replace(DOC, transfer_policy="BLOCKED"),)

    body = start(client, headers).json()

    assert body["messages"][1]["content"] == BLOCKED_NOTICE
    assert body["inquiry"]["action"] == "ESCALATE"
    assert len(ai.adapters[0].requests) == 1          # 2차는 Claude 를 부르지 않는다


def test_unanswered_questions_reach_limit(client, db, headers, ai, taxonomy):
    """같은 항목을 두 번 물었는데 답을 못 얻으면 세 번째 판단에서 담당자 연결로 바꾼다 (09 4.2)."""
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    send(client, headers, inquiry_id, content="잘 모르겠어요", key="k-2")
    send(client, headers, inquiry_id, content="모르겠어요", key="k-3")

    body = send(client, headers, inquiry_id, content="몰라요", key="k-4").json()

    assert body["inquiry"]["action"] == "ESCALATE"
    assert "ASK_MORE_UNANSWERED" in [o["rule"] for o in assessments(db)[-1].override_reasons]


def test_history_and_collected_facts_are_sent(client, db, headers, ai, taxonomy):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]

    send(client, headers, inquiry_id, content="인증 서버 오류가 나요")

    sent = json.loads(ai.adapters[-1].requests[0][1])
    assert sent["message"] == "인증 서버 오류가 나요"
    assert [m["role"] for m in sent["history"]] == ["user", "assistant"]
    assert sent["collected_facts"]["target_system"] == "사내 VPN"
    assert sent["ask_more_count"] == 1


def test_secrets_are_masked_before_saving(client, db, headers, ai):
    body = start(client, headers, content="비밀번호는 Abc123!@ 인데 VPN 로그인이 안 돼요").json()

    saved = db.scalar(select(Message.content).where(Message.seq == 1))
    assert "Abc123!@" not in saved
    assert body["messages"][0]["content"] == saved
    assert "Abc123!@" not in ai.adapters[0].requests[0][1]


def assessment(action, missing=(), urgent=False, urgency=None, **facts):
    return InquiryAssessment(action=action, missing_items=list(missing), urgent_signal=urgent, urgency=urgency,
                             facts=FACTS | facts)


def test_ask_more_counts():
    asked_symptom = assessment("ASK_MORE", ["symptom"])

    assert ask_more_counts([]) == (0, 0)
    assert ask_more_counts([asked_symptom]) == (1, 0)                                   # 아직 답을 기다림
    assert ask_more_counts([asked_symptom, assessment("ASK_MORE", ["symptom"])]) == (2, 1)
    assert ask_more_counts([asked_symptom, assessment("ANSWER", symptom="인증 오류")]) == (1, 0)


def test_build_ai_input_uses_prior_assessments(db, owner):
    inquiry = Inquiry(id=7, user_id=owner.id, status="IN_PROGRESS")
    history = [Message(session_id=3, seq=1, sender="USER", content="VPN 안 돼요"),
               Message(session_id=3, seq=2, sender="AI", content="오류가 나오나요?"),
               Message(session_id=3, seq=3, sender="USER", content="인증 오류요")]
    prior = [assessment("ASK_MORE", ["symptom"], urgent=True, urgency="P2"),
             assessment("ASK_MORE", ["symptom"], urgency="P3", target_system="메일")]

    inp = build_ai_input(inquiry, owner, "IT운영팀", history, prior)

    assert (inp.session_id, inp.inquiry_id, inp.message) == ("3", "7", "인증 오류요")
    assert [m.role for m in inp.history] == ["user", "assistant"]
    assert inp.collected_facts.target_system == "메일"
    assert (inp.ask_more_count, inp.ask_more_unanswered_count) == (2, 1)
    assert (inp.prior_urgent_signal, inp.prior_urgency) == (True, "P2")
    assert (inp.user_context.employee_no, inp.user_context.department_name) == ("E0001", "IT운영팀")


def test_history_limit_from_env(db, owner, monkeypatch):
    monkeypatch.setenv("AI_HISTORY_LIMIT", "2")
    history = [Message(session_id=3, seq=i, sender="USER" if i % 2 else "AI", content=f"글 {i}") for i in range(1, 6)]

    inp = build_ai_input(Inquiry(id=7, user_id=owner.id, status="IN_PROGRESS"), owner, None, history, [])

    assert [m.content for m in inp.history] == ["글 3", "글 4"]       # 이번 글(글 5) 앞의 최근 2개


# ---------------------------------------------------------------- IQ-03 문의 상세

def test_get_inquiry(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    db.add(Category(code="NET", name="VPN·네트워크"))
    db.get(Inquiry, inquiry_id).category_code = "NET"
    db.commit()

    res = client.get(f"{INQUIRIES}/{inquiry_id}", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["category"] == {"code": "NET", "name": "VPN·네트워크"}
    assert (body["ticket"], body["activeDraftId"], body["closedAt"]) == (None, None, None)
    assert body["createdAt"].endswith("+09:00")


def test_get_inquiry_of_other_user_is_not_found(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    add_user(db, "E0002", service_role="AGENT")

    res = client.get(f"{INQUIRIES}/{inquiry_id}", headers=bearer(login(client, "E0002")))

    assert res.status_code == 404
    assert error_code(res) == "INQUIRY_NOT_FOUND"


def test_admin_can_view_any_inquiry(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    add_user(db, "A0001", service_role="ADMIN")

    assert client.get(f"{INQUIRIES}/{inquiry_id}", headers=bearer(login(client, "A0001"))).status_code == 200


@pytest.mark.parametrize("member_active, group_active, expected", [(True, True, 200), (False, True, 404), (True, False, 404)])
def test_ticket_group_member_can_view(client, db, headers, member_active, group_active, expected):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    group = SupportGroup(name="네트워크팀", is_active=group_active)
    db.add(group)
    db.flush()
    agent = add_user(db, "E0002", service_role="AGENT")
    db.add(SupportGroupMember(group_id=group.id, user_id=agent.id, member_role="AGENT", assignable=True,
                              is_active=member_active))
    add_ticket(db, inquiry_id, group_id=group.id, work_status="WIP")

    res = client.get(f"{INQUIRIES}/{inquiry_id}", headers=bearer(login(client, "E0002")))

    assert res.status_code == expected


@pytest.mark.parametrize("work_status, display", [
    (None, "received"), ("RDY", "assigned"), ("WIP", "progress"), ("FIN", "awaiting_confirm"), ("CLS", "resolved"),
])
def test_display_status_follows_ticket(client, db, headers, work_status, display):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    ticket = add_ticket(db, inquiry_id, work_status=work_status)

    body = client.get(f"{INQUIRIES}/{inquiry_id}", headers=headers).json()

    assert body["displayStatus"] == display
    assert body["ticket"] == {"id": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": None, "workStatus": work_status}


def test_get_inquiry_not_found(client, headers):
    assert error_code(client.get(f"{INQUIRIES}/999", headers=headers)) == "INQUIRY_NOT_FOUND"


# ---------------------------------------------------------------- IQ-08 메시지 전송

def send(client, headers, inquiry_id, content="인증 서버에 연결할 수 없다고 나와요.", key="key-2"):
    return client.post(f"{INQUIRIES}/{inquiry_id}/messages", json={"content": content},
                       headers={**headers, "Idempotency-Key": key})


def test_send_message_continues_session(client, db, headers):
    first = start(client, headers).json()
    inquiry_id = first["inquiry"]["id"]

    res = send(client, headers, inquiry_id)

    assert res.status_code == 201
    body = res.json()
    assert [(m["seq"], m["sender"]) for m in body["messages"]] == [(3, "USER"), (4, "AI")]
    assert {m["sessionId"] for m in body["messages"]} == {first["inquiry"]["currentSessionId"]}
    assert body["inquiry"]["title"] == first["inquiry"]["title"]          # 제목은 첫 AI 처리 때만 정한다
    assert body["nextActions"] == ["REPLY"]
    assert db.scalar(select(Message.content).where(Message.seq == 3)) == "인증 서버에 연결할 수 없다고 나와요."


@pytest.mark.parametrize("role", ["EMPLOYEE", "ADMIN"])
def test_send_message_only_by_owner(client, db, headers, role):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    add_user(db, "E0002", service_role=role)

    res = send(client, bearer(login(client, "E0002")), inquiry_id)

    assert res.status_code == 404
    assert error_code(res) == "INQUIRY_NOT_FOUND"


@pytest.mark.parametrize("status", ["AI_RESOLVED", "CLOSED_UNRESOLVED"])
def test_send_message_to_closed_inquiry(client, db, headers, status):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    db.get(Inquiry, inquiry_id).status = status
    db.commit()

    assert error_code(send(client, headers, inquiry_id)) == "INQUIRY_CLOSED"


def test_send_message_to_ended_session(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    db.scalar(select(ChatSession)).ended_at = datetime_utils.now()
    db.commit()

    assert error_code(send(client, headers, inquiry_id)) == "INQUIRY_CLOSED"


@pytest.mark.parametrize("status, action", [("IN_PROGRESS", "ANSWER"), ("IN_PROGRESS", "ESCALATE"), ("RECEIVED", "ESCALATE")])
def test_send_message_outside_question_stage(client, db, headers, status, action):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    inquiry = db.get(Inquiry, inquiry_id)
    inquiry.status, inquiry.action = status, action
    db.commit()

    res = send(client, headers, inquiry_id)

    assert res.status_code == 409
    assert error_code(res) == "INQUIRY_INVALID_STATE"
    assert res.json()["error"]["details"] == [{"reason": "CURRENT_STATUS", "message": "현재 상태", "value": status}]
    assert db.scalar(select(Message).where(Message.seq == 3)) is None


def test_send_message_keeps_user_message_when_ai_fails(client, db, headers, ai):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    ai.broken = True

    res = send(client, headers, inquiry_id)

    saved = db.scalar(select(Message).where(Message.seq == 3))
    assert res.status_code == 503
    assert res.json()["error"]["details"] == [{"reason": "MESSAGE_ID", "message": "저장된 메시지", "value": saved.id}]
    assert saved.sender == "USER"


def test_send_message_requires_idempotency_key(client, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]

    res = client.post(f"{INQUIRIES}/{inquiry_id}/messages", json={"content": "x"}, headers=headers)

    assert res.status_code == 422


# ---------------------------------------------------------------- IQ-05 세션 목록

def test_list_sessions(client, db, headers):
    session_id = start(client, headers).json()["inquiry"]["currentSessionId"]
    inquiry_id = db.scalar(select(Inquiry.id))

    res = client.get(f"{INQUIRIES}/{inquiry_id}/sessions", headers=headers)

    assert res.status_code == 200
    (item,) = res.json()["items"]
    assert (item["id"], item["inquiryId"], item["endedAt"], item["endReason"]) == (session_id, inquiry_id, None, None)


def test_list_sessions_of_other_user_is_not_found(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    add_user(db, "E0002")

    res = client.get(f"{INQUIRIES}/{inquiry_id}/sessions", headers=bearer(login(client, "E0002")))

    assert error_code(res) == "INQUIRY_NOT_FOUND"


# ---------------------------------------------------------------- IQ-07 메시지 목록

def test_list_messages(client, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    send(client, headers, inquiry_id)

    res = client.get(f"{INQUIRIES}/{inquiry_id}/messages", headers=headers)

    assert res.status_code == 200
    assert [(m["seq"], m["sender"]) for m in res.json()["items"]] == [(1, "USER"), (2, "AI"), (3, "USER"), (4, "AI")]
    assert all(m["sources"] == [] for m in res.json()["items"])


def test_list_messages_by_session(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    old_session = db.scalar(select(ChatSession))
    old_session.ended_at = datetime_utils.now()
    new_session = ChatSession(inquiry_id=inquiry_id)
    db.add(new_session)
    db.flush()
    db.add(Message(session_id=new_session.id, seq=1, sender="USER", content="다시 문의해요"))
    db.commit()

    all_items = client.get(f"{INQUIRIES}/{inquiry_id}/messages", headers=headers).json()["items"]
    new_items = client.get(f"{INQUIRIES}/{inquiry_id}/messages", params={"sessionId": new_session.id},
                           headers=headers).json()["items"]

    assert [(m["sessionId"], m["seq"]) for m in all_items] == [
        (old_session.id, 1), (old_session.id, 2), (new_session.id, 1),
    ]
    assert [m["content"] for m in new_items] == ["다시 문의해요"]


def test_list_messages_rejects_session_of_other_inquiry(client, headers):
    first = start(client, headers).json()["inquiry"]
    second = start(client, headers, key="key-3").json()["inquiry"]

    res = client.get(f"{INQUIRIES}/{first['id']}/messages", params={"sessionId": second["currentSessionId"]},
                     headers=headers)

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["field"] == "sessionId"
    assert res.json()["error"]["details"][0]["reason"] == "NOT_FOUND"


@pytest.fixture
def answered(client, db, headers):
    """AI 답변(seq 2)에 열람 범위가 다른 출처 4개를 붙인다."""
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    ai_message_id = db.scalar(select(Message.id).where(Message.seq == 2))
    for code, scope in [("IT-NET-001", "ALL"), ("IT-NET-900", "AGENT")]:
        doc = KnowledgeDocument(doc_code=code, doc_type="GUIDE", title=code)
        db.add(doc)
        db.flush()
        db.add(DocumentVersion(document_id=doc.id, version="v1.0", view_scope=scope, ingest_status="DONE"))
    legacy = LegacyInquiry(legacy_no="L-001", received_at=datetime_utils.now(), view_scope="ALL")
    db.add(legacy)
    db.flush()
    db.add_all([
        MessageSource(message_id=ai_message_id, source_kind="DOCUMENT", doc_code="IT-NET-001", version="v1.0",
                      location="3.2", excerpt="업데이트 후 접속 불가", rank=1),
        MessageSource(message_id=ai_message_id, source_kind="DOCUMENT", doc_code="IT-NET-900", version="v1.0", rank=2),
        MessageSource(message_id=ai_message_id, source_kind="LEGACY", legacy_inquiry_id=legacy.id,
                      excerpt="재설치 후 정상", rank=3),
        MessageSource(message_id=ai_message_id, source_kind="DOCUMENT", doc_code="DELETED", version="v1.0", rank=4),
    ])
    db.commit()
    return inquiry_id


def source_codes(res):
    ai = next(m for m in res.json()["items"] if m["sender"] == "AI")
    return [(s["sourceKind"], s["docCode"]) for s in ai["sources"]]


def test_list_messages_filters_sources_by_view_scope(client, db, headers, answered):
    add_user(db, "A0001", service_role="ADMIN")

    mine = client.get(f"{INQUIRIES}/{answered}/messages", headers=headers)
    admin = client.get(f"{INQUIRIES}/{answered}/messages", headers=bearer(login(client, "A0001")))

    assert source_codes(mine) == [("DOCUMENT", "IT-NET-001"), ("LEGACY", None)]
    assert source_codes(admin) == [("DOCUMENT", "IT-NET-001"), ("DOCUMENT", "IT-NET-900"), ("LEGACY", None)]


def test_list_messages_source_fields(client, headers, answered):
    res = client.get(f"{INQUIRIES}/{answered}/messages", headers=headers)

    ai = next(m for m in res.json()["items"] if m["sender"] == "AI")
    source = ai["sources"][0]
    assert set(source) == {"id", "sourceKind", "docCode", "version", "location", "excerpt", "rank"}
    assert (source["location"], source["excerpt"], source["rank"]) == ("3.2", "업데이트 후 접속 불가", 1)


def test_list_messages_of_other_user_is_not_found(client, db, headers):
    inquiry_id = start(client, headers).json()["inquiry"]["id"]
    add_user(db, "E0002")

    res = client.get(f"{INQUIRIES}/{inquiry_id}/messages", headers=bearer(login(client, "E0002")))

    assert error_code(res) == "INQUIRY_NOT_FOUND"


# ---------------------------------------------------------------- IQ-02 문의 목록

def add_inquiry(db, user, created_at=None, **fields):
    inquiry = Inquiry(user_id=user.id, status=fields.pop("status", "IN_PROGRESS"), **fields)
    if created_at is not None:
        inquiry.created_at = created_at
    db.add(inquiry)
    db.flush()
    db.add(ChatSession(inquiry_id=inquiry.id))
    db.commit()
    return inquiry


def kst(text):
    return datetime.fromisoformat(text).replace(tzinfo=datetime_utils.KST).astimezone(timezone.utc)


def listed(client, headers, **params):
    return client.get(INQUIRIES, params=params, headers=headers)


def ids(res):
    return [item["id"] for item in res.json()["items"]]


def test_list_shows_only_own_inquiries(client, db, owner, headers):
    mine = add_inquiry(db, owner, title="VPN")
    other = add_user(db, "E0002", service_role="AGENT")
    add_inquiry(db, other)

    res = listed(client, headers)

    assert res.status_code == 200
    assert ids(res) == [mine.id]
    item = res.json()["items"][0]
    assert set(item) == {"id", "user", "title", "status", "displayStatus", "category", "urgency", "receiptNo",
                         "createdAt", "updatedAt"}
    assert item["user"] == {"id": owner.id, "employeeNo": "E0001", "name": "김민지"}
    assert res.json()["totalCount"] == 1


def test_admin_lists_all_and_filters_by_user(client, db, owner):
    mine = add_inquiry(db, owner)
    admin = add_user(db, "A0001", service_role="ADMIN")
    theirs = add_inquiry(db, admin)
    admin_headers = bearer(login(client, "A0001"))

    assert sorted(ids(listed(client, admin_headers))) == sorted([mine.id, theirs.id])
    assert ids(listed(client, admin_headers, userId=owner.id)) == [mine.id]


def test_user_id_filter_is_admin_only(client, headers):
    res = listed(client, headers, userId=1)

    assert res.status_code == 403
    assert error_code(res) == "FORBIDDEN"


def test_list_default_sort_is_newest_first(client, db, owner, headers):
    old = add_inquiry(db, owner, created_at=kst("2026-10-01T09:00:00"))
    new = add_inquiry(db, owner, created_at=kst("2026-10-02T09:00:00"))

    assert ids(listed(client, headers)) == [new.id, old.id]


def test_list_sort_by_urgency_puts_null_last(client, db, owner, headers):
    p3 = add_inquiry(db, owner, urgency="P3")
    none = add_inquiry(db, owner)
    p1 = add_inquiry(db, owner, urgency="P1")

    assert ids(listed(client, headers, sort="urgency,asc")) == [p1.id, p3.id, none.id]


@pytest.fixture
def every_state(db, owner):
    """화면 표시 상태마다 문의 하나씩. {표시 상태: 문의 id}"""
    states = {
        "in_progress": add_inquiry(db, owner, action="ASK_MORE"),
        "unconfirmed": add_inquiry(db, owner, action="ANSWER"),
        "ai_resolved": add_inquiry(db, owner, status="AI_RESOLVED", resolution_result="RESOLVED"),
        "unresolved": add_inquiry(db, owner, status="CLOSED_UNRESOLVED"),
        "received": add_inquiry(db, owner, status="RECEIVED"),
    }
    for work_status, shown in [("RDY", "assigned"), ("WIP", "progress"), ("FIN", "awaiting_confirm"), ("CLS", "resolved")]:
        states[shown] = add_inquiry(db, owner, status="HANDED_OFF")
        add_ticket(db, states[shown].id, work_status=work_status)
    return {shown: inquiry.id for shown, inquiry in states.items()}


def test_list_display_status_matches_detail(client, headers, every_state):
    items = listed(client, headers, size=100).json()["items"]

    for item in items:
        detail = client.get(f"{INQUIRIES}/{item['id']}", headers=headers).json()
        assert item["displayStatus"] == detail["displayStatus"]
    assert {item["id"]: item["displayStatus"] for item in items} == {v: k for k, v in every_state.items()}


@pytest.mark.parametrize("shown", ["in_progress", "unconfirmed", "ai_resolved", "unresolved", "received", "assigned",
                                   "progress", "awaiting_confirm", "resolved"])
def test_list_filters_by_display_status(client, headers, every_state, shown):
    assert ids(listed(client, headers, displayStatus=shown)) == [every_state[shown]]


def test_list_filters_by_status_category_and_urgency(client, db, owner, headers):
    db.add_all([Category(code="NET", name="VPN·네트워크"), Category(code="ACC", name="계정")])
    db.commit()
    net = add_inquiry(db, owner, category_code="NET", urgency="P2")
    acc = add_inquiry(db, owner, category_code="ACC", urgency="P3", status="AI_RESOLVED")

    assert ids(listed(client, headers, categoryCode="NET")) == [net.id]
    assert sorted(ids(listed(client, headers, urgency=["P2", "P3"]))) == sorted([net.id, acc.id])
    assert ids(listed(client, headers, status="AI_RESOLVED")) == [acc.id]
    assert listed(client, headers, categoryCode="NET").json()["items"][0]["category"] == {"code": "NET", "name": "VPN·네트워크"}


def test_list_filters_by_kst_date(client, db, owner, headers):
    before = add_inquiry(db, owner, created_at=kst("2026-09-30T23:59:00"))
    first = add_inquiry(db, owner, created_at=kst("2026-10-01T00:00:00"))
    last = add_inquiry(db, owner, created_at=kst("2026-10-01T23:59:00"))
    after = add_inquiry(db, owner, created_at=kst("2026-10-02T00:00:00"))

    one_day = listed(client, headers, createdFrom="2026-10-01", createdTo="2026-10-01")

    assert sorted(ids(one_day)) == sorted([first.id, last.id])
    assert before.id not in ids(listed(client, headers, createdFrom="2026-10-01"))
    assert after.id not in ids(listed(client, headers, createdTo="2026-10-01"))


def test_list_rejects_reversed_dates(client, headers):
    res = listed(client, headers, createdFrom="2026-10-02", createdTo="2026-10-01")

    assert res.status_code == 400
    assert error_code(res) == "INVALID_REQUEST"


@pytest.mark.parametrize("params, field, reason", [
    ({"createdFrom": "2026/10/01"}, "createdFrom", "INVALID_FORMAT"),
    ({"displayStatus": "closed"}, "displayStatus[0]", "INVALID_VALUE"),
    ({"urgency": "P5"}, "urgency[0]", "INVALID_VALUE"),
    ({"sort": "title,asc"}, "sort[0]", "INVALID_FORMAT"),
])
def test_list_validation(client, headers, params, field, reason):
    res = listed(client, headers, **params)

    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["field"], detail["reason"]) == (field, reason)


def test_list_search_by_title_receipt_and_doc_code(client, db, owner, headers):
    by_title = add_inquiry(db, owner, title="VPN 접속 불가")
    by_receipt = add_inquiry(db, owner, title="프린터")
    add_ticket(db, by_receipt.id)
    by_doc = add_inquiry(db, owner, title="메일")
    session_id = db.scalar(select(ChatSession.id).where(ChatSession.inquiry_id == by_doc.id))
    message = Message(session_id=session_id, seq=1, sender="AI", content="답변")
    db.add(message)
    db.flush()
    db.add(MessageSource(message_id=message.id, source_kind="DOCUMENT", doc_code="IT-MAIL-003", version="v1"))
    db.commit()

    assert ids(listed(client, headers, q="vpn")) == [by_title.id]
    assert ids(listed(client, headers, q=f"RCPT-{by_receipt.id:04d}")) == [by_receipt.id]
    assert ids(listed(client, headers, q="mail-003")) == [by_doc.id]
    assert listed(client, headers, q=f"RCPT-{by_receipt.id:04d}").json()["items"][0]["receiptNo"] == f"RCPT-{by_receipt.id:04d}"
