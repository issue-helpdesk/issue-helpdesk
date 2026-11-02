"""부재자 제외 + 자동배정 선정 시나리오 — 시연 데이터(time_off 14건)와 실제 담당자 표(assignees.csv)로 확인한다.

DB·Jira 호출 없음. "누구를 고르는가"만 본다(실제 Jira 지정·재조회는 service/smoke 점검 몫).
time_off 14건은 전달 자료(time_off.csv)와 같은 값을 아래에 그대로 적었다 (dataset/ 에 아직 파일이 없어서).
현재 시각은 `now`로 직접 넣으므로 시험 날짜와 상관없이 같은 결과가 나온다.
"""

import csv
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from app.integrations.jira import Member, TimeOff, absent_user_ids, pick_assignee

ASSIGNEES_CSV = Path(__file__).resolve().parents[1] / "dataset" / "data" / "assignees.csv"

# emp_id, 유형, 시작일, 종료일  (time_off.csv 14건)
TIME_OFF_ROWS = """
EMP-1325,ANNUAL,2026-10-26,2026-10-28
EMP-1353,HALF_PM,2026-10-27,2026-10-27
EMP-1385,ANNUAL,2026-10-28,2026-10-29
EMP-1423,HALF_PM,2026-10-29,2026-10-29
EMP-1178,HALF_AM,2026-10-30,2026-10-30
EMP-1464,ANNUAL,2026-11-02,2026-11-02
EMP-1333,ANNUAL,2026-11-03,2026-11-04
EMP-1408,HALF_PM,2026-11-04,2026-11-04
EMP-1338,ANNUAL,2026-11-05,2026-11-06
EMP-1241,HALF_AM,2026-11-06,2026-11-06
EMP-1270,HALF_AM,2026-11-09,2026-11-09
EMP-1130,ANNUAL,2026-11-11,2026-11-11
EMP-1461,ANNUAL,2026-11-12,2026-11-13
EMP-1278,ANNUAL,2026-11-16,2026-11-18
""".strip().splitlines()


def uid(emp_id: str) -> int:
    return int(emp_id.split("-")[1])


def load_entries() -> list[TimeOff]:
    out = []
    for line in TIME_OFF_ROWS:
        emp, kind, start, end = line.split(",")
        out.append(TimeOff(uid(emp), kind, date.fromisoformat(start), date.fromisoformat(end)))
    return out


def load_team(team: str) -> list[Member]:
    """assignees.csv 의 한 팀을 Member 로 바꾼다. Jira 계정은 시험용 가짜 값(acc-사번)이다."""
    members = []
    with ASSIGNEES_CSV.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["team"] != team:
                continue
            scenarios = frozenset(s for s in r["scenario_ids"].split(",") if s and s != "-")
            members.append(Member(
                user_id=uid(r["emp_id"]), employee_no=r["emp_id"], name=r["name"],
                is_manager=r["role"] in ("팀장", "조직장"), assignable=r["assignable"] == "Y",
                jira_account_id=f"acc-{r['emp_id']}", scenario_ids=scenarios, rdy=int(r["open_tickets"] or 0),
            ))
    return members


def pick(team: str, scenario: str, when: str, *, entries=None, tweak=None):
    members = load_team(team)
    if tweak:
        members = [tweak(m) for m in members]
    absent = absent_user_ids(entries if entries is not None else load_entries(), datetime.fromisoformat(when))
    return pick_assignee(members, scenario, exclude_user_ids=absent)


# ------------------------------------------------------------------ 시연 데이터 확인

def test_demo_data_only_half_affect_auto_assignment():
    """14건 중 7건은 assignable=N 인 팀장·조직장이라 자동배정에 영향이 없다(전달 md 6번 설명과 같은 숫자)."""
    with ASSIGNEES_CSV.open(encoding="utf-8-sig") as f:
        assignable = {r["emp_id"]: r["assignable"] == "Y" for r in csv.DictReader(f)}
    emps = [line.split(",")[0] for line in TIME_OFF_ROWS]
    assert len(emps) == 14 and len(set(emps)) == 14
    assert all(e in assignable for e in emps)                     # 담당자 표에 모두 있다
    assert sum(assignable[e] for e in emps) == 7
    assert sum(not assignable[e] for e in emps) == 7


# ------------------------------------------------------------------ 부재자가 빠지고 다음 사람이 선정

