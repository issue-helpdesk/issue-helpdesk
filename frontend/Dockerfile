# 프론트 이미지: Vite 로 빌드한 정적 파일을 nginx 가 내보내고, /api 는 백엔드로 넘긴다.
#   docker build -t issue-helpdesk-web frontend

FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# VITE_ 값은 빌드할 때 코드에 박힌다. 바꾸면 다시 빌드해야 한다
ARG VITE_API_BASE_URL=/api/v1
# backend API 연결 작업 다 끝나면 false. 아직 일부분만 이루어져있어 true
ARG VITE_USE_MOCK=false
# 영역별로 따로 정하고 싶을 때만 값을 준다. 비워 두면 VITE_USE_MOCK 을 따른다
ARG VITE_USE_MOCK_AUTH=false
ARG VITE_USE_MOCK_INQUIRY=false
ARG VITE_USE_MOCK_TICKET=false
ARG VITE_USE_MOCK_FAQ=false
ARG VITE_USE_MOCK_GUIDE=false
ARG VITE_USE_MOCK_OPS=false
# 서버 모드에서 접수·해결 확인을 서버로 보낼지(true 일 때만). Jira 작업 실행기가 떠 있는 환경에서만 켠다
ARG VITE_SERVER_INTAKE=true
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_USE_MOCK=$VITE_USE_MOCK \
    VITE_USE_MOCK_AUTH=$VITE_USE_MOCK_AUTH \
    VITE_USE_MOCK_INQUIRY=$VITE_USE_MOCK_INQUIRY \
    VITE_USE_MOCK_TICKET=$VITE_USE_MOCK_TICKET \
    VITE_USE_MOCK_FAQ=$VITE_USE_MOCK_FAQ \
    VITE_USE_MOCK_GUIDE=$VITE_USE_MOCK_GUIDE \
    VITE_USE_MOCK_OPS=$VITE_USE_MOCK_OPS \
    VITE_SERVER_INTAKE=$VITE_SERVER_INTAKE

COPY . .
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
