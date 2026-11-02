"""생성 서비스(services/jira_create.py)를 실제 Jira(ITHD)에 붙여 처음부터 끝까지 해 보는 점검 스크립트. 저장소 루트에서 실행한다.

    python backend/app/integrations/jira/service_check.py

하는 일 (DB는 임시 SQLite 메모리 DB라 아무것도 남지 않는다. Jira에는 시험 이슈 1건이 생긴다)
    1. 시험 접수(Ticket) 1건 + 생성 작업(JIRA_CREATE) 등록
    2. 작업 실행 → Jira에 이슈 생성, tickets.jira_key·jira_sync_status(SYNCED)·work_status(RDY)·작업 DONE 저장 확인
    3. 같은 작업을 다시 실행 → 선점 실패(SKIPPED), 같은 접수를 다시 등록 → 같은 작업 (중복 등록 없음)
    4. DB의 jira_key를 지우고(저장 유실 흉내) 새 작업으로 다시 실행 → 새로 만들지 않고 기존 이슈에 연결(LINKED)
       work_status도 Jira 현재 상태를 읽어 다시 채우는지 본다
       (Jira 검색에 방금 만든 이슈가 나타날 때까지 잠시 기다린 뒤에 한다)

필요한 것: 루트 .env 의 JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN, pip install -r requirements.txt
토큰 값은 화면에 출력하지 않는다. 만든 시험 이슈는 확인 후 Jira에서 직접 지운다.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.integrations.jira import JiraClient, JiraError  # noqa: E402
from app.models import Base, Category, Inquiry, InquiryType, IntegrationJob, SupportGroup, Ticket, User  # noqa: E402
from app.services import jira_create  # noqa: E402

TABLES = ["users", "support_groups", "categories", "inquiry_types", "inquiries", "tickets", "integration_jobs",
          "support_group_members", "member_skills", "assignment_logs", "time_off"]


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):
    # SQLite 는 INTEGER PRIMARY KEY 만 자동 증가한다
    return "INTEGER"


def _seed(db: Session, receipt_no: str) -> Ticket:
    """시험용 접수 1건. 값은 smoke_check.py 의 시험 티켓(RCPT-TEST-*)과 같다."""
    db.add_all([
        Category(code="NET", name="VPN·네트워크"),
        SupportGroup(id=3, name="네트워크팀"),
        User(id=17, employee_no="EMP-TEST", name="시험 사용자", email="test@hanwha-ict.example",
             service_role="EMPLOYEE", account_status="ACTIVE", password_hash="x"),
    ])
    db.flush()
    db.add_all([
        InquiryType(id=21, code="NET-02", category_code="NET", name="VPN 접속 불가",
                    request_kind="INCIDENT", default_urgency="P2", default_group_id=3),
        Inquiry(id=1, user_id=17, status="RECEIVED"),
    ])
    ticket = Ticket(
        id=42, receipt_no=receipt_no, draft_id=55, inquiry_id=1, session_id=1,
        summary="[테스트] 생성 서비스 점검 — 확인 후 삭제", target_system="VPN", symptom="재택근무 중 VPN 접속이 실패합니다.",
        occurred_at="오늘 오전", category_code="NET", inquiry_type_id=21, urgency="P2",
        urgency_reason="개인 업무 중단", business_impact="사내 시스템 접속 불가", tried_actions="재접속\n PC 재시작",
        group_id=3, jira_sync_status="PENDING", assign_status="PENDING", work_status=None,  # 접수(TK-04)는 null로 저장한다
    )
    db.add(ticket)
    db.commit()
    return ticket


def _step(ok: bool, text: str) -> bool:
    print(f"  [{'통과' if ok else '확인 필요'}] {text}")
    return ok


def _wait_until_searchable(jira: JiraClient, receipt_no: str, tries: int = 10, delay: float = 2.0) -> bool:
    """Jira 검색 색인에 방금 만든 이슈가 나타날 때까지 기다린다. 나타나기 전에 다시 만들면 중복이 생길 수 있다."""
    for _ in range(tries):
        if jira.find_by_receipt(receipt_no):
            return True
        time.sleep(delay)
    return False


def run_check(jira: JiraClient, *, stamp: str | None = None, wait_tries: int = 10, wait_delay: float = 2.0) -> bool:
    receipt_no = f"RCPT-TEST-{stamp or datetime.now().strftime('%m%d%H%M')}"
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES])
    ok = True
    key = None
    try:
        with Session(engine) as db:
            ticket = _seed(db, receipt_no)
            job = jira_create.enqueue_jira_create(db, ticket)
            db.commit()
            print(f"  시험 접수 {receipt_no}, 생성 작업 #{job.id} 등록 (PENDING)")

            print("2. 작업 실행")
            first = jira_create.run_jira_create_job(db, jira, job.id)
            db.expire_all()
            ticket, job = db.get(Ticket, 42), db.get(IntegrationJob, job.id)
            print(f"  결과: {first.outcome}, Jira 키 {first.jira_key}")
            ok &= _step(first.outcome == "CREATED", "Jira에 새 이슈가 생김 (CREATED)")
            ok &= _step(bool(ticket.jira_key) and ticket.jira_key == first.jira_key, f"tickets.jira_key 저장: {ticket.jira_key}")
            ok &= _step(ticket.jira_sync_status == "SYNCED", f"jira_sync_status = {ticket.jira_sync_status}")
            ok &= _step(ticket.work_status == "RDY", f"work_status = {ticket.work_status} (Jira 생성 직후 RDY)")
            ok &= _step((job.status, job.attempts) == ("DONE", 1), f"작업 상태 {job.status}, 시도 {job.attempts}회")
            key = ticket.jira_key

            print("3. 같은 작업 재실행 · 같은 접수 재등록")
            again = jira_create.run_jira_create_job(db, jira, job.id)
            ok &= _step(again.outcome == "SKIPPED", f"끝난 작업은 다시 실행되지 않음 ({again.outcome})")
            same = jira_create.enqueue_jira_create(db, db.get(Ticket, 42))
            ok &= _step(same.id == job.id, "같은 접수를 다시 등록해도 같은 작업 (중복 등록 없음)")

            print("4. DB 저장 유실 흉내: jira_key를 지우고 새 작업으로 다시 실행")
            searchable = _wait_until_searchable(jira, receipt_no, wait_tries, wait_delay)
            ok &= _step(searchable, "Jira 검색에 방금 만든 이슈가 나타남 (안 나타나면 아래 단계는 건너뜀)")
            if searchable:
                ticket = db.get(Ticket, 42)
                ticket.jira_key, ticket.jira_sync_status, ticket.work_status = None, "PENDING", None
                done = db.get(IntegrationJob, job.id)
                done.idempotency_key = f"{done.idempotency_key}:done"  # 새 작업을 등록할 수 있게 비켜 둔다
                db.commit()
                retry = jira_create.enqueue_jira_create(db, ticket)
                db.commit()
                linked = jira_create.run_jira_create_job(db, jira, retry.id)
                ok &= _step(linked.outcome == "LINKED" and linked.jira_key == key,
                            f"새로 만들지 않고 기존 이슈에 연결: {linked.outcome} {linked.jira_key} (기대 {key})")
                db.expire_all()
                ok &= _step(db.get(Ticket, 42).work_status == "RDY",
                            f"기존 이슈 연결 시 Jira 현재 상태로 채움: work_status = {db.get(Ticket, 42).work_status} (기대 RDY)")
    finally:
        engine.dispose()
    print(f"  시험 이슈: {jira.base_url}/browse/{key or '(생성 안 됨)'} — 확인 후 Jira에서 직접 지우세요")
    return ok


def main() -> int:
    try:
        with JiraClient.from_env() as jira:
            me = jira.check_auth()
            print(f"1. 인증 성공: {me['display_name']}")
            ok = run_check(jira)
    except JiraError as e:
        print(f"실패: {e.to_dict()}")
        return 1
    print("결과:", "모두 통과" if ok else "확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
