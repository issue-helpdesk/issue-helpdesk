"""실제 Jira(ITHD)에 붙여 보는 점검 스크립트. 저장소 루트에서 실행한다.

    python backend/app/integrations/jira/smoke_check.py            # 인증 + 기존 시험 티켓 확인 (새로 만들지 않음)
    python backend/app/integrations/jira/smoke_check.py --create   # 위 + 새 시험 티켓 1건 생성
    python backend/app/integrations/jira/smoke_check.py --flow     # 위 + 담당자 지정·재조회·상태 전환(RDY→WIP→FIN→CLS)까지 (--create 포함)
    python backend/app/integrations/jira/smoke_check.py --reopen   # 새 시험 티켓으로 FIN→WIP→FIN 재처리를 해 보고 「최종 처리 결과」가 어떻게 남는지 본다 (--create 포함, CLS까지는 가지 않음)

필요한 것: 루트 .env 의 JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN, pip install -r requirements.txt
토큰 값은 화면에 출력하지 않는다. 새로 만든 시험 티켓은 확인 후 Jira에서 직접 지운다.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from app.integrations.jira import JiraClient, JiraError  # noqa: E402
from app.integrations.jira.mapper import adf_to_text  # noqa: E402

FINAL_RESULT_FIELD = "customfield_10069"  # 「최종 처리 결과」 (field_mapping.yaml transition_fields.final_result)

# 새 사이트에 같은 접수번호의 시험 티켓이 있으면 그 티켓을 찾아 돌려줘야 한다.
EXISTING = {
    "receipt_no": "RCPT-TEST-0001",
    "title": "[테스트] Jira 연동 모듈 확인용 — 확인 후 삭제",
    "category_code": "NET",
    "urgency": "P2",
    "group_name": "네트워크팀",
    "summary": "재택근무 중 VPN 접속이 실패합니다.",
    "onset": "오늘 오전",
    "tried_actions": "재접속\n PC 재시작",
    "request_kind": "INCIDENT",
    "impact_scope": "PERSONAL",
    "target_system": "VPN",
    "inquiry_type_code": "NET-02",
}


def check(jira: JiraClient, ticket: dict, *, create: bool = False) -> bool:
    result = jira.create_ticket(ticket) if create else jira.find_by_receipt(ticket["receipt_no"])
    if result is None:
        print("  기존 시험 티켓 없음: 검색 확인만 통과 (새로 만들지 않음)")
        return True
    action = "새로 만듦" if result.get("created") else "기존 티켓 조회"
    print(f"  {ticket['receipt_no']} → {result['jira_key']} ({action})  {result['jira_url']}")
    diffs = jira.check_saved(result["jira_key"], ticket)
    print(f"  저장값 비교: {'차이 없음' if not diffs else diffs}")
    if not create:
        return not diffs
    # 검색 인덱스에 나타나기 전에는 생성 함수를 다시 호출하지 않는다.
    again = None
    for _ in range(5):
        again = jira.find_by_receipt(ticket["receipt_no"])
        if again:
            break
        time.sleep(1)
    if again is None:
        print("  검색 반영 대기: 중복 생성 시험을 중단했습니다. 기존 생성 여부부터 확인하세요.")
        return False
    again = jira.create_ticket(ticket)
    print(f"  같은 접수로 다시 호출: {again['jira_key']}, created={again['created']} (False 여야 중복 없음)")
    return not diffs and again["created"] is False and again["jira_key"] == result["jira_key"]


def flow(jira: JiraClient, jira_key: str, my_account_id: str) -> bool:
    """생성한 시험 티켓에 ⑤⑥ 단계를 실제로 해 본다: 담당자 지정 → 재조회 비교 → 상태 전환."""
    ok = True
    r = jira.assign_issue(jira_key, my_account_id)
    print(f"  담당자 지정: 요청 {r['account_id'][:12]}… / Jira 값 {str(r['actual_account_id'])[:12]}… → matched={r['matched']}")
    ok = ok and r["matched"]
    print(f"  현재 상태: {jira.get_work_status(jira_key)['work_status']}")
    try:
        jira.transition_issue(jira_key, "CLS")
        print("  RDY → CLS 바로 전환: 허용됨 (예상과 다름, 워크플로 확인 필요)")
    except JiraError as e:
        print(f"  RDY → CLS 바로 전환: 거부됨 ({e.reason}) — 한 단계씩만 가능")
    for step in ("WIP", "FIN", "CLS"):
        try:
            res = jira.transition_issue(jira_key, step, final_result="[테스트] 연동 점검용 최종 처리 결과")
            print(f"  → {step}: changed={res['changed']}, Jira 상태={jira.get_work_status(jira_key)['work_status']}")
        except JiraError as e:
            print(f"  → {step}: 실패 {e.to_dict()}")
            ok = False
            break
    if jira.get_work_status(jira_key)["work_status"] == "CLS":  # CLS 까지 갔을 때만 되돌림 막기를 본다
        try:
            jira.transition_issue(jira_key, "WIP")
            print("  CLS → WIP 되돌리기: 허용됨 (막혀야 함)")
            ok = False
        except JiraError as e:
            print(f"  CLS → WIP 되돌리기: 코드가 막음 ({e.reason})")
    return ok


def _final_result(jira: JiraClient, jira_key: str) -> str:
    raw = jira.get_issue(jira_key, [FINAL_RESULT_FIELD])["fields"].get(FINAL_RESULT_FIELD)
    return adf_to_text(raw).strip()


def reopen_probe(jira: JiraClient, jira_key: str) -> bool:
    """FIN → WIP → FIN 재처리를 실제 Jira 워크플로로 해 보고, 「최종 처리 결과」가 어떻게 남는지 본다. CLS까지는 가지 않는다.

    FIN → WIP 는 클라이언트가 허용하는 유일한 되돌림이다(미해결 재처리). 그래서 정식 호출(transition_issue)로 한다.
    알아내려는 것: ① FIN 에서 WIP 로 가는 전환이 열려 있는가 ② WIP 로 돌아갔을 때 이전 결과가 필드에 남는가
    ③ 두 번째 FIN 에서 새 결과가 이전 결과를 덮어쓰는가, 이어 붙는가 ④ 이전 결과가 Jira 변경 이력에 남는가.
    전환 화면에 이전 결과가 미리 채워져 보이는지는 API로 알 수 없다. Jira 화면에서 직접 확인한다.
    """
    first, second = "[테스트] 1차 처리 결과 A", "[테스트] 2차 처리 결과 B"
    for step in ("WIP", "FIN"):
        jira.transition_issue(jira_key, step, final_result=first)
    print(f"  1차 FIN 완료. 필드 값: {_final_result(jira, jira_key)!r}")

    listed = jira._request("GET", f"/rest/api/3/issue/{jira_key}/transitions").get("transitions", [])
    print(f"  FIN 에서 갈 수 있는 상태: {[(t.get('to') or {}).get('name') for t in listed]}")
    wip_id = jira.mapping["options"]["work_status"]["values"]["WIP"]["id"]
    to_wip = next((t for t in listed if str((t.get("to") or {}).get("id")) == wip_id), None)
    if to_wip is None:
        print("  FIN → WIP 전환이 Jira 워크플로에 없습니다. 이 방향으로 가려면 Jira 관리자 설정 변경이 먼저 필요합니다.")
        return False
    try:
        jira.transition_issue(jira_key, "WIP")
    except JiraError as e:
        print(f"  FIN → WIP 전환 실패: {e.to_dict()} (전환 화면이 필수 입력을 요구할 수 있음)")
        return False
    after = jira.get_issue(jira_key, ["resolution", "resolutiondate"])["fields"]
    print(f"  FIN → WIP 후 상태: {jira.get_work_status(jira_key)['work_status']}, 필드 값: {_final_result(jira, jira_key)!r}")
    cleared = not after.get("resolution") and not after.get("resolutiondate")
    print(f"  해결 결과·해결 일시 비워짐: {cleared} (False 면 워크플로 FIN → WIP 후처리 확인)")

    jira.transition_issue(jira_key, "FIN", final_result=second)
    now = _final_result(jira, jira_key)
    if now == second:
        verdict = "새 결과로 덮어씀 (가이드화에 맞는 동작)"
    elif first in now and second in now:
        verdict = "이전 결과에 이어 붙음 (가이드에 실패한 조치가 섞일 수 있음)"
    elif now == first:
        verdict = "새 결과가 반영되지 않음"
    else:
        verdict = "예상 밖의 값"
    print(f"  2차 FIN 후 필드 값: {now!r} → {verdict}")

    kept = None
    try:
        hist = jira._request("GET", f"/rest/api/3/issue/{jira_key}/changelog").get("values", [])
        changes = [i for h in hist for i in h.get("items", []) if i.get("fieldId") == FINAL_RESULT_FIELD]
        kept = any(first in str(i.get("fromString") or "") or first in str(i.get("toString") or "") for i in changes)
        print(f"  변경 이력에 1차 결과가 남아 있음: {kept} (최종 처리 결과 변경 {len(changes)}건)")
    except JiraError as e:
        print(f"  변경 이력 조회 실패: {e.to_dict()} (Jira 화면의 이슈 이력에서 직접 확인)")
    if kept is not True:
        print("  이전 결과의 변경 이력 보존을 확인하지 못했습니다 → 확인 필요 (Jira 화면의 이슈 이력에서 직접 확인)")
    return now == second and cleared and kept is True


def main() -> int:
    try:
        with JiraClient.from_env() as jira:
            me = jira.check_auth()
            print(f"1. 인증 성공: {me['display_name']} (보고자로 들어갈 계정)")

            print("2. 기존 시험 접수 확인")
            ok = check(jira, EXISTING)

            if any(a in sys.argv for a in ("--create", "--flow", "--reopen")):
                stamp = datetime.now().strftime("%m%d%H%M")
                print("3. 새 시험 접수 생성")
                ticket = {**EXISTING, "receipt_no": f"RCPT-TEST-{stamp}"}
                ok = check(jira, ticket, create=True) and ok
                if "--flow" in sys.argv:
                    print("4. 담당자 지정 · 재조회 · 상태 전환")
                    found = jira.find_by_receipt(ticket["receipt_no"])
                    ok = flow(jira, found["jira_key"], me["account_id"]) and ok
                if "--reopen" in sys.argv:
                    print("4. FIN → WIP → FIN 재처리와 최종 처리 결과 확인")
                    found = jira.find_by_receipt(ticket["receipt_no"])
                    jira.assign_issue(found["jira_key"], me["account_id"])
                    ok = reopen_probe(jira, found["jira_key"]) and ok
    except JiraError as e:
        print(f"실패: {e.to_dict()}")
        return 1
    print("결과:", "모두 통과" if ok else "확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
