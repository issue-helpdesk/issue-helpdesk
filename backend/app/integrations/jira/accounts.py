"""사번 ↔ Jira accountId 연결표를 읽는다 (jira_accounts.yaml).

네트워크를 쓰지 않는다. 표에 없거나 값이 비어 있는 사번은 None 이고, 선정 함수는 이를 "Jira 계정 없음"으로 본다.

    from app.integrations.jira import account_id_for, Member
    member = Member(user_id=7, employee_no="EMP-1370", jira_account_id=account_id_for("EMP-1370"), ...)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

ACCOUNTS_PATH = Path(__file__).with_name("jira_accounts.yaml")


@lru_cache(maxsize=1)
def load_account_map(path: Path = ACCOUNTS_PATH) -> dict[str, str]:
    """{사번: accountId}. 값이 비어 있는 줄은 뺀다. 한 계정이 두 사번에 걸려 있으면 ValueError."""
    with path.open(encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("accounts") or {}
    accounts = {str(k).strip(): str(v).strip() for k, v in raw.items() if v is not None and str(v).strip()}
    seen: dict[str, str] = {}
    for emp, account in accounts.items():
        if account in seen:
            raise ValueError(f"Jira 계정 {account} 가 {seen[account]} 와 {emp} 두 사번에 연결되어 있습니다(1:1이어야 합니다).")
        seen[account] = emp
    return accounts


def account_id_for(employee_no: str, accounts: Mapping[str, str] | None = None) -> str | None:
    accounts = load_account_map() if accounts is None else accounts
    return accounts.get(str(employee_no).strip())
