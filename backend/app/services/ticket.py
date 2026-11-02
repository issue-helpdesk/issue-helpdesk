"""접수 초안·최종 접수 (TK-01~04). 초안은 문의자가 고치고, 접수 확정 뒤 Jira 생성은 연동 작업이 한다."""
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.agent.flow.urgency import urgency_of
from app.agent.llm import Facts, safe_default
from app.agent.sensitive import MASK_NOTICE_DRAFT, mask_secrets
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
    AssignmentLog as AssignmentLogView,
    AssignmentRequest,
    DraftChange,
    DraftUpdateRequest,
    DraftUpdateResult,
    IntegrationJob as IntegrationJobView,
    StatusHistory,
    Ticket as TicketView,
    TicketCreateRequest,
    TicketDraft as TicketDraftView,
    TicketListQuery,
    TicketSummary,
    TicketUpdateRequest,
)
from app.services.ai_responder import facts_of, type_info
from app.services.inquiry import can_view_inquiry, close_unresolved, end_session, invalid_state, record_sensitive_input
from app.services.inquiry_status import CLOSED_STATUSES, display_status, ticket_display_status
from app.services.assignment import AssigneeNotAssignable, reserve_assignment
from app.services.jira_create import enqueue_jira_create
from app.services.jira_transition import enqueue_jira_transition
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

