-- ITssue HelpDesk 데이터셋 테이블 (dataset/data/ 의 CSV·JSON과 1:1)
--
-- 여러 번 실행해도 안전하다 (create ... if not exists). 데이터는 db/seed.py 가 넣는다.
-- 시각은 모두 한국 시간(KST) 그대로 저장한다 (timestamp, 시간대 없음).
-- 챗봇이 새로 만드는 문의·티켓·세션 테이블은 여기 두지 않는다. 백엔드의 Alembic 마이그레이션에서 만든다.

create extension if not exists vector;   -- RAG 임베딩용 (pgvector). 이 파일에서는 켜 두기만 한다.

-- ---------------------------------------------------------------- 분류 체계 (taxonomy.json)

create table if not exists categories (
    code        text primary key,                 -- ACC, ACS, NET, SW, HW, SYS, SEC
    name        text not null,
    scope       text not null                     -- 다루는 범위
);

create table if not exists urgency_levels (
    code         text primary key,                -- P1 ~ P4
    label        text not null,                   -- 긴급 / 높음 / 보통 / 낮음
    description  text not null,                   -- 판단 기준
    response_min integer not null,                -- 응답 목표 시간(분)
    resolve_min  integer not null                 -- 해결 목표 시간(분)
);

create table if not exists teams (
    name        text primary key,                 -- IT운영·보안 조직의 6개 담당팀
    area        text not null
);

create table if not exists channels (
    code        text primary key,                 -- 전화 / 메일 / 메신저 (ITssue 도입 전 접수 창구)
    description text not null
);

create table if not exists handling_types (
    code        text primary key,                 -- 티켓 / 즉시 처리
    description text not null
);

create table if not exists user_roles (
    role        text primary key,                 -- 일반 임직원 / IT 운영 담당자 / 관리자
    who         text not null,
    page        text not null,                    -- 쓰는 화면
    functions   text not null
);

create table if not exists assignee_roles (
    role        text primary key,                 -- L1 상담 / L2 담당 / 팀장 / 조직장
    assignable  boolean not null,
    description text not null
);

-- ---------------------------------------------------------------- FAQ (faq.csv)

create table if not exists faqs (
    faq_id        text primary key,               -- FAQ-001
    category_code text not null references categories (code),
    question      text not null,
    answer        text not null,
    keywords      text[] not null default '{}'
);

-- ---------------------------------------------------------------- 시나리오·대형 장애 (taxonomy.json)

create table if not exists scenarios (
    scenario_id     text primary key,             -- ACC-01
    category_code   text not null references categories (code),
    subcategory     text not null,
    ticket_type     text not null check (ticket_type in ('장애', '요청', '문의')),
    default_urgency text not null references urgency_levels (code),
    team            text not null references teams (name),
    manual_id       text not null,                -- MAN-01 ~ MAN-07 (dataset/manuals)
    faq_id          text references faqs (faq_id),
    impact_scope    text not null check (impact_scope in ('개인', '부서', '전사')),
    tool            text not null
);

create table if not exists major_incidents (
    incident_id  text primary key,                -- MI-2026-01
    scenario_id  text not null references scenarios (scenario_id),
    started_at   timestamp not null,
    ticket_count integer not null,
    duration_min integer not null,
    summary      text not null
);

-- ---------------------------------------------------------------- 임직원·담당자 (employees.csv, assignees.csv)

create table if not exists employees (
    emp_id            text primary key,           -- EMP-1001
    name              text not null,
    division          text not null,
    team              text not null,              -- 소속 팀 (전사 21개 팀. teams 표의 IT 담당팀과 다르다)
    job_title         text not null,
    itssue_role       text not null references user_roles (role),
    email             text not null unique,
    chat_id           text not null,
    pc_os             text not null,
    employment_status text not null
);

create table if not exists assignees (
    emp_id          text primary key references employees (emp_id),
    name            text not null unique,         -- 문의 이력의 assignee 가 이름으로 적혀 있다
    team            text not null references teams (name),
    role            text not null references assignee_roles (role),
    assignable      boolean not null,
    specialty_area  text not null,
    jira_account    text not null,
    handled_tickets integer not null,             -- 배정된 티켓 수 (즉시 처리 제외)
    open_tickets    integer not null              -- 아직 끝나지 않은 티켓 수
);

