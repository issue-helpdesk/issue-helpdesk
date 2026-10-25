"""접수 데이터를 ITHD 티켓 생성 요청으로 바꾼다.

입력 키는 06 테이블 설계서의 DB 컬럼 이름이다 (07 API 계약서 0장).
어떤 키가 어느 Jira 필드로 가는지는 field_mapping.yaml 의 fields·options·create 절이 정한다.
네트워크를 쓰지 않는 순수 변환이다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

MAPPING_PATH = Path(__file__).with_name("field_mapping.yaml")


class MappingError(ValueError):
    """Jira로 보낼 수 없는 접수 데이터. 다시 보내도 결과가 같아 재시도 대상이 아니다."""


@lru_cache(maxsize=1)
def load_mapping(path: Path = MAPPING_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _option(m: Mapping[str, Any], key: str, code: str) -> Mapping[str, Any]:
    values = m["options"][key]["values"]
    if code not in values:
        raise MappingError(f"{key} 값 '{code}'는 매핑에 없습니다. 가능한 값: {', '.join(values)}")
    return values[code]


def compose_description(ticket: Mapping[str, Any], m: Mapping[str, Any] | None = None) -> str:
    """description 이 있으면 그대로, 없으면 초안 항목(summary·onset·…)을 제목과 함께 이어 붙인다."""
    m = m or load_mapping()
    if _text(ticket.get("description")):
        return _text(ticket["description"])
    blocks = [
        f"[{label}]\n{_text(ticket.get(key))}"
        for key, label in m["create"]["description_parts"].items()
        if _text(ticket.get(key))
    ]
    return "\n\n".join(blocks)


def _adf(text: str) -> dict[str, Any]:
    """Jira Cloud v3 의 기본 description 은 ADF(문서 구조)로 받는다. 줄마다 문단 하나."""
    content = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
        for line in text.splitlines()
    ]
    return {"type": "doc", "version": 1, "content": content or [{"type": "paragraph"}]}


def to_jira_fields(ticket: Mapping[str, Any], m: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """접수 데이터 → POST /rest/api/3/issue 의 "fields"."""
    m = m or load_mapping()
    create = m["create"]

    missing = [k for k in create["required"] if not _text(ticket.get(k))]
    if missing:
        raise MappingError(f"필수 항목이 비어 있습니다: {', '.join(missing)}")

    values: dict[str, str] = {k: _text(v) for k, v in ticket.items() if _text(v)}
    description = compose_description(ticket, m)
    if description:
        values["description"] = description
    values.update(create["constants"])
    for key, source in create["derived"].items():
        if source in values:
            values[key] = values[source]

    max_len = create["text_max_length"]
    if len(values["receipt_no"]) > max_len:
        raise MappingError(f"receipt_no는 {max_len}자를 넘을 수 없습니다. 접수번호를 잘라 저장하지 않습니다.")
    issue_type = _option(m, "issue_type", create["issue_type"])
    out: dict[str, Any] = {
        "project": {"key": m["project"]["key"]},
        "issuetype": {"id": issue_type["id"]},
    }
    if description:
        out["description"] = _adf(description)  # 전체 글. customfield_10058 은 255자까지만

    for key, code in values.items():
        if key in create["skip"] or key not in m["fields"]:
            continue  # 매핑에 없는 키(초안 항목 등)는 보내지 않는다
        fdef = m["fields"][key]
        opt = m["options"].get(key)
        if fdef["type"] == "option":
            out[fdef["jira"]] = {"id": _option(m, key, code)["id"]}
        elif fdef["type"] == "string":
            # 글자 칸이라도 선택값이 정해진 키(request_kind·channel 등)는 코드 대신 Jira 저장값을 넣는다
            text = _option(m, key, code)["value"] if opt and opt["field"] == fdef["jira"] else code
            out[fdef["jira"]] = text[:max_len]
        # 같은 값을 다른 Jira 칸에도 넣는 경우: urgency → priority, group_name → components
        if opt and opt["field"] != fdef["jira"]:
            entry = _option(m, key, code)
            if opt["field"] == "components":
                out["components"] = [{"id": entry["id"]}]
            else:
                out[opt["field"]] = {"id": entry["id"]}

    return out


def work_status_from_jira(status_id: Any, m: Mapping[str, Any] | None = None) -> str | None:
    """Jira 상태 ID → ITssue 업무 상태(RDY·WIP·FIN·CLS). 매핑에 없는 상태면 None."""
    m = m or load_mapping()
    for code, entry in m["options"]["work_status"]["values"].items():
        if str(entry["id"]) == str(status_id):
            return code
    return None