TRIAGE_REASON = "서비스데스크 확인"
# 허용하는 업무 상태 변경 (API 03 1.3). 누가 요청할 수 있는지는 required_role()
TRANSITIONS = {("RDY", "WIP"), ("WIP", "FIN"), ("FIN", "CLS"), ("FIN", "WIP")}
NOTE_EDITABLE = ("WIP", "FIN")            # 처리 결과만 고칠 수 있는 상태


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

        # 사용자가 고친 글은 가려서 저장한다 (docs/10 4장 ②)
        masked_counts: Counter[str] = Counter()
        for name in sent - {"inquiry_type_id"}:
            value = getattr(body, name)
            if value is not None:
                masked = mask_secrets(value)
                value = masked.text
                masked_counts.update(masked.counts)
            setattr(draft, name, value)
        record_sensitive_input(self.audit_logs, inquiry.id, user, dict(masked_counts))
        changes = []
        if "inquiry_type_id" in sent and body.inquiry_type_id != draft.inquiry_type_id:
            changes = self.reclassify(inquiry, draft, new_type)
        if sent:
            draft.updated_at = datetime_utils.now()
        self.db.commit()
        return DraftUpdateResult(draft=self.to_draft(draft), changes=changes,
                                 mask_notice=MASK_NOTICE_DRAFT if masked_counts else None)

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
                requested_work_status=ticket.requested_work_status,
                transition_status=ticket.transition_status,
                work_status_confirmed_at=ticket.work_status_confirmed_at,
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

    def request_transition(self, ticket_id: int, body: TicketUpdateRequest, user: User) -> TicketView:
        """TK-07. 상태를 바로 바꾸지 않고 요청(requested_work_status·transition_status)과 JIRA_TRANSITION 작업을 남긴다.

        검사 순서: 볼 권한(404) → 실행자(403) → Jira 연동(409) → 허용 변경(409) → 진행 중 작업(409) → 입력(422).
        """
        if body.work_status is None and body.resolution_note is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "workStatus", "REQUIRED", "변경할 상태나 처리 결과를 보내 주세요.")
        ticket = self.tickets.get_for_update(ticket_id)
        inquiry = self.inquiries.get(ticket.inquiry_id) if ticket else None
        if inquiry is None or not can_view_inquiry(self.inquiries, inquiry, ticket, user):
            raise AppError(ErrorCode.TICKET_NOT_FOUND)

        current, target = ticket.work_status, body.work_status
        is_staff = self.is_staff(ticket, user)
        if body.resolution_note is not None and not is_staff:
            raise AppError(ErrorCode.FORBIDDEN)
        if target is not None and not (is_staff if required_role(current, target) == "STAFF" else inquiry.user_id == user.id):
            raise AppError(ErrorCode.FORBIDDEN)
        if ticket.jira_sync_status != "SYNCED":
            raise AppError(ErrorCode.TICKET_NOT_SYNCED)
        if (target is not None and (current, target) not in TRANSITIONS) or (target is None and current not in NOTE_EDITABLE):
            raise AppError(ErrorCode.TICKET_INVALID_TRANSITION, [
                {"reason": "TRANSITION", "message": "요청한 변경", "value": {"from": current, "to": target or current}},
            ])
        if ticket.transition_status != "IDLE" or self.tickets.has_active_job(ticket.id, "JIRA_TRANSITION"):
            raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS, [
                {"reason": "TRANSITION_STATUS", "message": "상태 변경 작업 상태", "value": ticket.transition_status},
            ])
        if target == "FIN" and not body.resolution_note:
            # 재완료는 저장된 이전 결과가 있어도 이번 요청에 처리 결과를 받아야 한다.
            if self.tickets.has_reopened(ticket.id) or not ticket.resolution_note:
                raise field_error(ErrorCode.TICKET_RESOLUTION_NOTE_REQUIRED, "resolutionNote", "REQUIRED")
        if (current, target) == ("FIN", "WIP") and not body.reason:
            raise field_error(ErrorCode.VALIDATION_ERROR, "reason", "REQUIRED", "남은 증상을 입력해 주세요.")

        # 처리 결과·남은 증상도 사용자가 쓴 글이라 Jira 로 보내기 전에 가린다 (docs/10 4장 ②)
        masked_counts: Counter[str] = Counter()
        texts = {}
        for name in ("resolution_note", "reason"):
            value = getattr(body, name)
            if value is not None:
                masked = mask_secrets(value)
                texts[name] = masked.text
                masked_counts.update(masked.counts)
        record_sensitive_input(self.audit_logs, inquiry.id, user, dict(masked_counts))

        now = datetime_utils.now()
        ticket.requested_work_status = target
        ticket.transition_status = "PENDING"
        if target == "CLS":
            ticket.resolution_confirmed_at = now
        try:
            enqueue_jira_transition(self.db, ticket, {
                "ticketId": ticket.id,
                "receiptNo": ticket.receipt_no,
                "jiraKey": ticket.jira_key,
                "fromStatus": current,
                "toStatus": target,                        # null 이면 처리 결과만 수정
                "resolutionNote": texts.get("resolution_note"),
                "reason": texts.get("reason"),
                "requestedBy": user.id,
                "requestedAt": now.isoformat(),
                "resolutionConfirmedAt": now.isoformat() if target == "CLS" else None,
            })
            self.db.commit()
        except IntegrityError:
            self.db.rollback()                             # 같은 접수에 다른 요청이 먼저 작업을 등록했다
            raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS)
        return self.to_ticket(ticket, inquiry)

    def assign(self, ticket_id: int, body: AssignmentRequest, user: User) -> TicketView:
        """TK-09. 권한·상태·사유를 확인하고 공용 배정 함수(reserve_assignment)로 예약한다. 감사 로그·커밋은 여기서 한다.

        assigneeId 가 null 이면 그 그룹에서 자동 선정한다 (docs/11 2.4).
        """
        ticket = self.tickets.get_for_update(ticket_id)
        inquiry = self.inquiries.get(ticket.inquiry_id) if ticket else None
        if inquiry is None or not can_view_inquiry(self.inquiries, inquiry, ticket, user):
            raise AppError(ErrorCode.TICKET_NOT_FOUND)
        if not self.can_assign(ticket, body, user):
            raise AppError(ErrorCode.FORBIDDEN)
        if ticket.work_status == "CLS":
            raise AppError(ErrorCode.TICKET_INVALID_TRANSITION, [
                {"reason": "CURRENT_STATUS", "message": "현재 상태", "value": ticket.work_status},
            ])
        if self.tickets.has_active_job(ticket.id, "JIRA_ASSIGN"):
            raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS)
        if not body.reason:
            raise field_error(ErrorCode.ASSIGNMENT_REASON_REQUIRED, "reason", "REQUIRED")
        group = self.references.get_support_group(body.group_id)
        if group is None or not group.is_active:
            raise field_error(ErrorCode.VALIDATION_ERROR, "groupId", "NOT_FOUND", "활성 담당 그룹이 아닙니다.")

        try:
            reservation = reserve_assignment(self.db, ticket, group.id, reason=body.reason, actor_id=user.id,
                                             assignee_id=body.assignee_id)
        except AssigneeNotAssignable as e:
            raise field_error(ErrorCode.ASSIGNEE_NOT_ASSIGNABLE, "assigneeId", "INVALID_VALUE", str(e))
        except IntegrityError:
            self.db.rollback()                 # 같은 접수에 다른 배정 요청이 먼저 작업을 등록했다
            raise AppError(ErrorCode.INTEGRATION_JOB_IN_PROGRESS)
        self.audit_logs.add("REASSIGN", "ticket", ticket.id, result=reservation.event, actor_id=user.id,
                            reason=body.reason)
        self.db.commit()
        return self.to_ticket(ticket, inquiry)

    def can_assign(self, ticket: Ticket, body: AssignmentRequest, user: User) -> bool:
        """ADMIN 은 모두. MANAGER 는 지금 배정 그룹이 자기 그룹인 접수만, 다른 그룹으로는 자동배정으로만 넘긴다."""
        if user.service_role == "ADMIN":
            return True
        if user.service_role != "AGENT" or ticket.group_id is None:
            return False
        if not self.references.is_group_manager(ticket.group_id, user.id):
            return False
        return body.group_id == ticket.group_id or body.assignee_id is None

    def assignment_logs(self, ticket_id: int, viewer: User) -> ItemList[AssignmentLogView]:
        """TK-10. 담당 그룹·ADMIN 만. 문의자 본인도 404."""
        ticket = self.tickets.get(ticket_id)
        if ticket is None or not self.is_staff(ticket, viewer):
            raise AppError(ErrorCode.TICKET_NOT_FOUND)
        return ItemList(items=[
            AssignmentLogView(
                id=log.id,
                ticket_id=log.ticket_id,
                event=log.event,
                group_id=log.group_id,
                group=GroupRef.model_validate(group) if group else None,
                assignee_id=log.assignee_id,
                assignee=UserRef.model_validate(assignee) if assignee else None,
                rule_id=log.rule_id,
                reason=log.reason,
                actor_id=log.actor_id,
                actor=UserRef.model_validate(actor) if actor else None,
                created_at=log.created_at,
            )
            for log, group, assignee, actor in self.tickets.assignment_logs(ticket.id)
        ])

    def integration_jobs(self, ticket_id: int) -> ItemList[IntegrationJobView]:
        """TK-11. ADMIN 확인은 라우터가 한다. payload 는 내보내지 않는다."""
        if self.tickets.get(ticket_id) is None:
            raise AppError(ErrorCode.TICKET_NOT_FOUND)
        return ItemList(items=[IntegrationJobView.model_validate(job) for job in self.tickets.integration_jobs(ticket_id)])

    def is_staff(self, ticket: Ticket, user: User) -> bool:
        """ADMIN, 또는 접수 담당 그룹의 활성 구성원인 AGENT."""
        if user.service_role == "ADMIN":
            return True
        return bool(user.service_role == "AGENT" and ticket.group_id
                    and self.inquiries.is_active_group_member(user.id, ticket.group_id))

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
            requested_work_status=ticket.requested_work_status,
            transition_status=ticket.transition_status,
            work_status_confirmed_at=ticket.work_status_confirmed_at,
            resolution_confirmed_at=ticket.resolution_confirmed_at,
            needs_admin=needs_admin(ticket),
            display_status=display_status(inquiry, ticket),
            resolution_note=ticket.resolution_note,
            created_at=ticket.created_at,
            finished_at=ticket.finished_at,
            closed_at=ticket.closed_at,
        )


TicketServiceDep = Annotated[TicketService, Depends(TicketService)]


def required_role(current: str | None, target: str) -> str:
    """목표 상태를 요청할 수 있는 사람. 미해결(FIN → WIP)만 문의자가 WIP 로 되돌린다."""
    if target == "CLS" or (target == "WIP" and current == "FIN"):
        return "REQUESTER"
    return "STAFF"


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
    """생성·배정·상태 변경 중 하나라도 관리자 확인이 필요하다 (03 1.2)."""
    return "NEEDS_ADMIN" in (ticket.jira_sync_status, ticket.assign_status, ticket.transition_status)


def jira_url(jira_key: str | None) -> str | None:
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    return f"{base}/browse/{jira_key}" if base and jira_key else None