create table if not exists assignee_scenarios (   -- 담당자가 맡는 시나리오 (assignees.csv 의 scenario_ids)
    emp_id      text not null references assignees (emp_id) on delete cascade,
    scenario_id text not null references scenarios (scenario_id),
    primary key (emp_id, scenario_id)
);

-- ---------------------------------------------------------------- 과거 문의 처리 이력 (history.csv)

create table if not exists inquiry_history (
    inquiry_id      text primary key,             -- INQ-2026-00001
    created_at      timestamp not null,
    channel         text not null references channels (code),
    handling_type   text not null references handling_types (code),
    requester_id    text not null references employees (emp_id),
    requester_dept  text not null,
    ticket_type     text not null check (ticket_type in ('장애', '요청', '문의')),
    category_code   text not null references categories (code),
    category        text not null,
    subcategory     text not null,
    scenario_id     text not null references scenarios (scenario_id),
    tool            text not null,
    urgency         text not null references urgency_levels (code),
    urgency_label   text not null,
    impact_scope    text not null check (impact_scope in ('개인', '부서', '전사')),
    title           text not null,
    description     text not null,
    status          text not null check (status in ('RDY', 'WIP', 'FIN')),
    assigned_team   text not null references teams (name),
    assignee        text not null,                -- 담당자 이름 (원본 그대로)
    assignee_emp_id text not null references assignees (emp_id),   -- 이름으로 찾아 넣은 사번
    resolved_at     timestamp,                    -- 처리 중(WIP)이면 비어 있다
    root_cause      text not null,
    resolution      text not null,
    prevention      text,
    related_faq     text references faqs (faq_id)
);

create index if not exists inquiry_history_scenario_idx on inquiry_history (scenario_id);
create index if not exists inquiry_history_category_idx on inquiry_history (category_code);
create index if not exists inquiry_history_requester_idx on inquiry_history (requester_id);
create index if not exists inquiry_history_assignee_idx on inquiry_history (assignee_emp_id);
create index if not exists inquiry_history_created_idx on inquiry_history (created_at);

-- ---------------------------------------------------------------- 평가용 정답셋 (eval_inquiries.csv)
--
-- AI 검색 자료나 프롬프트 예시에 넣지 않는 데이터라 public 과 떨어진 eval 스키마에 둔다.
-- 범위 밖·모호한 문의는 정답 칸이 '-' 이므로 외래키를 걸지 않는다.
-- seed.py 는 --with-eval 을 줬을 때만 이 표를 채운다.

create schema if not exists eval;

create table if not exists eval.inquiries (
    eval_id           text primary key,           -- EV-001
    query             text not null,
    expected_category text not null,
    expected_scenario text not null,
    expected_urgency  text not null,
    expected_action   text not null,              -- ANSWER / ESCALATE / ASK_MORE / OUT_OF_SCOPE
    additional_action text not null,
    expected_team     text not null,
    team_scoring      text not null,
    label_note        text not null,
    dataset_split     text not null
);

-- ---------------------------------------------------------------- 접근 제한 (Supabase)
--
-- Supabase 는 public 스키마의 표를 anon 키로 조회·수정할 수 있는 REST API를 자동으로 만든다.
-- 행 수준 보안(RLS)을 켜고 정책을 두지 않으면 그 API로는 아무것도 읽거나 쓸 수 없다.
-- 백엔드는 DB에 직접 붙으므로(표 소유자) 영향이 없다.

alter table categories         enable row level security;
alter table urgency_levels     enable row level security;
alter table teams              enable row level security;
alter table channels           enable row level security;
alter table handling_types     enable row level security;
alter table user_roles         enable row level security;
alter table assignee_roles     enable row level security;
alter table faqs               enable row level security;
alter table scenarios          enable row level security;
alter table major_incidents    enable row level security;
alter table employees          enable row level security;
alter table assignees          enable row level security;
alter table assignee_scenarios enable row level security;
alter table inquiry_history    enable row level security;
alter table eval.inquiries     enable row level security;
