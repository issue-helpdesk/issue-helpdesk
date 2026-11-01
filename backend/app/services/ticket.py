"""접수 초안·최종 접수 (TK-01~04). 초안은 문의자가 고치고, 접수 확정 뒤 Jira 생성은 연동 작업이 한다."""
import logging
import os
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError

from app.agent.flow.urgency import urgency_of
from app.agent.llm import Facts, safe_default
from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.core.permissions import DEFAULT_TICKET_VIEW, TICKET_VIEW_ROLES
from app.db.session import DbSession
from app.models import (
    AssignmentLog,
    Category,
    ChatSession,
    Inquiry,
    InquiryAssessment,
    InquiryType,
    SupportGroup,
    Ticket,
    TicketDraft,
    User,
)
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.inquiry import InquiryRepositoryDep
from app.repositories.reference import ReferenceRepositoryDep
from app.repositories.ticket import TicketRepositoryDep
from app.schemas.common import ItemList, Page, parse_sort
from app.schemas.inquiry import CategoryRef, GroupRef, InquiryTypeRef, UserRef
from app.schemas.ticket import (
    DraftChange,
    DraftUpdateRequest,
    DraftUpdateResult,
    StatusHistory,
    Ticket as TicketView,
    TicketCreateRequest,
    TicketDraft as TicketDraftView,
    TicketListQuery,
    TicketSummary,
)
from app.services.ai_responder import facts_of, type_info
from app.services.inquiry import can_view_inquiry, close_unresolved, end_session, invalid_state
from app.services.inquiry_status import CLOSED_STATUSES, display_status, ticket_display_status
from app.services.jira_create import enqueue_jira_create
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

TRIAGE_REASON = "서비스데스크 확인"


