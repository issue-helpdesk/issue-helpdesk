from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import auth, health, inquiries, reference, tickets, users
from app.core.errors import register_error_handlers
from app.rag.search import runtime as search_runtime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # EMBEDDING_PRELOAD=true 면 임베딩 모델을 미리 연다 (EC2 약 28초). 꺼져 있으면 첫 검색 때 연다
    search_runtime.preload()
    yield


app = FastAPI(
    title="Issue Helpdesk API",
    version=__version__,
    lifespan=lifespan,
)
register_error_handlers(app)

API_VERSION_V1 = "/api/v1"
app.include_router(health.router, prefix=API_VERSION_V1)
app.include_router(auth.router, prefix=API_VERSION_V1)
app.include_router(users.router, prefix=API_VERSION_V1)
app.include_router(inquiries.router, prefix=API_VERSION_V1)
app.include_router(reference.router, prefix=API_VERSION_V1)
app.include_router(tickets.router, prefix=API_VERSION_V1)
