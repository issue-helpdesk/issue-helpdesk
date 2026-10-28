"""별도 상태 동기화 시험 서버. Jira를 읽기만 하며 DB·상태 전환 API를 호출하지 않는다."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.integrations.jira import JiraClient, JiraError, parse_jira_webhook, verify_hub_signature
from app.integrations.jira.status_sync import WORK_STATUSES, needs_status_refresh, plan_status_sync

DEMO_SECRET = "status-lab-demo-secret-only"


@dataclass(frozen=True)
class Settings:
    mode: str
    issue_key: str
    secret: str
    base_url: str = "https://example.atlassian.net"
    email: str = "status-lab@example.invalid"
    token: str = "demo-token"
    current_status: str | None = None


def settings_from_env(mode: str, current_status: str | None = None) -> Settings:
    if current_status is not None and current_status not in WORK_STATUSES:
        raise ValueError("시험용 현재 상태는 RDY/WIP/FIN/CLS 중 하나여야 합니다.")
    if mode == "mock":
        return Settings(mode, "ITHD-DEMO", DEMO_SECRET, current_status=current_status)
    if mode != "real":
        raise ValueError("mode는 mock 또는 real이어야 합니다.")
    names = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "LAB_ISSUE_KEY", "LAB_WEBHOOK_SECRET")
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    if missing:
        raise ValueError("설정 누락: " + ", ".join(missing))
    base = os.environ["JIRA_BASE_URL"].strip().rstrip("/")
    url = urlparse(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError("JIRA_BASE_URL은 경로 없는 https 사이트 주소여야 합니다.")
    secret = os.environ["LAB_WEBHOOK_SECRET"]
    if len(secret) < 32:
        raise ValueError("웹훅 비밀값은 32자 이상이어야 합니다.")
    return Settings(mode, os.environ["LAB_ISSUE_KEY"].strip(), secret, base,
                    os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"], current_status)


def mock_jira(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/rest/api/3/issue/ITHD-DEMO":
        return httpx.Response(200, json={"fields": {"status": {"id": "10005", "name": "WIP"}}})
    return httpx.Response(404, json={"errorMessages": ["시험 경로 없음"]})


def create_app(settings: Settings, transport: httpx.BaseTransport | None = None) -> FastAPI:
    if settings.mode == "mock" and transport is None:
        transport = httpx.MockTransport(mock_jira)
    app = FastAPI(title="Jira 상태 동기화 시험", docs_url=None, redoc_url=None)

    def resolve(event):
        with JiraClient(settings.base_url, settings.email, settings.token, transport=transport) as jira:
            latest = jira.get_work_status(event.issue_key)
        return plan_status_sync(event, latest, current_work_status=settings.current_status)

    @app.get("/health")
    def health():
        return {"ok": True, "mode": settings.mode, "feature": "status_sync", "db_updated": False}

    @app.post("/api/v1/webhooks/jira")
    async def receive(request: Request):
        body = await request.body()
        if not verify_hub_signature(body, request.headers.get("X-Hub-Signature"), settings.secret):
            raise HTTPException(403, detail="bad_signature")
        try:
            event = parse_jira_webhook(json.loads(body), delivery_id=request.headers.get("X-Atlassian-Webhook-Identifier"))
        except (ValueError, TypeError, UnicodeDecodeError):
            raise HTTPException(400, detail="invalid_webhook") from None
        if event.issue_key != settings.issue_key:
            return {"ok": True, "mode": settings.mode, "reason": "ignored_issue", "db_updated": False}
        try:
            plan = await run_in_threadpool(resolve, event) if needs_status_refresh(event) else plan_status_sync(event, None)
        except JiraError as exc:
            raise HTTPException(502, detail={"reason": exc.reason, "retryable": exc.retryable}) from None
        return {"ok": True, "mode": settings.mode, "status_changed": needs_status_refresh(event),
                **asdict(plan), "db_updated": False}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "real"), default="mock")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--current-status", choices=sorted(WORK_STATUSES), help="DB 대신 사용하는 시험용 현재값. DB에서는 읽지 않음")
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("설정 파일이 없습니다.")
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    try:
        settings = settings_from_env(args.mode, args.current_status)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
