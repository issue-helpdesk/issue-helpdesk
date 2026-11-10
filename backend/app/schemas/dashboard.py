from datetime import date as Date
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.common import CamelModel, KstDatetime

Interval = Literal["DAY", "WEEK", "MONTH"]


class PeriodQuery(CamelModel):
    model_config = ConfigDict(extra="ignore")

    from_: Date | None = Field(None, alias="from")
    to: Date | None = None


class TrendQuery(PeriodQuery):
    interval: Interval = "DAY"


class Period(CamelModel):
    from_: Date = Field(alias="from")
    to: Date


class TrendPeriod(Period):
    interval: Interval


class WorkCounts(CamelModel):
    rdy: int = 0
    wip: int = 0
    fin: int = 0
    cls: int = 0


class OverviewTotals(CamelModel):
    inquiry_count: int
    ai_resolved_count: int
    unconfirmed_count: int
    unresolved_count: int
    ticket_count: int
    received_count: int
    in_progress_count: int
    awaiting_confirm_count: int
    closed_count: int
    needs_admin_count: int


class CategoryCounts(CamelModel):
    category_code: str
    name: str
    inquiry_count: int = 0
    ai_resolved_count: int = 0
    ticket_count: int = 0
    closed_count: int = 0


class UrgencyCount(CamelModel):
    urgency: str
    ticket_count: int


class GroupCounts(WorkCounts):
    group_id: int
    name: str


class MemberCounts(WorkCounts):
    user_id: int
    name: str
    group_id: int
    oldest_wip_since: KstDatetime | None = None     # 지금 처리 중인 접수 중 가장 오래된 WIP 시작 시각. 선택 기간과 무관


class OverviewTrend(CamelModel):
    date: Date
    inquiry_count: int = 0
    ai_resolved_count: int = 0
    ticket_count: int = 0
    closed_count: int = 0


class Overview(CamelModel):
    period: TrendPeriod
    totals: OverviewTotals
    by_category: list[CategoryCounts]
    by_urgency: list[UrgencyCount]
    by_group: list[GroupCounts]
    by_member: list[MemberCounts]
    trend: list[OverviewTrend]


class MyGroupMember(WorkCounts):
    user_id: int
    name: str


class MyGroup(WorkCounts):
    group_id: int
    name: str
    members: list[MyGroupMember]


class MyDashboard(CamelModel):
    period: Period
    me: WorkCounts
    groups: list[MyGroup]


class AiUsageTotals(CamelModel):
    ai_consultation_count: int
    ai_resolved_count: int
    ai_resolved_rate: float
    call_count: int
    failed_count: int
    avg_latency_ms: int | None          # 응답 시간이 남은 호출이 없으면 null
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    unpriced_models: list[str]          # 단가가 없어 estimated_cost 에서 빠진 모델
    budget: float | None
    budget_usage_rate: float | None


class PurposeUsage(CamelModel):
    purpose: str
    call_count: int
    failed_count: int
    avg_latency_ms: int | None
    input_tokens: int
    output_tokens: int


class ModelUsage(CamelModel):
    model: str
    adapter: str
    call_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost: float | None        # 단가가 없으면 null


class AiUsageTrend(CamelModel):
    date: Date
    ai_consultation_count: int = 0
    ai_resolved_count: int = 0
    call_count: int = 0
    estimated_cost: float = 0


class AiUsage(CamelModel):
    period: TrendPeriod
    totals: AiUsageTotals
    by_purpose: list[PurposeUsage]
    by_model: list[ModelUsage]
    trend: list[AiUsageTrend]
