from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import auth, documents, faqs, health, inquiries, jira_webhook, notifications, reference, tickets, time_off, users
from app.core.errors import register_error_handlers
from app.core.upload_limit import UploadLimitMiddleware
from app.rag.search import runtime as search_runtime
from app.services.document_ingest import submit_resume


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # EMBEDDING_PRELOAD=true 면 임베딩 모델을 미리 연다 (EC2 약 28초). 꺼져 있으면 첫 검색 때 연다
    search_runtime.preload()
    # 모델이 있는 서버에서만 멈춘 문서 적재를 잇는다. 모델 없는 개발 PC 는 건너뛴다
    if search_runtime.preload_enabled():
        submit_resume()
    yield


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
app.include_router(faqs.router, prefix=API_VERSION_V1)
app.include_router(time_off.router, prefix=API_VERSION_V1)
app.include_router(jira_webhook.router, prefix=API_VERSION_V1)
app.include_router(notifications.router, prefix=API_VERSION_V1)
