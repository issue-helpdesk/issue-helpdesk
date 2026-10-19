"""dataset/data/ 의 CSV·JSON을 docs/06.테이블_설계서.md 의 테이블에 적재한다.

    python db/seed.py --check        # DB 없이 파일만 변환·검사 (건수, 참조, 코드 변환)
    python db/seed.py                # 적재 (다시 실행해도 같은 키는 갱신만 한다)
    python db/seed.py --reset-passwords   # 적재하면서 기존 사용자 비밀번호도 초기 비밀번호로 다시 넣는다

- 테이블은 미리 만들어 둬야 한다 (Alembic 마이그레이션). 이 스크립트는 테이블을 만들지 않는다.
- 연결 주소는 환경 변수 DATABASE_URL 또는 저장소 루트의 .env 에서 읽는다.
- 신규 사용자의 초기 비밀번호는 환경 변수 SEED_INITIAL_PASSWORD 로 받아 해시로 저장한다.
  이미 있는 사용자의 비밀번호는 --reset-passwords 를 주지 않으면 바꾸지 않는다.
- 해시는 개발용 임시 방식(솔트 + SHA-256)이다. 정식 해싱 방식이 정해지면 hash_password 만 바꾸고
  --reset-passwords 로 다시 넣는다. 로그인 검증도 같은 방식이어야 한다.
- 평가셋(eval_inquiries.csv)은 DB에 넣지 않고 파일로 관리한다.
- FAQ 문서 버전의 열람 범위·외부 전송 정책은 처음 만들 때만 정한다. 이미 있는 버전의 정책·현행 여부·적재 상태는
  다시 실행해도 건드리지 않는다 (관리자가 바꾼 값과 임베딩이 끝난 상태를 지킨다).
  FAQ의 임베딩 입력(질문 + 본문)이 바뀐 경우에만 청크를 고치고 그 버전을 다시 적재 대상(PENDING·비현행)으로 돌린다.
- 필요한 패키지: psycopg[binary], python-dotenv
"""
import argparse
import csv
import hashlib
import json
import os
import secrets
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
FAQ_VERSION = "1.0"

# document_chunks.meta 의 키 (backend/app/rag/청크_메타데이터.md 'meta 계약'). 값이 없어도 키는 항상 넣는다
EMPTY_META = {"section_no": "", "inquiry_type_codes": [], "page_start": None, "page_end": None, "props": {},
              "subheadings": [], "faq_ids": [], "images": [], "handling": "", "team": "", "escalation_teams": [],
              "urgency": ""}

# ---------------------------------------------------------------- 데이터셋 값 → 설계 코드

SERVICE_ROLE = {"일반 임직원": "EMPLOYEE", "IT 운영 담당자": "AGENT", "관리자": "ADMIN"}
ACCOUNT_STATUS = {"재직": "ACTIVE"}
MEMBER_ROLE = {"L1 상담": "AGENT", "L2 담당": "AGENT", "팀장": "MANAGER", "조직장": "MANAGER"}
REQUEST_KIND = {"장애": "INCIDENT", "요청": "REQUEST", "문의": "QUESTION"}
CHANNEL = {"전화": "PHONE", "메일": "MAIL", "메신저": "MESSENGER"}
HANDLING = {"즉시 처리": "IMMEDIATE", "티켓": "TICKET"}
IMPACT = {"개인": "PERSONAL", "부서": "DEPARTMENT", "전사": "COMPANY"}
YN = {"Y": True, "N": False}

TRIAGE_GROUP = "서비스데스크"   # 담당 그룹이 불확실할 때 확인하는 그룹

# 열람 범위·외부 전송 정책 (팀 확정 전 제안값)
FAQ_POLICY = ("ALL", "ALLOWED")                 # FAQ는 전 직원 공개용 일반 안내
LEGACY_POLICY = ("ALL", "MASKED")               # 과거 사례: 문의자 정보는 넣지 않고, 본문은 마스킹 후 전송
LEGACY_POLICY_BY_CATEGORY = {"SEC": ("AGENT", "BLOCKED")}   # 보안 사고 이력은 담당자만, 외부 전송 금지

# 적재 순서 = 참조되는 테이블이 먼저
TABLES = ["departments", "users", "categories", "support_groups", "inquiry_types", "support_group_members",
          "member_skills", "knowledge_documents", "document_versions", "document_chunks", "legacy_inquiries"]


def read_csv(name):
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def blank(v):
    """빈칸과 '-' 는 값 없음으로 본다."""
    return None if v in ("", "-") else v


def kst(v):
    return f"{v}{KST}" if v else None


