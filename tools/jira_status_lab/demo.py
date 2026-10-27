"""모의 상태 수신 서버에 실제 로컬 HTTP 요청을 보내는 시연."""
import argparse
import hashlib
import hmac
import json

import httpx

from receiver import DEMO_SECRET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", trust_env=False, timeout=15) as client:
        health = client.get("/health")
        health.raise_for_status()
        if health.json().get("mode") != "mock":
            raise SystemExit("모의 시연은 mock 모드에만 실행합니다.")
        cases = [("상태 변경", "jira:issue_updated", "status", "ITHD-DEMO", "status_resolved", "WIP"),
                 ("제목 변경", "jira:issue_updated", "summary", "ITHD-DEMO", "not_status_change", None),
                 ("댓글 사건", "comment_created", "status", "ITHD-DEMO", "ignored_event", None),
                 ("다른 티켓", "jira:issue_updated", "status", "ITHD-OTHER", "ignored_issue", None)]
        for label, event, field, key, reason, status in cases:
            payload = {"webhookEvent": event, "issue": {"key": key}, "changelog": {"id": "demo-1", "items": [
                {"field": field, "from": "10004", "to": "10005"}]}}
            body = json.dumps(payload).encode()
            signature = hmac.new(DEMO_SECRET.encode(), body, hashlib.sha256).hexdigest()
            r = client.post("/api/v1/webhooks/jira", content=body, headers={"X-Hub-Signature": "sha256=" + signature})
            r.raise_for_status()
            result = r.json()
            if result["reason"] != reason or result.get("work_status") != status or result["db_updated"]:
                raise SystemExit(f"FAIL {label}")
            print(f"PASS {label}: {reason}, work_status={status}")
    print("4개 로컬 HTTP 사례 통과. 실제 Jira 발신 웹훅과 DB 저장은 별도 시험입니다.")


if __name__ == "__main__":
    main()
