# FastAPI 서버 이미지. 빌드 컨텍스트는 저장소 루트 (pyproject.toml · uv.lock 이 루트에 있다)
#   docker build -f backend/Dockerfile -t issue-helpdesk-backend .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 의존성 먼저 설치한다. 코드만 바뀌면 이 층은 캐시를 그대로 쓴다.
# embedding: 검색용 임베딩 모델(torch). 리눅스에서는 pyproject 설정대로 CPU 판을 받는다
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --extra embedding --no-install-project

# config.py 가 저장소 루트를 parents[3] 으로 찾으므로 /app/backend/app 구조를 유지한다
COPY backend ./backend

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
