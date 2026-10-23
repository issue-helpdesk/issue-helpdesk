from fastapi import FastAPI

from app import __version__
from app.api import health

app = FastAPI(
    title="Issue Helpdesk API",
    version=__version__
)

API_VERSION_V1 = "/api/v1"
app.include_router(health.router, prefix=API_VERSION_V1)
