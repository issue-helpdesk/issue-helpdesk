"""운영 집계 (OP-01~03). 공통 규칙은 API 05 2.1. 문의는 inquiries.created_at, 접수는 tickets.created_at 기준으로 기간을 나눈다."""
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends

from app.constants import llm as llm_constants
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.models import User
from app.repositories.dashboard import DashboardRepositoryDep, LlmRow, TicketRow
from app.schemas.dashboard import (
    AiUsage,
    AiUsageTotals,
    AiUsageTrend,
    CategoryCounts,
    GroupCounts,
    MemberCounts,
    ModelUsage,
    MyDashboard,
    MyGroup,
    MyGroupMember,
    Overview,
    OverviewTotals,
    OverviewTrend,
    Period,
    PeriodQuery,
    PurposeUsage,
    TrendPeriod,
    TrendQuery,
    UrgencyCount,
    WorkCounts,
)
from app.utils import datetime_utils

DEFAULT_DAYS = 30
MAX_SPAN_DAYS = 365         # to - from. 양 끝을 포함해 윤년도 1년으로 받는다
URGENCIES = ("P1", "P2", "P3", "P4")
WORK_FIELDS = {"RDY": "rdy", "WIP": "wip", "FIN": "fin", "CLS": "cls"}


class DashboardService:
    def __init__(self, dashboard: DashboardRepositoryDep) -> None:
        self.dashboard = dashboard

    def overview(self, query: TrendQuery) -> Overview:
        """OP-01."""
        start, end = resolve_period(query)
        inquiries = self.dashboard.inquiries(*kst_range(start, end))
        tickets = self.dashboard.tickets(*kst_range(start, end))
        statuses = Counter(i.status for i in inquiries)
        works = Counter(t.work_status for t in tickets)

        trend = {d: OverviewTrend(date=d) for d in bucket_dates(start, end, query.interval)}
        by_category = {code: CategoryCounts(category_code=code, name=name) for code, name in self.dashboard.categories().items()}
        for i in inquiries:
            bucket = trend[bucket_of(i.created_at, start, query.interval)]
            bucket.inquiry_count += 1
            category = by_category.get(i.category_code)
            if category:
                category.inquiry_count += 1
            if i.status == "AI_RESOLVED":
                bucket.ai_resolved_count += 1
                if category:
                    category.ai_resolved_count += 1
        for t in tickets:
            bucket = trend[bucket_of(t.created_at, start, query.interval)]
            bucket.ticket_count += 1
            category = by_category.get(t.category_code)
            if category:
                category.ticket_count += 1
            if t.work_status == "CLS":
                bucket.closed_count += 1
                if category:
                    category.closed_count += 1

        urgencies = Counter(t.urgency for t in tickets)
        return Overview(
            period=TrendPeriod(from_=start, to=end, interval=query.interval),
            totals=OverviewTotals(
                inquiry_count=len(inquiries),
                ai_resolved_count=statuses["AI_RESOLVED"],
                unconfirmed_count=sum(i.display_status == "unconfirmed" for i in inquiries),
                unresolved_count=statuses["CLOSED_UNRESOLVED"],
                ticket_count=len(tickets),
                received_count=statuses["RECEIVED"],
                in_progress_count=works["WIP"],
                awaiting_confirm_count=works["FIN"],
                closed_count=works["CLS"],
                needs_admin_count=sum(t.needs_admin for t in tickets),
            ),
            by_category=list(by_category.values()),
            by_urgency=[UrgencyCount(urgency=u, ticket_count=urgencies[u]) for u in URGENCIES],
            by_group=self.group_counts(tickets),
            by_member=self.member_counts(tickets),
            trend=list(trend.values()),
        )

    def group_counts(self, tickets: list[TicketRow]) -> list[GroupCounts]:
        """활성 그룹은 접수가 없어도 보여 주고, 비활성 그룹은 접수가 있을 때만 보여 준다."""
        counts = count_by(tickets, lambda t: t.group_id)
        return [
            GroupCounts(group_id=group_id, name=name, **counts.get(group_id, {}))
            for group_id, (name, active) in self.dashboard.groups().items()
            if active or group_id in counts
        ]

    def member_counts(self, tickets: list[TicketRow]) -> list[MemberCounts]:
        """이름 순 (순위 아님). 구성원에서 빠졌어도 맡았던 접수가 있으면 보여 준다."""
        counts = count_by(tickets, lambda t: (t.group_id, t.assignee_id) if t.group_id and t.assignee_id else None)
        names = {(m.group_id, m.user_id): m.name for m in self.dashboard.active_members()}
        former = self.dashboard.user_names({user_id for pair in counts if pair not in names for user_id in pair[1:]})
        for pair in counts:
            names.setdefault(pair, former.get(pair[1], ""))
        rows = [MemberCounts(user_id=user_id, name=name, group_id=group_id, **counts.get((group_id, user_id), {}))
                for (group_id, user_id), name in names.items()]
        return sorted(rows, key=lambda m: (m.name, m.group_id, m.user_id))

    def me(self, query: PeriodQuery, user: User) -> MyDashboard:
        """OP-02. 내 접수와 소속 그룹 현황. 업무량 확인용이라 순위를 매기지 않는다."""
        start, end = resolve_period(query)
        tickets = self.dashboard.tickets(*kst_range(start, end))
        members = self.dashboard.active_members()
        group_names = self.dashboard.groups()
        my_groups = sorted({m.group_id for m in members if m.user_id == user.id and group_names.get(m.group_id, ("", False))[1]})
        by_group = count_by(tickets, lambda t: t.group_id)
        by_member = count_by(tickets, lambda t: (t.group_id, t.assignee_id) if t.assignee_id else None)
        return MyDashboard(
            period=Period(from_=start, to=end),
            me=WorkCounts(**count_by(tickets, lambda t: "me" if t.assignee_id == user.id else None).get("me", {})),
            groups=[
                MyGroup(
                    group_id=group_id,
                    name=group_names[group_id][0],
                    **by_group.get(group_id, {}),
                    members=[
                        MyGroupMember(user_id=m.user_id, name=m.name, **by_member.get((group_id, m.user_id), {}))
                        for m in sorted((m for m in members if m.group_id == group_id), key=lambda m: (m.name, m.user_id))
                    ],
                )
                for group_id in my_groups
            ],
        )

    def ai_usage(self, query: TrendQuery) -> AiUsage:
        """OP-03. 원본 호출 기록은 주지 않는다."""
        start, end = resolve_period(query)
        inquiries = self.dashboard.inquiries(*kst_range(start, end))
        calls = self.dashboard.llm_calls(*kst_range(start, end))

        trend = {d: AiUsageTrend(date=d) for d in bucket_dates(start, end, query.interval)}
        for i in inquiries:
            bucket = trend[bucket_of(i.created_at, start, query.interval)]
            bucket.ai_consultation_count += 1
            bucket.ai_resolved_count += i.status == "AI_RESOLVED"
        total_cost = 0.0
        for c in calls:
            bucket = trend[bucket_of(c.created_at, start, query.interval)]
            bucket.call_count += 1
            cost = call_cost(c) or 0.0
            bucket.estimated_cost += cost
            total_cost += cost
        for bucket in trend.values():
            bucket.estimated_cost = round(bucket.estimated_cost, 4)

        total_cost = round(total_cost, 4)
        resolved = sum(i.status == "AI_RESOLVED" for i in inquiries)
        budget = period_budget(start, end)
        return AiUsage(
            period=TrendPeriod(from_=start, to=end, interval=query.interval),
            totals=AiUsageTotals(
                ai_consultation_count=len(inquiries),
                ai_resolved_count=resolved,
                ai_resolved_rate=round(resolved / len(inquiries), 3) if inquiries else 0,
                call_count=len(calls),
                failed_count=sum(not c.success for c in calls),
                avg_latency_ms=avg_latency(calls),
                input_tokens=sum(c.input_tokens or 0 for c in calls),
                output_tokens=sum(c.output_tokens or 0 for c in calls),
                estimated_cost=total_cost,
                unpriced_models=sorted({c.model for c in calls if call_cost(c) is None}),
                budget=budget,
                budget_usage_rate=round(total_cost / budget, 3) if budget else None,
            ),
            by_purpose=[
                PurposeUsage(
                    purpose=purpose,
                    call_count=len(rows),
                    failed_count=sum(not c.success for c in rows),
                    avg_latency_ms=avg_latency(rows),
                    input_tokens=sum(c.input_tokens or 0 for c in rows),
                    output_tokens=sum(c.output_tokens or 0 for c in rows),
                )
                for purpose, rows in sorted(group_by(calls, lambda c: c.purpose).items())
            ],
            by_model=[
                ModelUsage(
                    model=model,
                    adapter=adapter,
                    call_count=len(rows),
                    input_tokens=sum(c.input_tokens or 0 for c in rows),
                    output_tokens=sum(c.output_tokens or 0 for c in rows),
                    estimated_cost=None if call_cost(rows[0]) is None else round(sum(call_cost(c) for c in rows), 4),
                )
                for (model, adapter), rows in sorted(group_by(calls, lambda c: (c.model, c.adapter)).items())
            ],
            trend=list(trend.values()),
        )