def test_annual_leave_changes_the_pick_business_systems():
    # SYS-02 담당은 권다은(1130)·김정훈(1480). 업무량이 같으면 사번 순이라 평소엔 권다은.
    assert pick("업무시스템팀", "SYS-02", "2026-11-10T10:00").user_id == 1130
    d = pick("업무시스템팀", "SYS-02", "2026-11-11T10:00")        # 권다은 연차(리허설 당일)
    assert d.user_id == 1480
    assert d.excluded[1130] == "배정 제외 대상"


def test_annual_leave_beats_lower_workload_endpoint_team():
    # HW-03~05 담당은 김수아(1102, 진행 1건)·임동훈(1333, 0건). 평소엔 업무량이 적은 임동훈.
    assert pick("엔드포인트지원팀", "HW-03", "2026-11-02T10:00").user_id == 1333
    assert pick("엔드포인트지원팀", "HW-03", "2026-11-03T10:00").user_id == 1102   # 임동훈 연차 → 업무량이 더 많아도 김수아
    assert pick("엔드포인트지원팀", "HW-03", "2026-11-04T10:00").user_id == 1102   # 종료일(11/4)까지 포함
    assert pick("엔드포인트지원팀", "HW-03", "2026-11-05T10:00").user_id == 1333   # 복귀


def test_half_day_pm_cutoff_security_team():
    # SEC-01 담당은 황민석(1408)·송예린(1462). 황민석 11/4 오후 반차.
    assert pick("정보보안팀", "SEC-01", "2026-11-04T12:59").user_id == 1408        # 13시 전엔 근무
    assert pick("정보보안팀", "SEC-01", "2026-11-04T13:00").user_id == 1462        # 13시 정각부터 부재
    assert pick("정보보안팀", "SEC-01", "2026-11-05T09:00").user_id == 1408


def test_half_day_am_returns_at_noon_infra_team():
    # ACC-04 담당은 임재원(1233)·한지민(1241)·오가윤(1319). 한지민이 업무량 최소가 되게 나머지에 1건씩 둔다.
    busy = lambda m: replace(m, rdy=1) if m.user_id in (1233, 1319) else replace(m, rdy=0)  # noqa: E731
    assert pick("시스템인프라팀", "ACC-04", "2026-11-05T10:00", tweak=busy).user_id == 1241   # 부재 아님
    d = pick("시스템인프라팀", "ACC-04", "2026-11-06T10:00", tweak=busy)                     # 오전 반차 → 제외
    assert d.user_id == 1233 and 1241 in d.excluded
    assert pick("시스템인프라팀", "ACC-04", "2026-11-06T13:00", tweak=busy).user_id == 1241  # 13시 복귀


# ------------------------------------------------------------------ 후보 없음 · 팀장 부재 · 미분류

def test_everyone_absent_means_no_candidate():
    entries = load_entries() + [TimeOff(1480, "ANNUAL", date(2026, 11, 11), date(2026, 11, 11))]  # 김정훈도 같은 날 연차(가정)
    d = pick("업무시스템팀", "SYS-02", "2026-11-11T10:00", entries=entries)
    assert not d.selected and d.reason == "배정 가능한 후보 없음"                      # 호출하는 쪽이 확인 필요(NEEDS_ADMIN)로 넘긴다


def test_manager_leave_does_not_change_auto_assignment():
    # 정상훈(업무시스템팀 팀장) 11/2 연차. 팀장은 원래 후보가 아니라 결과가 같아야 한다.
    with_leave = pick("업무시스템팀", "SYS-02", "2026-11-02T10:00")
    without = pick("업무시스템팀", "SYS-02", "2026-11-02T10:00", entries=[])
    assert with_leave.user_id == without.user_id == 1130
    assert 1464 in with_leave.excluded


def test_unclassified_ticket_is_not_auto_assigned_even_if_everyone_present():
    d = pick("업무시스템팀", "", "2026-11-10T10:00")
    assert not d.selected and "미분류" in d.reason


def test_demo_window_only_four_effective_entries():
    """11/2~11/12 사이에 걸리면서 자동배정에 영향이 있는 일정은 전달 md 6번의 4건이다."""
    effective_emps = {"EMP-1333", "EMP-1408", "EMP-1241", "EMP-1130"}
    with ASSIGNEES_CSV.open(encoding="utf-8-sig") as f:
        assignable = {r["emp_id"] for r in csv.DictReader(f) if r["assignable"] == "Y"}
    window = (date(2026, 11, 2), date(2026, 11, 12))
    hit = {line.split(",")[0] for line in TIME_OFF_ROWS
           if date.fromisoformat(line.split(",")[2]) <= window[1] and date.fromisoformat(line.split(",")[3]) >= window[0]}
    assert hit & {e for e in assignable} == effective_emps
