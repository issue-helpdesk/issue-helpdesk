import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode

logger = logging.getLogger(__name__)

TRACE_HEADER = "X-Request-Id"

# Pydantic 오류 type → details[].reason (5.3)
REASONS = {
    "missing": "REQUIRED",
    "string_too_short": "TOO_SHORT",
    "string_too_long": "TOO_LONG",
    "too_short": "TOO_SHORT",
    "too_long": "TOO_LONG",
    "greater_than": "OUT_OF_RANGE",
    "greater_than_equal": "OUT_OF_RANGE",
    "less_than": "OUT_OF_RANGE",
    "less_than_equal": "OUT_OF_RANGE",
    "value_error": "INVALID_FORMAT",
}
REASON_MESSAGES = {
    "REQUIRED": "필수 입력값입니다.",
    "TOO_SHORT": "입력값이 너무 짧습니다.",
    "TOO_LONG": "입력값이 너무 깁니다.",
    "OUT_OF_RANGE": "허용 범위를 벗어났습니다.",
    "INVALID_FORMAT": "형식이 올바르지 않습니다.",
    "INVALID_VALUE": "허용되지 않는 값입니다.",
}
HTTP_CODES = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    429: ErrorCode.TOO_MANY_REQUESTS,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        details: list[dict[str, Any]] | None = None,
        message: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code.name)
        self.code = code
        self.details = details
        self.message = message or code.message
        self.headers = headers


def trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", None) or request.headers.get(TRACE_HEADER) or str(uuid.uuid4())


def error_response(request: Request, code: ErrorCode, details=None, message=None, headers=None) -> JSONResponse:
    tid = trace_id(request)
    return JSONResponse(
        status_code=code.status,
        content={"error": {"code": code.name, "message": message or code.message, "details": details, "traceId": tid}},
        headers={**(headers or {}), TRACE_HEADER: tid},
    )


def field_name(loc: tuple) -> str | None:
    """('body', 'keywords', 0) → 'keywords[0]'. 요청 위치(body·query·path)는 뺀다."""
    name = ""
    for part in loc[1:]:
        name += f"[{part}]" if isinstance(part, int) else (f".{part}" if name else str(part))
    return name or None


def validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    details = []
    for err in exc.errors():
        reason = REASONS.get(err["type"], "INVALID_VALUE")
        details.append({"field": field_name(tuple(err["loc"])), "reason": reason, "message": REASON_MESSAGES[reason]})
    return details


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        request.state.trace_id = request.headers.get(TRACE_HEADER) or str(uuid.uuid4())
        response = await call_next(request)
        response.headers[TRACE_HEADER] = request.state.trace_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return error_response(request, exc.code, exc.details, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # JSON 자체를 읽지 못한 경우는 400 (5.4)
        if any(err["type"] == "json_invalid" for err in exc.errors()):
            return error_response(request, ErrorCode.INVALID_REQUEST)
        return error_response(request, ErrorCode.VALIDATION_ERROR, validation_details(exc))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        code = HTTP_CODES.get(exc.status_code, ErrorCode.INVALID_REQUEST if exc.status_code < 500 else ErrorCode.INTERNAL_ERROR)
        return error_response(request, code)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        # 원인은 응답에 넣지 않고 traceId 와 함께 서버 로그에만 남긴다
        logger.exception("처리하지 못한 오류 traceId=%s", trace_id(request))
        return error_response(request, ErrorCode.INTERNAL_ERROR)
