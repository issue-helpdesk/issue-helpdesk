"""dataset/data/ 의 CSV·JSON을 docs/06.테이블_설계서.md 의 테이블에 적재한다.

    python db/seed.py --check        # DB 없이 파일만 변환·검사 (건수, 참조, 코드 변환)
    python db/seed.py                # 적재 (다시 실행해도 같은 키는 갱신만 한다)
    python db/seed.py --reset-passwords   # 적재하면서 기존 사용자 비밀번호도 초기 비밀번호로 다시 넣는다

- 테이블은 미리 만들어 둬야 한다 (Alembic 마이그레이션). 이 스크립트는 테이블을 만들지 않는다.
- 연결 주소는 환경 변수 DATABASE_URL 또는 저장소 루트의 .env 에서 읽는다.
- 신규 사용자의 초기 비밀번호는 환경 변수 SEED_INITIAL_PASSWORD 로 받아 해시로 저장한다.
  이미 있는 사용자의 비밀번호는 --reset-passwords 를 주지 않으면 바꾸지 않는다.
- 해시는 로그인(backend/app/core/security.py)과 같은 Argon2id 이다. 예전 임시 방식(sha256$...)으로
  들어간 사용자는 로그인할 수 없으니 --reset-passwords 로 다시 넣는다.
- 평가셋(eval_inquiries.csv)은 DB에 넣지 않고 파일로 관리한다.
- FAQ는 게시판용 faqs 테이블에 넣는다. Knowledge(검색 대상)에는 넣지 않는다 (가이드 청크에 같은 FAQ가 있다).
  이미 있는 FAQ의 게시 여부(is_active)는 다시 실행해도 건드리지 않는다 (관리자가 내린 게시글을 되살리지 않는다).
- 가이드·매뉴얼(knowledge_documents·document_versions·document_chunks)은 이 스크립트가 아니라 가이드 적재 스크립트가 넣는다.
- 필요한 패키지: psycopg[binary], python-dotenv, argon2-cffi
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataset" / "data"

try:                                    # DATABASE_URL·SEED_INITIAL_PASSWORD 를 .env 에서 읽는다
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

KST = "+09:00"               # 데이터셋 시각은 한국 시간이며 시간대 표기가 없다

# ---------------------------------------------------------------- 데이터셋 값 → 설계 코드

SERVICE_ROLE = {"일반 임직원": "EMPLOYEE", "IT 운영 담당자": "AGENT", "관리자": "ADMIN"}
ACCOUNT_STATUS = {"재직": "ACTIVE"}
MEMBER_ROLE = {"L1 상담": "AGENT", "L2 담당": "AGENT", "팀장": "MANAGER", "조직장": "MANAGER"}
REQUEST_KIND = {"장애": "INCIDENT", "요청": "REQUEST", "문의": "QUESTION"}
CHANNEL = {"전화": "PHONE", "메일": "MAIL", "메신저": "MESSENGER"}
HANDLING = {"즉시 처리": "IMMEDIATE", "티켓": "TICKET"}
IMPACT = {"개인": "PERSONAL", "부서": "DEPARTMENT", "전사": "COMPANY"}
YN = {"Y": True, "N": False}
TIME_OFF_TYPES = {"ANNUAL", "HALF_AM", "HALF_PM"}

TRIAGE_GROUP = "서비스데스크"   # 담당 그룹이 불확실할 때 확인하는 그룹

# 열람 범위·외부 전송 정책 (팀 확정 전 제안값)
LEGACY_POLICY = ("ALL", "MASKED")               # 과거 사례: 문의자 정보는 넣지 않고, 본문은 마스킹 후 전송
LEGACY_POLICY_BY_CATEGORY = {"SEC": ("AGENT", "BLOCKED")}   # 보안 사고 이력은 담당자만, 외부 전송 금지

# 적재 순서 = 참조되는 테이블이 먼저
TABLES = ["departments", "users", "categories", "support_groups", "inquiry_types", "support_group_members",
          "member_skills", "faqs", "legacy_inquiries", "time_off"]


def read_csv(name):
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def blank(v):
    """빈칸과 '-' 는 값 없음으로 본다."""
    return None if v in ("", "-") else v


def kst(v):
    return f"{v}{KST}" if v else None


def hash_password(password):
    """Argon2id 해시. argon2-cffi 기본값으로 로그인 쪽 PasswordHasher 와 같다."""
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


class Plan:
    """파일을 읽어 테이블별 행(자연키 기준)으로 바꾼 결과. DB의 id는 적재할 때 붙인다."""

    def __init__(self):
        self.rows = {t: [] for t in TABLES}
        self.problems = []      # 있으면 적재하지 않는다
        self.warnings = []      # 적재는 하지만 확인이 필요한 것

    def code(self, mapping, value, where):
        if value not in mapping:
            self.problems.append(f"{where}: 변환할 수 없는 값 '{value}'")
        return mapping.get(value)

    def ref(self, keys, value, where):
        if value not in keys:
            self.problems.append(f"{where}: 참조 대상에 없는 값 '{value}'")


def build():
    tax = json.loads((DATA / "taxonomy.json").read_text(encoding="utf-8"))
    employees, assignees, history, faqs, time_off = (read_csv(n) for n in (
        "employees.csv", "assignees.csv", "history.csv", "faq.csv", "time_off.csv"))
    p = Plan()
    r = p.rows

    # 부서: 사업부(상위) → 팀(하위)
    divisions = {}
    for e in employees:
        divisions.setdefault(e["division"], set()).add(e["team"])
    for div, teams in divisions.items():
        r["departments"].append({"name": div, "parent": None})
        r["departments"] += [{"name": t, "parent": div} for t in sorted(teams)]
    team_names = Counter(t for teams in divisions.values() for t in teams)
    p.problems += [f"departments: 팀 '{t}' 이 여러 사업부에 있음" for t, n in team_names.items() if n > 1]

    # 사용자
    emp = {e["emp_id"]: e for e in employees}
    for e in employees:
        where = f"employees {e['emp_id']}"
        r["users"].append({
            "employee_no": e["emp_id"], "name": e["name"], "email": e["email"], "department": e["team"],
            "position": e["job_title"],
            "service_role": p.code(SERVICE_ROLE, e["itssue_role"], where),
            "account_status": p.code(ACCOUNT_STATUS, e["employment_status"], where)})

    # 분류·담당 그룹·세부 유형
    r["categories"] = [{"code": c["code"], "name": c["name"], "description": c["scope"]}
                       for c in tax["category_detail"]]
    cat_codes = {c["code"] for c in r["categories"]}
    for t in tax["team_detail"]:
        p.ref(team_names, t["name"], "support_groups.department")
        r["support_groups"].append({"name": t["name"], "department": t["name"], "description": t["area"],
                                    "is_triage": t["name"] == TRIAGE_GROUP})
    group_names = {g["name"] for g in r["support_groups"]}
    for s in tax["scenarios"]:
        where = f"scenarios {s['id']}"
        p.ref(cat_codes, s["cat"], where)
        p.ref(group_names, s["team"], where)
        r["inquiry_types"].append({"code": s["id"], "category_code": s["cat"], "name": s["sub"],
                                   "request_kind": p.code(REQUEST_KIND, s["type"], where),
                                   "default_urgency": s["urg"], "default_group": s["team"]})
    type_codes = {t["code"] for t in r["inquiry_types"]}

    # 담당 그룹 구성원·처리 가능 업무
    for a in assignees:
        where = f"assignees {a['emp_id']}"
        p.ref(emp, a["emp_id"], where)
        p.ref(group_names, a["team"], where)
        if a["emp_id"] in emp and SERVICE_ROLE.get(emp[a["emp_id"]]["itssue_role"]) == "EMPLOYEE":
            p.problems.append(f"{where}: 구성원인데 service_role 이 EMPLOYEE")
        r["support_group_members"].append({
            "group": a["team"], "employee_no": a["emp_id"],
            "member_role": p.code(MEMBER_ROLE, a["role"], where),
            "assignable": p.code(YN, a["assignable"], where), "jira_account_id": blank(a["jira_account"])})
        for code in filter(None, (blank(s.strip()) for s in a["scenario_ids"].split(","))):
            p.ref(type_codes, code, where)
            r["member_skills"].append({"employee_no": a["emp_id"], "inquiry_type": code})

    # 자동배정 후보가 없는 세부 유형은 운영 중 '관리자 확인 필요'로 빠진다
    for t in r["inquiry_types"]:
        ok = any(m["employee_no"] == s["employee_no"] and m["group"] == t["default_group"] and m["assignable"]
                 for s in r["member_skills"] if s["inquiry_type"] == t["code"]
                 for m in r["support_group_members"])
        if not ok:
            p.warnings.append(f"inquiry_types {t['code']}: 기본 그룹({t['default_group']})에 배정 가능한 담당자가 없음")

    # FAQ 게시판
    for f in faqs:
        p.ref(cat_codes, f["category_code"], f"faq {f['faq_id']}")
        r["faqs"].append({"faq_code": f["faq_id"], "category_code": f["category_code"], "question": f["question"],
                          "answer": f["answer"],
                          "keywords": [k.strip() for k in f["keywords"].split(",") if k.strip()]})

    # 도입 이전 문의 이력 (문의자 개인은 넣지 않고 부서만 남긴다)
    member_by_name = {a["name"]: a["emp_id"] for a in assignees}
    for h in history:
        where = f"history {h['inquiry_id']}"
        p.ref(emp, h["requester_id"], where)
        p.ref(type_codes, h["scenario_id"], where)
        p.ref(group_names, h["assigned_team"], where)
        p.ref(member_by_name, h["assignee"], where)
        if h["status"] == "FIN" and not h["resolved_at"]:
            p.problems.append(f"{where}: FIN 인데 resolved_at 이 비어 있음")
        view, transfer = LEGACY_POLICY_BY_CATEGORY.get(h["category_code"], LEGACY_POLICY)
        r["legacy_inquiries"].append({
            "legacy_no": h["inquiry_id"], "received_at": kst(h["created_at"]), "resolved_at": kst(blank(h["resolved_at"])),
            "channel": p.code(CHANNEL, h["channel"], where), "handling_type": p.code(HANDLING, h["handling_type"], where),
            "requester_department": emp.get(h["requester_id"], {}).get("team"), "inquiry_type": h["scenario_id"],
            "urgency": h["urgency"], "impact_scope": p.code(IMPACT, h["impact_scope"], where),
            "title": h["title"], "description": h["description"], "root_cause": blank(h["root_cause"]),
            "resolution": blank(h["resolution"]), "prevention": blank(h["prevention"]),
            "group": h["assigned_team"], "assignee": member_by_name.get(h["assignee"]),
            "view_scope": view, "transfer_policy": transfer})

    # 연차·반차 일정 (가상 HR 데이터). 이름·팀·역할 열은 넣지 않는다
    for t in time_off:
        where = f"time_off {t['emp_id']} {t['start_date']}"
        p.ref(emp, t["emp_id"], where)
        p.ref(TIME_OFF_TYPES, t["time_off_type"], where)
        if t["end_date"] < t["start_date"]:
            p.problems.append(f"{where}: 종료일이 시작일보다 빠름")
        if t["time_off_type"] != "ANNUAL" and t["start_date"] != t["end_date"]:
            p.problems.append(f"{where}: 반차는 시작일과 종료일이 같아야 함")
        r["time_off"].append({"employee_no": t["emp_id"], "time_off_type": t["time_off_type"],
                              "start_date": t["start_date"], "end_date": t["end_date"], "note": blank(t["note"])})
    return p


# ---------------------------------------------------------------- DB 적재

def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL 이 없습니다. .env.example 을 .env 로 복사해 연결 주소를 넣으세요.")
    return url


def id_map(cur, sql):
    cur.execute(sql)
    return {key: id_ for id_, key in cur.fetchall()}


def upsert(cur, table, cols, key, rows, keep=()):
    """key 가 겹치면 key 이외의 열을 갱신한다. keep 의 열은 처음 넣을 때만 쓰고 이미 있는 행에서는 그대로 둔다."""
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key and c not in keep)
    action = f"do update set {updates}" if updates else "do nothing"
    cur.executemany(
        f"insert into {table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
        f"on conflict ({', '.join(key)}) {action}", rows)


def load(p, reset_passwords):
    import psycopg

    password = os.environ.get("SEED_INITIAL_PASSWORD")
    if not password:
        sys.exit("SEED_INITIAL_PASSWORD 가 없습니다. 사용자에게 줄 초기 비밀번호를 환경 변수로 넣으세요.")
    r = p.rows

    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:     # 끝까지 성공해야 한꺼번에 반영된다
        cur.execute("select table_name from information_schema.tables where table_schema = 'public'")
        missing = set(TABLES) - {t for (t,) in cur.fetchall()}
        if missing:
            sys.exit(f"테이블이 없습니다: {sorted(missing)}. 마이그레이션을 먼저 실행하세요.")

        # departments: 자연키 UNIQUE 가 없어 (이름, 상위) 로 찾아 없을 때만 넣는다
        dept = {}
        for d in r["departments"]:
            parent_id = dept.get(d["parent"])
            cur.execute("select id from departments where name = %s and parent_id is not distinct from %s",
                        (d["name"], parent_id))
            row = cur.fetchone() or cur.execute(
                "insert into departments (name, parent_id) values (%s, %s) returning id", (d["name"], parent_id)).fetchone()
            dept[d["name"]] = row[0]

        # users: 신규 사용자만 비밀번호 해시를 만들어 넣고, 기존 사용자는 비밀번호를 건드리지 않고 정보만 갱신한다
        # (password_hash 가 NOT NULL 이라 기존 사용자를 upsert 로 처리하면 해시 없이 넣는 행이 제약에 걸린다)
        existing = {no for (no,) in cur.execute("select employee_no from users").fetchall()}
        info = lambda u: (u["name"], u["email"], dept[u["department"]], u["position"], u["service_role"],
                          u["account_status"])
        cur.executemany(
            "insert into users (name, email, department_id, position, service_role, account_status, "
            "employee_no, password_hash) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(*info(u), u["employee_no"], hash_password(password)) for u in r["users"] if u["employee_no"] not in existing])
        cur.executemany(
            "update users set name = %s, email = %s, department_id = %s, position = %s, service_role = %s, "
            "account_status = %s, updated_at = now() where employee_no = %s",
            [(*info(u), u["employee_no"]) for u in r["users"] if u["employee_no"] in existing])
        if reset_passwords:     # 해싱 방식을 바꾼 뒤 기존 사용자까지 초기 비밀번호로 되돌릴 때
            cur.executemany(
                "update users set password_hash = %s, password_changed_at = null, failed_login_count = 0, "
                "locked_until = null, updated_at = now() where employee_no = %s",
                [(hash_password(password), u["employee_no"]) for u in r["users"] if u["employee_no"] in existing])
        user = id_map(cur, "select id, employee_no from users")

        upsert(cur, "categories", ["code", "name", "description"], ["code"],
               [(c["code"], c["name"], c["description"]) for c in r["categories"]])

        upsert(cur, "support_groups", ["name", "department_id", "description", "is_triage"], ["name"],
               [(g["name"], dept[g["department"]], g["description"], g["is_triage"]) for g in r["support_groups"]])
        group = id_map(cur, "select id, name from support_groups")

        upsert(cur, "inquiry_types", ["code", "category_code", "name", "request_kind", "default_urgency",
                                      "default_group_id"], ["code"],
               [(t["code"], t["category_code"], t["name"], t["request_kind"], t["default_urgency"],
                 group[t["default_group"]]) for t in r["inquiry_types"]])
        itype = id_map(cur, "select id, code from inquiry_types")

        upsert(cur, "support_group_members", ["group_id", "user_id", "member_role", "assignable", "jira_account_id"],
               ["group_id", "user_id"],
               [(group[m["group"]], user[m["employee_no"]], m["member_role"], m["assignable"], m["jira_account_id"])
                for m in r["support_group_members"]])

        upsert(cur, "member_skills", ["user_id", "inquiry_type_id"], ["user_id", "inquiry_type_id"],
               [(user[s["employee_no"]], itype[s["inquiry_type"]]) for s in r["member_skills"]])

        # 게시 여부(is_active)는 넣지 않아 기본값(true)으로 생기고, 이미 있는 FAQ에서는 관리자가 정한 값이 남는다
        upsert(cur, "faqs", ["faq_code", "category_code", "question", "answer", "keywords"], ["faq_code"],
               [(f["faq_code"], f["category_code"], f["question"], f["answer"], f["keywords"]) for f in r["faqs"]])

        upsert(cur, "legacy_inquiries",
               ["legacy_no", "received_at", "resolved_at", "channel", "handling_type", "requester_department_id",
                "inquiry_type_id", "urgency", "impact_scope", "title", "description", "root_cause", "resolution",
                "prevention", "group_id", "assignee_id", "view_scope", "transfer_policy"], ["legacy_no"],
               [(h["legacy_no"], h["received_at"], h["resolved_at"], h["channel"], h["handling_type"],
                 dept[h["requester_department"]], itype[h["inquiry_type"]], h["urgency"], h["impact_scope"],
                 h["title"], h["description"], h["root_cause"], h["resolution"], h["prevention"],
                 group[h["group"]], user[h["assignee"]], h["view_scope"], h["transfer_policy"])
                for h in r["legacy_inquiries"]])

        # 이미 있는 일정은 그대로 둔다 (화면에서 고친 내용을 되돌리지 않는다)
        upsert(cur, "time_off", ["user_id", "time_off_type", "start_date", "end_date", "note"],
               ["user_id", "time_off_type", "start_date"],
               [(user[t["employee_no"]], t["time_off_type"], t["start_date"], t["end_date"], t["note"])
                for t in r["time_off"]], keep=("end_date", "note"))

        print(f"\n{'테이블':24}{'파일':>8}{'DB':>8}")
        for table in TABLES:
            n = cur.execute(f"select count(*) from {table}").fetchone()[0]
            mark = "" if n == len(r[table]) else "   <- 다름 (파일에 없는 행이 DB에 있음)"
            print(f"{table:24}{len(r[table]):>8}{n:>8}{mark}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="DB에 붙지 않고 파일만 변환·검사한다")
    ap.add_argument("--reset-passwords", action="store_true", help="기존 사용자 비밀번호도 초기 비밀번호로 다시 넣는다")
    args = ap.parse_args()

    p = build()
    for w in p.warnings:
        print(f"[확인] {w}")
    if p.problems:
        sys.exit("데이터 파일에 문제가 있어 적재하지 않았습니다:\n- " + "\n- ".join(p.problems))
    if args.check:
        for table in TABLES:
            print(f"{table:24}{len(p.rows[table]):>6}건")
        print("파일 검사 통과")
        return
    load(p, args.reset_passwords)


if __name__ == "__main__":
    main()
