"""dataset/data/ 의 CSV·JSON을 db/schema.sql 의 표에 넣는다.

    python db/seed.py --check        # DB 없이 파일만 검사 (건수, 참조가 맞는지)
    python db/seed.py                # 표를 만들고 데이터를 넣는다 (다시 실행하면 같은 키는 덮어쓴다)
    python db/seed.py --reset        # 표를 비우고 다시 넣는다
    python db/seed.py --with-eval    # 평가용 정답셋(eval.inquiries)도 넣는다

연결 주소는 환경 변수 DATABASE_URL 또는 저장소 루트의 .env 에서 읽는다 (.env.example 참고).
필요한 패키지: psycopg[binary]
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataset" / "data"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"

# dataset/README.md 에 적힌 건수
EXPECTED = {"categories": 7, "urgency_levels": 4, "teams": 6, "channels": 3, "handling_types": 2, "user_roles": 3,
            "assignee_roles": 4, "faqs": 40, "scenarios": 50, "major_incidents": 7, "employees": 400,
            "assignees": 50, "inquiry_history": 400, "eval.inquiries": 50}

# 넣는 순서 = 참조되는 표가 먼저. 비울 때는 거꾸로.
ORDER = ["categories", "urgency_levels", "teams", "channels", "handling_types", "user_roles", "assignee_roles",
         "faqs", "scenarios", "major_incidents", "employees", "assignees", "assignee_scenarios", "inquiry_history"]


def read_csv(name):
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def none_if_empty(v):
    return v if v != "" else None


def build_rows(with_eval):
    """파일을 읽어 {표 이름: (열 목록, 행 목록)} 으로 돌려준다."""
    tax = json.loads((DATA / "taxonomy.json").read_text(encoding="utf-8"))
    faqs, employees, assignees, history = (read_csv(n) for n in
                                           ("faq.csv", "employees.csv", "assignees.csv", "history.csv"))
    emp_by_name = {a["name"]: a["emp_id"] for a in assignees}
    yn = {"Y": True, "N": False}

    rows = {
        "categories": (["code", "name", "scope"],
                       [(c["code"], c["name"], c["scope"]) for c in tax["category_detail"]]),
        "urgency_levels": (["code", "label", "description", "response_min", "resolve_min"],
                           [(k, v["label"], v["desc"], v["response_min"], v["resolve_min"])
                            for k, v in tax["urgency"].items()]),
        "teams": (["name", "area"], [(t["name"], t["area"]) for t in tax["team_detail"]]),
        "channels": (["code", "description"], [(c["code"], c["desc"]) for c in tax["channels"]]),
        "handling_types": (["code", "description"], [(c["code"], c["desc"]) for c in tax["handling_types"]]),
        "user_roles": (["role", "who", "page", "functions"],
                       [(r["role"], r["who"], r["page"], r["functions"]) for r in tax["user_roles"]]),
        "assignee_roles": (["role", "assignable", "description"],
                           [(r["role"], yn[r["assignable"]], r["desc"]) for r in tax["assignee_roles"]]),
        "faqs": (["faq_id", "category_code", "question", "answer", "keywords"],
                 [(r["faq_id"], r["category_code"], r["question"], r["answer"],
                   [k.strip() for k in r["keywords"].split(",") if k.strip()]) for r in faqs]),
        "scenarios": (["scenario_id", "category_code", "subcategory", "ticket_type", "default_urgency", "team",
                       "manual_id", "faq_id", "impact_scope", "tool"],
                      [(s["id"], s["cat"], s["sub"], s["type"], s["urg"], s["team"], s["manual"],
                        none_if_empty(s["faq"]), s["scope"], s["tool"]) for s in tax["scenarios"]]),
        "major_incidents": (["incident_id", "scenario_id", "started_at", "ticket_count", "duration_min", "summary"],
                            [(m["id"], m["scenario"], m["started_at"], m["tickets"], m["duration_min"], m["summary"])
                             for m in tax["major_incidents"]]),
        "employees": (list(employees[0]), [tuple(r.values()) for r in employees]),
        "assignees": (["emp_id", "name", "team", "role", "assignable", "specialty_area", "jira_account",
                       "handled_tickets", "open_tickets"],
                      [(a["emp_id"], a["name"], a["team"], a["role"], yn[a["assignable"]], a["specialty_area"],
                        a["jira_account"], int(a["handled_tickets"]), int(a["open_tickets"])) for a in assignees]),
        "assignee_scenarios": (["emp_id", "scenario_id"],
                               [(a["emp_id"], s) for a in assignees for s in a["scenario_ids"].split(",")
                                if s and s != "-"]),          # '-' 는 맡은 시나리오 없음 (팀장·조직장)
        "inquiry_history": (
            ["inquiry_id", "created_at", "channel", "handling_type", "requester_id", "requester_dept", "ticket_type",
             "category_code", "category", "subcategory", "scenario_id", "tool", "urgency", "urgency_label",
             "impact_scope", "title", "description", "status", "assigned_team", "assignee", "assignee_emp_id",
             "resolved_at", "root_cause", "resolution", "prevention", "related_faq"],
            [(h["inquiry_id"], h["created_at"], h["channel"], h["handling_type"], h["requester_id"],
              h["requester_dept"], h["ticket_type"], h["category_code"], h["category"], h["subcategory"],
              h["scenario_id"], h["tool"], h["urgency"], h["urgency_label"], h["impact_scope"], h["title"],
              h["description"], h["status"], h["assigned_team"], h["assignee"], emp_by_name.get(h["assignee"]),
              none_if_empty(h["resolved_at"]), h["root_cause"], h["resolution"], none_if_empty(h["prevention"]),
              none_if_empty(h["related_faq"])) for h in history]),
    }
    if with_eval:
        ev = read_csv("eval_inquiries.csv")
        rows["eval.inquiries"] = (list(ev[0]), [tuple(r.values()) for r in ev])
    return rows


def check(rows):
    """DB 없이 건수와 참조를 검사한다. 문제를 문장 목록으로 돌려준다."""
    problems = []
    for table, (_, data) in rows.items():
        want = EXPECTED.get(table)
        if want is not None and len(data) != want:
            problems.append(f"{table}: {len(data)}건 (README 기준 {want}건)")
    keys = {t: {r[0] for r in rows[t][1]} for t in ("categories", "urgency_levels", "teams", "channels",
                                                    "handling_types", "user_roles", "assignee_roles", "faqs",
                                                    "scenarios", "employees", "assignees")}

    def ref(table, col, target, optional=False):
        cols, data = rows[table]
        i = cols.index(col)
        bad = sorted({r[i] for r in data if not (optional and r[i] is None)} - keys[target], key=str)
        if bad:
            problems.append(f"{table}.{col}: {target} 에 없는 값 {bad[:5]}")

    ref("faqs", "category_code", "categories")
    ref("scenarios", "category_code", "categories")
    ref("scenarios", "default_urgency", "urgency_levels")
    ref("scenarios", "team", "teams")
    ref("scenarios", "faq_id", "faqs", optional=True)
    ref("major_incidents", "scenario_id", "scenarios")
    ref("employees", "itssue_role", "user_roles")
    ref("assignees", "emp_id", "employees")
    ref("assignees", "team", "teams")
    ref("assignees", "role", "assignee_roles")
    ref("assignee_scenarios", "scenario_id", "scenarios")
    for col, target in (("channel", "channels"), ("handling_type", "handling_types"), ("requester_id", "employees"),
                        ("category_code", "categories"), ("scenario_id", "scenarios"), ("urgency", "urgency_levels"),
                        ("assigned_team", "teams"), ("assignee_emp_id", "assignees")):
        ref("inquiry_history", col, target)
    ref("inquiry_history", "related_faq", "faqs", optional=True)
    return problems


def database_url():
    url = os.environ.get("DATABASE_URL")
    env = ROOT / ".env"
    if not url and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        sys.exit("DATABASE_URL 이 없습니다. .env.example 을 .env 로 복사해 연결 주소를 넣으세요.")
    return url


def load(rows, reset):
    import psycopg

    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:      # 끝까지 성공해야 한꺼번에 반영된다
        cur.execute(SCHEMA.read_text(encoding="utf-8"))
        tables = [t for t in ORDER if t in rows] + [t for t in rows if t not in ORDER]
        if reset:
            cur.execute("truncate " + ", ".join(reversed(tables)) + " cascade")
        for table in tables:
            cols, data = rows[table]
            pk = 2 if table == "assignee_scenarios" else 1
            updates = ", ".join(f"{c} = excluded.{c}" for c in cols[pk:])
            action = f"do update set {updates}" if updates else "do nothing"
            cur.executemany(
                f"insert into {table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
                f"on conflict ({', '.join(cols[:pk])}) {action}", data)
        print(f"{'표':22}{'파일':>8}{'DB':>8}")
        ok = True
        for table in tables:
            cur.execute(f"select count(*) from {table}")
            n = cur.fetchone()[0]
            same = n == len(rows[table][1])
            ok = ok and same
            print(f"{table:22}{len(rows[table][1]):>8}{n:>8}{'' if same else '   <- 다름'}")
        if not ok:
            print("건수가 다른 표가 있습니다. 파일에 없는 행이 DB에 남아 있으면 --reset 으로 다시 넣으세요.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="DB에 붙지 않고 파일만 검사한다")
    ap.add_argument("--reset", action="store_true", help="표를 비운 뒤 다시 넣는다")
    ap.add_argument("--with-eval", action="store_true", help="평가용 정답셋(eval.inquiries)도 넣는다")
    args = ap.parse_args()

    rows = build_rows(args.with_eval)
    problems = check(rows)
    if problems:
        sys.exit("데이터 파일에 문제가 있어 넣지 않았습니다:\n- " + "\n- ".join(problems))
    if args.check:
        for table, (_, data) in rows.items():
            print(f"{table:22}{len(data):>6}건")
        print("파일 검사 통과")
        return
    load(rows, args.reset)


if __name__ == "__main__":
    main()
