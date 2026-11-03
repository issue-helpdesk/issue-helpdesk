"""문서 업로드(DC-07)가 크기 제한을 넘으면 본문을 끝까지 받지 않고 멈춘다.

FastAPI 는 라우터에 넘기기 전에 업로드를 끝까지 받아 임시 파일에 쓴다. 그래서 그 앞에서 받은 양을 센다.
요청에는 파일 말고 폼 값도 들어가므로 여유를 둔다. 파일 크기가 정확히 넘는지는 services/document.save_file 이 본다.
"""
import re

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.constants import file as file_constants
from app.core.error_codes import ErrorCode
from app.core.errors import error_response

UPLOAD_PATH = re.compile(r"^/api/v1/documents/\d+/versions/?$")


class _BodyTooLarge(Exception):
    pass


class UploadLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or not UPLOAD_PATH.match(scope["path"]):
            await self.app(scope, receive, send)
            return

        limit = file_constants.MAX_DOCUMENT_FILE_MB * 1024 * 1024 + file_constants.FORM_MARGIN_BYTES
        request = Request(scope)
        if declared_size(request) > limit:          # 헤더만 보고 본문을 받기 전에 끝낸다
            await too_large(request)(scope, receive, send)
            return

        received, exceeded, started = 0, False, False

        async def counted_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:                # 헤더가 없거나 틀려도 넘는 순간 멈춘다
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if not exceeded:                        # 멈춘 뒤 앱이 만든 오류 응답은 버리고 아래 안내를 보낸다
                started = True
                await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await too_large(request)(scope, receive, send)


def declared_size(request: Request) -> int:
    value = request.headers.get("content-length", "")
    return int(value) if value.isdigit() else 0


def too_large(request: Request):
    return error_response(request, ErrorCode.DOCUMENT_FILE_TOO_LARGE, [
        {"field": "file", "reason": "OUT_OF_RANGE", "message": "최대 크기", "value": f"{file_constants.MAX_DOCUMENT_FILE_MB}MB"},
    ])