class TicketService:
    def __init__(
        self,
        db: DbSession,
        inquiries: InquiryRepositoryDep,
        references: ReferenceRepositoryDep,
        tickets: TicketRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
    ) -> None:
        self.db = db
        self.inquiries = inquiries
        self.references = references
        self.tickets = tickets
        self.audit_logs = audit_logs

    def create_draft(self, inquiry_id: int, user: User) -> TicketDraftView:
        """TK-01. 마지막 판단 이력과 문의의 현재 판단값으로 초안을 채운다."""
        inquiry = self.inquiries.get_for_update(inquiry_id)
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.INQUIRY_NOT_FOUND)
        draft_id = self.inquiries.active_draft_id(inquiry.id)
        if draft_id is not None:
            raise AppError(ErrorCode.DRAFT_ALREADY_EXISTS, [
                {"reason": "DRAFT_ID", "message": "작성 중인 초안", "value": draft_id},
            ])
        session = self.inquiries.current_session(inquiry.id)
        if inquiry.status in CLOSED_STATUSES or session is None or session.ended_at is not None:
            raise AppError(ErrorCode.INQUIRY_CLOSED)
        if inquiry.status != "IN_PROGRESS":
            raise invalid_state(inquiry)

        assessments = self.inquiries.assessments(inquiry.id)
        last = assessments[-1] if assessments else None
        draft = self.tickets.add(TicketDraft(
            inquiry_id=inquiry.id,
            session_id=session.id,
            **facts_fields(facts_of(last) if last else None),
            category_code=inquiry.category_code,
            inquiry_type_id=inquiry.inquiry_type_id,
            urgency=inquiry.urgency,
            urgency_reason=last.urgency_reason if last else None,
            recommended_group_id=inquiry.recommended_group_id or self.references.triage_group_id(),
            status="EDITING",
        ))
        self.db.commit()
        return self.to_draft(draft)

    def get_draft(self, draft_id: int, user: User) -> TicketDraftView:
        """TK-02."""
        draft = self.tickets.get_draft(draft_id)
        inquiry = self.inquiries.get(draft.inquiry_id) if draft else None
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.DRAFT_NOT_FOUND)
        return self.to_draft(draft)

    def update_draft(self, draft_id: int, body: DraftUpdateRequest, user: User) -> DraftUpdateResult:
        """TK-03. 보낸 필드만 바꾼다. 세부 유형이 바뀌면 분류·긴급도·추천 그룹을 서버가 다시 정한다."""
        sent = body.model_fields_set
        if "status" in sent and len(sent) > 1:
            other = min(sent - {"status"})
            raise field_error(ErrorCode.VALIDATION_ERROR, DraftUpdateRequest.model_fields[other].alias or other,
                              "NOT_ALLOWED", "취소할 때는 다른 항목을 함께 보낼 수 없습니다.")
        inquiry, draft = self.lock_own_draft(draft_id, user)
        if draft.status != "EDITING":
            raise draft_not_editable(draft)

        if "status" in sent:
            close_unresolved(self.inquiries, self.audit_logs, inquiry, user)
            self.db.commit()
            return DraftUpdateResult(draft=self.to_draft(draft), changes=[])

        new_type = None
        if body.inquiry_type_id is not None:
            new_type = self.inquiries.ref(InquiryType, body.inquiry_type_id)
            if new_type is None or not new_type.is_active:
                raise field_error(ErrorCode.VALIDATION_ERROR, "inquiryTypeId", "NOT_FOUND", "존재하지 않는 세부 유형입니다.")

        for name in sent - {"inquiry_type_id"}:
            setattr(draft, name, getattr(body, name))
        changes = []
        if "inquiry_type_id" in sent and body.inquiry_type_id != draft.inquiry_type_id:
            changes = self.reclassify(inquiry, draft, new_type)
        if sent:
            draft.updated_at = datetime_utils.now()
        self.db.commit()
        return DraftUpdateResult(draft=self.to_draft(draft), changes=changes)

    def reclassify(self, inquiry: Inquiry, draft: TicketDraft, new_type: InquiryType | None) -> list[DraftChange]:
        """세부 유형을 바꾸면 분류·긴급도·추천 그룹을 다시 정하고, 바뀐 것만 돌려준다.

        긴급도는 대화에서 모은 facts 로 같은 규칙(08 5.3)을 다시 돌리되 지금 값보다 내리지 않는다.
        """
        assessments = self.inquiries.assessments(inquiry.id)
        last = assessments[-1] if assessments else None
        urgency = urgency_of(
            (facts_of(last) if last else None) or safe_default().facts,
            suggested_urgency(last),
            type_info(new_type) if new_type else None,
            prior_urgency=draft.urgency,
        )
        type_reason = f"세부 유형 {new_type.code}" if new_type else None
        updates = [
            ("categoryCode", "category_code", new_type.category_code if new_type else None,
             f"{type_reason}의 분류" if new_type else "미분류"),
            ("urgency", "urgency", urgency.value, " ".join(o["reason"] for o in urgency.overrides) or None),
            ("recommendedGroupId", "recommended_group_id",
             new_type.default_group_id if new_type else self.references.triage_group_id(),
             f"{type_reason} 기본 그룹" if new_type else TRIAGE_REASON),
        ]
        draft.inquiry_type_id = new_type.id if new_type else None
        changes = []
        for field, column, after, reason in updates:
            before = getattr(draft, column)
            if before != after:
                setattr(draft, column, after)
                changes.append(DraftChange(field=field, before=before, after=after, reason=reason))
                if column == "urgency":
                    draft.urgency_reason = reason
        return changes

    def confirm(self, body: TicketCreateRequest, user: User) -> tuple[TicketView, bool]:
        """TK-04. (접수, 새로 만들었는지). 이미 접수된 문의면 기존 접수를 돌려준다."""
        inquiry, draft = self.lock_own_draft(body.draft_id, user)
        existing = self.inquiries.ticket(inquiry.id)
        if existing is not None:
            return self.to_ticket(existing, inquiry), False
        if draft.status != "EDITING":
            raise draft_not_editable(draft)
        if not same_time(body.draft_updated_at, draft.updated_at):
            raise AppError(ErrorCode.DRAFT_RECONFIRM_REQUIRED, [{
                "reason": "DRAFT_UPDATED_AT", "message": "현재 초안 수정 시각",
                "value": datetime_utils.to_kst(draft.updated_at).isoformat() if draft.updated_at else None,
            }])
        if not draft.summary:
            raise field_error(ErrorCode.VALIDATION_ERROR, "summary", "REQUIRED", "문의 요약을 입력해 주세요.")

        try:
            ticket = self.save_ticket(inquiry, draft, user)
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("접수 저장 실패 draft_id=%s", draft.id)
            raise AppError(ErrorCode.TICKET_SAVE_FAILED)
        return self.to_ticket(ticket, inquiry), True

    def save_ticket(self, inquiry: Inquiry, draft: TicketDraft, user: User) -> Ticket:
        """접수·초안·문의·세션과 연동 작업·배정 이력·감사 로그를 한 트랜잭션으로 저장한다."""
        now = datetime_utils.now()
        ticket = self.tickets.add(Ticket(
            receipt_no=f"PENDING-{draft.id}",          # id 를 받은 뒤 접수번호로 바꾼다
            draft_id=draft.id,
            inquiry_id=inquiry.id,
            session_id=draft.session_id,
            summary=draft.summary,
            target_system=draft.target_system,
            symptom=draft.symptom,
            occurred_at=draft.occurred_at,
            category_code=draft.category_code,
            inquiry_type_id=draft.inquiry_type_id,
            urgency=draft.urgency,
            urgency_reason=draft.urgency_reason,
            business_impact=draft.business_impact,
            tried_actions=draft.tried_actions,
            group_id=draft.recommended_group_id,
            jira_sync_status="PENDING",
            assign_status="PENDING",
        ))
        ticket.receipt_no = f"RCPT-{ticket.id:04d}"
        draft.status = "CONFIRMED"
        inquiry.status = "RECEIVED"
        inquiry.updated_at = now
        end_session(self.inquiries.ref(ChatSession, draft.session_id), now, "HANDED_OFF")
        enqueue_jira_create(self.db, ticket)
        self.tickets.add(AssignmentLog(
            ticket_id=ticket.id, event="RECOMMEND", group_id=ticket.group_id,
            reason="세부 유형 기본 그룹" if ticket.inquiry_type_id else TRIAGE_REASON,
        ))
        self.audit_logs.add("CONFIRM", "ticket", ticket.id, result=ticket.receipt_no, actor_id=user.id)
        self.db.commit()
        return ticket

    def list_tickets(self, query: TicketListQuery, viewer: User) -> Page[TicketSummary]:
        """TK-05. view 로 범위를 정하고 나머지 조건은 그 범위 안에서 거른다."""
        view = query.view or DEFAULT_TICKET_VIEW[viewer.service_role]
        if viewer.service_role not in TICKET_VIEW_ROLES[view]:
            raise AppError(ErrorCode.FORBIDDEN)
        if query.created_from and query.created_to and query.created_from > query.created_to:
            raise AppError(ErrorCode.INVALID_REQUEST)

        rows, total = self.tickets.search(
            requester_id=viewer.id if view == "REQUESTER" else None,
            member_id=viewer.id if view == "ASSIGNED" else None,
            work_statuses=query.work_status,
            jira_sync_statuses=query.jira_sync_status,
            assign_statuses=query.assign_status,
            needs_admin=query.needs_admin,
            category_codes=query.category_code,
            urgencies=query.urgency,
            group_id=query.group_id,
            assignee_id=query.assignee_id,
            created_from=datetime_utils.kst_start(query.created_from) if query.created_from else None,
            created_before=datetime_utils.kst_start(query.created_to + timedelta(days=1)) if query.created_to else None,
            q=query.q or None,
            sort=parse_sort(query.sort),
            offset=query.offset,
            limit=query.size,
        )
        items = [
            TicketSummary(
                id=ticket.id,
                receipt_no=ticket.receipt_no,
                jira_key=ticket.jira_key,
                inquiry_id=ticket.inquiry_id,
                requester=UserRef.model_validate(requester),
                summary=ticket.summary,
                category=CategoryRef.model_validate(category) if category else None,
                urgency=ticket.urgency,
                group=GroupRef.model_validate(group) if group else None,
                assignee=UserRef.model_validate(assignee) if assignee else None,
                jira_sync_status=ticket.jira_sync_status,
                assign_status=ticket.assign_status,
                work_status=ticket.work_status,
                requested_work_status=None,
                transition_status="IDLE",
                work_status_confirmed_at=None,
                needs_admin=needs_admin(ticket),
                display_status=ticket_display_status(ticket),
                created_at=ticket.created_at,
            )
            for ticket, requester, category, group, assignee in rows
        ]
        return Page.of(items, query.page, query.size, total)

    def get_ticket(self, ticket_id: int, viewer: User) -> TicketView:
        """TK-06."""
        ticket, inquiry = self.find_viewable(ticket_id, viewer)
        return self.to_ticket(ticket, inquiry)

    def status_history(self, ticket_id: int, viewer: User) -> ItemList[StatusHistory]:
        """TK-08."""
        ticket, _ = self.find_viewable(ticket_id, viewer)
        return ItemList(items=[
            StatusHistory(
                id=h.id,
                ticket_id=h.ticket_id,
                from_status=h.from_status,
                to_status=h.to_status,
                source=h.source,
                actor_id=h.actor_id,
                actor=UserRef.model_validate(actor) if actor else None,
                reason=h.reason,
                changed_at=h.changed_at,
            )
            for h, actor in self.tickets.status_history(ticket.id)
        ])

    def find_viewable(self, ticket_id: int, viewer: User) -> tuple[Ticket, Inquiry]:
        ticket = self.tickets.get(ticket_id)
        inquiry = self.inquiries.get(ticket.inquiry_id) if ticket else None
        if inquiry is None or not can_view_inquiry(self.inquiries, inquiry, ticket, viewer):
            raise AppError(ErrorCode.TICKET_NOT_FOUND)
        return ticket, inquiry

    def lock_own_draft(self, draft_id: int, user: User) -> tuple[Inquiry, TicketDraft]:
        """문의 → 초안 순으로 잠근다 (TK-04 처리 1)."""
        draft = self.tickets.get_draft(draft_id)
        inquiry = self.inquiries.get_for_update(draft.inquiry_id) if draft else None
        if inquiry is None or inquiry.user_id != user.id:
            raise AppError(ErrorCode.DRAFT_NOT_FOUND)
        return inquiry, self.tickets.get_draft_for_update(draft_id)

    def to_draft(self, draft: TicketDraft) -> TicketDraftView:
        category = self.inquiries.ref(Category, draft.category_code)
        inquiry_type = self.inquiries.ref(InquiryType, draft.inquiry_type_id)
        group = self.inquiries.ref(SupportGroup, draft.recommended_group_id)
        return TicketDraftView(
            id=draft.id,
            inquiry_id=draft.inquiry_id,
            session_id=draft.session_id,
            summary=draft.summary,
            target_system=draft.target_system,
            symptom=draft.symptom,
            occurred_at=draft.occurred_at,
            category_code=draft.category_code,
            category=CategoryRef.model_validate(category) if category else None,
            inquiry_type_id=draft.inquiry_type_id,
            inquiry_type=InquiryTypeRef.model_validate(inquiry_type) if inquiry_type else None,
            urgency=draft.urgency,
            urgency_reason=draft.urgency_reason,
            business_impact=draft.business_impact,
            tried_actions=draft.tried_actions,
            recommended_group_id=draft.recommended_group_id,
            recommended_group=GroupRef.model_validate(group) if group else None,
            status=draft.status,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    def to_ticket(self, ticket: Ticket, inquiry: Inquiry) -> TicketView:
        requester = self.inquiries.ref(User, inquiry.user_id)
        category = self.inquiries.ref(Category, ticket.category_code)
        inquiry_type = self.inquiries.ref(InquiryType, ticket.inquiry_type_id)
        group = self.inquiries.ref(SupportGroup, ticket.group_id)
        assignee = self.inquiries.ref(User, ticket.assignee_id)
        return TicketView(
            id=ticket.id,
            receipt_no=ticket.receipt_no,
            draft_id=ticket.draft_id,
            inquiry_id=ticket.inquiry_id,
            session_id=ticket.session_id,
            requester=UserRef.model_validate(requester),
            summary=ticket.summary,
            target_system=ticket.target_system,
            symptom=ticket.symptom,
            occurred_at=ticket.occurred_at,
            category_code=ticket.category_code,
            category=CategoryRef.model_validate(category) if category else None,
            inquiry_type_id=ticket.inquiry_type_id,
            inquiry_type=InquiryTypeRef.model_validate(inquiry_type) if inquiry_type else None,
            urgency=ticket.urgency,
            urgency_reason=ticket.urgency_reason,
            business_impact=ticket.business_impact,
            tried_actions=ticket.tried_actions,
            group_id=ticket.group_id,
            group=GroupRef.model_validate(group) if group else None,
            assignee_id=ticket.assignee_id,
            assignee=UserRef.model_validate(assignee) if assignee else None,
            jira_key=ticket.jira_key,
            jira_url=jira_url(ticket.jira_key),
            jira_sync_status=ticket.jira_sync_status,
            assign_status=ticket.assign_status,
            work_status=ticket.work_status,
            # 상태 변경 요청 칸(docs/06 v0.8)은 아직 테이블에 없어 최초 접수 값으로 준다
            requested_work_status=None,
            transition_status="IDLE",
            work_status_confirmed_at=None,
            resolution_confirmed_at=None,
            needs_admin=needs_admin(ticket),
            display_status=display_status(inquiry, ticket),
            resolution_note=ticket.resolution_note,
            created_at=ticket.created_at,
            finished_at=ticket.finished_at,
            closed_at=ticket.closed_at,
        )


TicketServiceDep = Annotated[TicketService, Depends(TicketService)]


def facts_fields(facts: Facts | None) -> dict:
    """초안에 옮길 확인 항목. AI 요약(facts.summary)이 비었으면 null 로 두고 사용자가 채운다."""
    if facts is None:
        return {}
    return {
        "summary": facts.summary or None,
        "target_system": facts.target_system,
        "symptom": facts.symptom,
        "occurred_at": facts.occurred_at,
        "business_impact": facts.business_impact,
        "tried_actions": ", ".join(facts.tried_actions) or None,
    }


def suggested_urgency(assessment: InquiryAssessment | None) -> str | None:
    """AI 가 처음 제안한 긴급도. 안전 기본값으로 처리된 판단이면 없다."""
    return (assessment.ai_output or {}).get("urgency_suggested") if assessment else None


def same_time(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return a is b
    return datetime_utils.as_utc(a) == datetime_utils.as_utc(b)


def draft_not_editable(draft: TicketDraft) -> AppError:
    return AppError(ErrorCode.DRAFT_NOT_EDITABLE, [
        {"reason": "CURRENT_STATUS", "message": "현재 상태", "value": draft.status},
    ])


def needs_admin(ticket: Ticket) -> bool:
    """생성·배정 중 하나라도 관리자 확인이 필요하다. 상태 변경 확인(transition_status)은 칸이 생기면 더한다."""
    return "NEEDS_ADMIN" in (ticket.jira_sync_status, ticket.assign_status)


def jira_url(jira_key: str | None) -> str | None:
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    return f"{base}/browse/{jira_key}" if base and jira_key else None
