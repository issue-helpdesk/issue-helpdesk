"""실제 Jira(ITHD)에 붙여 보는 점검 스크립트. 저장소 루트에서 실행한다.

    python backend/app/integrations/jira/smoke_check.py            # 인증 + 기존 시험 티켓 확인 (새로 만들지 않음)
    python backend/app/integrations/jira/smoke_check.py --create   # 위 + 새 시험 티켓 1건 생성
    python backend/app/integrations/jira/smoke_check.py --flow     # 위 + 담당자 지정·재조회·상태 전환(RDY→WIP→FIN→CLS)까지 (--create 포함)

필요한 것: 루트 .env 의 JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN, pip install -r requirements.txt
토큰 값은 화면에 출력하지 않는다. 새로 만든 시험 티켓은 확인 후 Jira에서 직접 지운다.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from app.integrations.jira import JiraClient, JiraError  # noqa: E402

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


def main() -> int:
    try:
        with JiraClient.from_env() as jira:
            me = jira.check_auth()
            print(f"1. 인증 성공: {me['display_name']} (보고자로 들어갈 계정)")

            print("2. 기존 시험 접수 확인")
            ok = check(jira, EXISTING)

            if "--create" in sys.argv or "--flow" in sys.argv:
                stamp = datetime.now().strftime("%m%d%H%M")
                print("3. 새 시험 접수 생성")
                ticket = {**EXISTING, "receipt_no": f"RCPT-TEST-{stamp}"}
                ok = check(jira, ticket, create=True) and ok
                if "--flow" in sys.argv:
                    print("4. 담당자 지정 · 재조회 · 상태 전환")
                    found = jira.find_by_receipt(ticket["receipt_no"])
                    ok = flow(jira, found["jira_key"], me["account_id"]) and ok
    except JiraError as e:
        print(f"실패: {e.to_dict()}")
        return 1
    print("결과:", "모두 통과" if ok else "확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