def hash_password(password):
    """개발용 임시 해시: 'sha256$<솔트>$<hex>'. 앞의 표시로 나중에 어떤 방식으로 저장됐는지 구분한다."""
    salt = secrets.token_hex(16)
    return f"sha256${salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"


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
    employees, assignees, history, faqs = (read_csv(n) for n in (
        "employees.csv", "assignees.csv", "history.csv", "faq.csv"))
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

    # FAQ → 문서 1건 = 버전 1건 = 청크 1건 (새 버전은 PENDING·비현행. 임베딩 뒤 적재 스크립트가 현행으로 켠다)
    view, transfer = FAQ_POLICY
    for f in faqs:
        p.ref(cat_codes, f["category_code"], f"faq {f['faq_id']}")
        r["knowledge_documents"].append({"doc_code": f["faq_id"], "doc_type": "FAQ", "title": f["question"],
                                         "category_code": f["category_code"]})
        r["document_versions"].append({"doc_code": f["faq_id"], "version": FAQ_VERSION,
                                       "file_path": "dataset/data/faq.csv", "file_format": "TEXT",
                                       "view_scope": view, "transfer_policy": transfer})
        keywords = ", ".join(k.strip() for k in f["keywords"].split(",") if k.strip())
        r["document_chunks"].append({
            "doc_code": f["faq_id"], "heading_path": f["question"], "location": f["faq_id"],
            "content": f"Q. {f['question']}\nA. {f['answer']}\n키워드: {keywords}",
            "seq": 1, "unit_key": f"{f['faq_id']}@{FAQ_VERSION}/faq:{f['faq_id']}", "chunk_type": "FAQ", "part": 1,
            "meta": {**EMPTY_META, "faq_ids": [f["faq_id"]]}})

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
    from psycopg.types.json import Jsonb

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

        upsert(cur, "knowledge_documents", ["doc_code", "doc_type", "title", "category_code"], ["doc_code"],
               [(d["doc_code"], d["doc_type"], d["title"], d["category_code"]) for d in r["knowledge_documents"]])
        doc = id_map(cur, "select id, doc_code from knowledge_documents")

        # 정책(view_scope·transfer_policy)과 현행·적재 상태는 처음 만들 때만 정한다.
        # 이미 있는 버전에서 바꾸면 관리자가 정한 정책과 임베딩이 끝난 상태가 시드를 돌릴 때마다 되돌아간다
        upsert(cur, "document_versions", ["document_id", "version", "file_path", "file_format", "view_scope",
                                          "transfer_policy", "is_current", "ingest_status"], ["document_id", "version"],
               [(doc[v["doc_code"]], v["version"], v["file_path"], v["file_format"], v["view_scope"],
                 v["transfer_policy"], False, "PENDING") for v in r["document_versions"]],
               keep=("view_scope", "transfer_policy", "is_current", "ingest_status"))
        version = {doc_id: vid for vid, doc_id in cur.execute(
            "select id, document_id from document_versions where version = %s and document_id = any(%s)",
            (FAQ_VERSION, list(doc.values()))).fetchall()}

        # FAQ 청크 (버전마다 1개, seq=1). 임베딩 입력(질문 + 본문)이 그대로면 다시 쓰지 않는다:
        # 지우고 다시 넣으면 청크 id 가 바뀌고 임베딩이 같이 지워지는데 버전은 DONE·현행으로 남는다
        has_embeddings = cur.execute("select to_regclass('document_chunk_embeddings')").fetchone()[0]
        fields = ["unit_key", "chunk_type", "part", "location", "meta", "heading_path", "content"]
        old = {(vid, seq): row for vid, seq, *row in cur.execute(
            f"select version_id, seq, id, {', '.join(fields)} from document_chunks where version_id = any(%s)",
            (list(version.values()),)).fetchall()}
        inserts, updates, reingest = [], [], []
        for c in r["document_chunks"]:
            vid = version[doc[c["doc_code"]]]
            new = [c[f] for f in fields]
            if (vid, c["seq"]) not in old:
                inserts.append((vid, c["seq"], *new[:4], Jsonb(c["meta"]), *new[5:]))
                continue
            chunk_id, *cur_vals = old[(vid, c["seq"])]
            if cur_vals == new:                         # 바뀐 것이 없으면 행을 다시 쓰지 않는다
                continue
            updates.append((*new[:4], Jsonb(c["meta"]), *new[5:], chunk_id))
            if cur_vals[5:] != new[5:]:                 # 임베딩 입력(질문·본문)이 바뀜 → 다시 적재 대상
                reingest.append((c["doc_code"], vid, chunk_id))
        cur.executemany(f"insert into document_chunks (version_id, seq, {', '.join(fields)}) "
                        f"values ({', '.join(['%s'] * (len(fields) + 2))})", inserts)
        cur.executemany(f"update document_chunks set {', '.join(f'{f} = %s' for f in fields)} where id = %s", updates)
        if reingest:
            if has_embeddings:
                cur.execute("delete from document_chunk_embeddings where chunk_id = any(%s)", ([x[2] for x in reingest],))
            cur.execute("update document_versions set is_current = false, ingest_status = 'PENDING', ingest_error = null "
                        "where id = any(%s)", ([x[1] for x in reingest],))
            reingest = [x[0] for x in reingest]
        if reingest:
            print(f"[확인] 임베딩 입력이 바뀌어 다시 적재 대상(PENDING)으로 돌린 FAQ {len(reingest)}건: "
                  + ", ".join(reingest[:10]) + (" …" if len(reingest) > 10 else ""))

        upsert(cur, "legacy_inquiries",
               ["legacy_no", "received_at", "resolved_at", "channel", "handling_type", "requester_department_id",
                "inquiry_type_id", "urgency", "impact_scope", "title", "description", "root_cause", "resolution",
                "prevention", "group_id", "assignee_id", "view_scope", "transfer_policy"], ["legacy_no"],
               [(h["legacy_no"], h["received_at"], h["resolved_at"], h["channel"], h["handling_type"],
                 dept[h["requester_department"]], itype[h["inquiry_type"]], h["urgency"], h["impact_scope"],
                 h["title"], h["description"], h["root_cause"], h["resolution"], h["prevention"],
                 group[h["group"]], user[h["assignee"]], h["view_scope"], h["transfer_policy"])
                for h in r["legacy_inquiries"]])

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
