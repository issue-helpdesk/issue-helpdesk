from fastapi import FastAPI

from app import __version__
from app.api import auth, health, inquiries, users
from app.core.errors import register_error_handlers

app = FastAPI(
    title="Issue Helpdesk API",
    version=__version__
)
register_error_handlers(app)

API_VERSION_V1 = "/api/v1"
app.include_router(health.router, prefix=API_VERSION_V1)
app.include_router(auth.router, prefix=API_VERSION_V1)
app.include_router(users.router, prefix=API_VERSION_V1)
app.include_router(inquiries.router, prefix=API_VERSION_V1)
