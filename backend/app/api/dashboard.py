from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth, AgentAuth
from app.schemas.dashboard import AiUsage, MyDashboard, Overview, PeriodQuery, TrendQuery
from app.services.dashboard import DashboardServiceDep

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=Overview)
def overview(query: Annotated[TrendQuery, Query()], _: AdminAuth, service: DashboardServiceDep) -> Overview:
    return service.overview(query)


@router.get("/me", response_model=MyDashboard)
def my_dashboard(query: Annotated[PeriodQuery, Query()], auth: AgentAuth, service: DashboardServiceDep) -> MyDashboard:
    return service.me(query, auth.user)


@router.get("/ai-usage", response_model=AiUsage)
def ai_usage(query: Annotated[TrendQuery, Query()], _: AdminAuth, service: DashboardServiceDep) -> AiUsage:
    return service.ai_usage(query)
