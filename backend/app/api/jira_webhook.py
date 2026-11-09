import json

from fastapi import APIRouter, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_jira_webhook_secret
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.integrations.jira.webhook import WebhookError, parse_jira_webhook, verify_hub_signature
from app.services.jira_webhook import record_webhook_event

# Jira 웹훅 (TK-13). 로그인 대신 서명으로 확인한다
router = APIRouter(tags=["jira-webhook"])


@router.post("/webhooks/jira", status_code=status.HTTP_204_NO_CONTENT)
async def receive_jira_webhook(request: Request, db: DbSession) -> Response:
    body = await request.body()     # 서명은 받은 그대로의 바이트로 확인한다
    if not verify_hub_signature(body, request.headers.get("X-Hub-Signature"), get_jira_webhook_secret()):
        raise AppError(ErrorCode.WEBHOOK_SIGNATURE_INVALID)
    try:
        event = parse_jira_webhook(json.loads(body), delivery_id=request.headers.get("X-Atlassian-Webhook-Identifier"))
    except (ValueError, WebhookError) as error:
        raise AppError(ErrorCode.INVALID_REQUEST) from error
    await run_in_threadpool(record_webhook_event, db, event)   # 본문을 읽느라 async 라서 DB 호출을 스레드로 넘긴다
    return Response(status_code=status.HTTP_204_NO_CONTENT)
