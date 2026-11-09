import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app import __version__
from app.agent.sensitive import install_log_filter
from app.api import (
    audit_logs,
    auth,
    dashboard,
    documents,
    faqs,
    guide_clusters,
    guide_images,
    health,
    inquiries,
    jira_webhook,
    notifications,
    reference,
    security_alerts,
    tickets,
    time_off,
    users,
)
from app.core.config import check_startup_settings
from app.core.errors import register_error_handlers
from app.core.upload_limit import UploadLimitMiddleware
from app.rag.search import runtime as search_runtime
from app.services.document_ingest import resume_periodically, submit_cleanup, submit_resume

install_log_filter()    # uvicorn 은 앱을 불러오기 전에 로그를 설정하므로 여기서 불러도 된다


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_startup_settings()
    # EMBEDDING_PRELOAD=true 면 임베딩 모델을 미리 연다 (EC2 약 28초). 꺼져 있으면 첫 검색 때 연다
    search_runtime.preload()
    submit_cleanup()
    # 모델이 있는 서버에서만 멈춘 문서 적재를 잇는다. 모델 없는 개발 PC 는 건너뛴다
    resume_task = None
    if search_runtime.preload_enabled():
        submit_resume()
        resume_task = asyncio.create_task(resume_periodically())
    yield
    if resume_task is not None:
        resume_task.cancel()
        with suppress(asyncio.CancelledError):
            await resume_task


app = FastAPI(
    title="Issue Helpdesk API",
    version=__version__,
    lifespan=lifespan,
)
register_error_handlers(app)
app.add_middleware(UploadLimitMiddleware)

API_VERSION_V1 = "/api/v1"
app.include_router(health.router, prefix=API_VERSION_V1)
app.include_router(auth.router, prefix=API_VERSION_V1)
app.include_router(users.router, prefix=API_VERSION_V1)
app.include_router(inquiries.router, prefix=API_VERSION_V1)
app.include_router(reference.router, prefix=API_VERSION_V1)
app.include_router(tickets.router, prefix=API_VERSION_V1)
app.include_router(documents.router, prefix=API_VERSION_V1)
app.include_router(guide_images.router, prefix=API_VERSION_V1)
app.include_router(guide_clusters.router, prefix=API_VERSION_V1)
app.include_router(faqs.router, prefix=API_VERSION_V1)
app.include_router(time_off.router, prefix=API_VERSION_V1)
app.include_router(jira_webhook.router, prefix=API_VERSION_V1)
app.include_router(notifications.router, prefix=API_VERSION_V1)
app.include_router(dashboard.router, prefix=API_VERSION_V1)
app.include_router(audit_logs.router, prefix=API_VERSION_V1)
app.include_router(security_alerts.router, prefix=API_VERSION_V1)
