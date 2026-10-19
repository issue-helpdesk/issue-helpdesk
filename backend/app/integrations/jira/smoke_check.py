"""실제 Jira(ITSD)에 붙여 보는 점검 스크립트. 저장소 루트에서 실행한다.

    python backend/app/integrations/jira/smoke_check.py            # 인증 + 기존 시험 티켓 확인 (새로 만들지 않음)
    python backend/app/integrations/jira/smoke_check.py --create   # 위 + 새 시험 티켓 1건 생성

필요한 것: 루트 .env 의 JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN, pip install -r requirements.txt
토큰 값은 화면에 출력하지 않는다. 새로 만든 시험 티켓은 확인 후 Jira에서 직접 지운다.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from app.integrations.jira import JiraClient, JiraError  # noqa: E402

# 10.19에 로그인 세션으로 만든 시험 티켓(ITSD-353)과 같은 내용. 있으면 그 티켓을 찾아 돌려줘야 한다.
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


def check(jira: JiraClient, ticket: dict) -> bool:
    result = jira.create_ticket(ticket)
    action = "새로 만듦" if result["created"] else "이미 있어 그대로 돌려줌"
    print(f"  {ticket['receipt_no']} → {result['jira_key']} ({action})  {result['jira_url']}")
    diffs = jira.check_saved(result["jira_key"], ticket)
    print(f"  저장값 비교: {'차이 없음' if not diffs else diffs}")
    if result["created"]:
        time.sleep(5)  # 새 티켓이 Jira 검색에 잡히기까지 몇 초 걸린다
    again = jira.create_ticket(ticket)
    print(f"  같은 접수로 다시 호출: {again['jira_key']}, created={again['created']} (False 여야 중복 없음)")
    return not diffs and again["created"] is False and again["jira_key"] == result["jira_key"]


def main() -> int:
    try:
        with JiraClient.from_env() as jira:
            me = jira.check_auth()
            print(f"1. 인증 성공: {me['display_name']} (보고자로 들어갈 계정)")

            print("2. 기존 시험 접수 확인")
            ok = check(jira, EXISTING)

            if "--create" in sys.argv:
                stamp = datetime.now().strftime("%m%d%H%M")
                print("3. 새 시험 접수 생성")
                ok = check(jira, {**EXISTING, "receipt_no": f"RCPT-TEST-{stamp}"}) and ok
    except JiraError as e:
        print(f"실패: {e.to_dict()}")
        return 1
    print("결과:", "모두 통과" if ok else "확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