def resolve_period(query: PeriodQuery) -> tuple[date, date]:
    """기본 최근 30일(오늘 포함). from 만 오면 오늘까지, to 만 오면 그날까지 30일."""
    today = datetime_utils.to_kst(datetime_utils.now()).date()
    end = query.to or today
    start = query.from_ or end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end or (end - start).days > MAX_SPAN_DAYS:
        raise AppError(ErrorCode.INVALID_REQUEST)
    return start, end


def kst_range(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime_utils.kst_start(start), datetime_utils.kst_start(end + timedelta(days=1))


def bucket_dates(start: date, end: date, interval: str) -> list[date]:
    """빈 구간도 0 으로 보여 준다. 주는 시작일부터 7일씩, 월은 달력 달로 나누고 첫 구간은 시작일부터다."""
    dates, current = [], start
    while current <= end:
        dates.append(current)
        if interval == "DAY":
            current += timedelta(days=1)
        elif interval == "WEEK":
            current += timedelta(days=7)
        else:
            current = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
    return dates


def bucket_of(created_at: datetime, start: date, interval: str) -> date:
    day = datetime_utils.to_kst(created_at).date()
    if interval == "DAY":
        return day
    if interval == "WEEK":
        return start + timedelta(days=(day - start).days // 7 * 7)
    return max(day.replace(day=1), start)


def group_by(rows: Iterable, key) -> dict[Any, list]:
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


def count_by(tickets: list[TicketRow], key) -> dict[Any, dict[str, int]]:
    """키별 WorkCounts 값. 키가 None 이거나 업무 상태가 없는(Jira 생성 전) 접수는 세지 않는다."""
    counts = defaultdict(Counter)
    for t in tickets:
        k = key(t)
        if k is not None:
            counts[k]                       # 업무 상태가 없어도 접수가 있었다는 것은 남긴다
            if t.work_status in WORK_FIELDS:
                counts[k][WORK_FIELDS[t.work_status]] += 1
    return {k: dict(v) for k, v in counts.items()}


def call_cost(call: LlmRow) -> float | None:
    """호출 한 건의 추정 비용. 단가를 모르는 모델이면 None."""
    if call.adapter in llm_constants.FREE_ADAPTERS:
        return 0.0
    prices = llm_constants.MODEL_PRICES_USD_PER_MTOK.get(call.model)
    if prices is None:
        return None
    return ((call.input_tokens or 0) * prices[0] + (call.output_tokens or 0) * prices[1]) / 1_000_000


def avg_latency(calls: list[LlmRow]) -> int | None:
    values = [c.latency_ms for c in calls if c.latency_ms is not None]
    return round(sum(values) / len(values)) if values else None


def period_budget(start: date, end: date) -> float | None:
    if not llm_constants.MONTHLY_BUDGET_USD:
        return None
    days = (end - start).days + 1
    return round(llm_constants.MONTHLY_BUDGET_USD * days / llm_constants.BUDGET_MONTH_DAYS, 2)


DashboardServiceDep = Annotated[DashboardService, Depends(DashboardService)]
