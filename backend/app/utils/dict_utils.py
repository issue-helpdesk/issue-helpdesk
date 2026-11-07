from typing import Any

from pydantic.alias_generators import to_camel


def camel_keys(value: Any) -> Any:
    """저장된 JSON 의 키를 안쪽까지 camelCase 로 바꾼다. 값은 그대로 둔다."""
    if isinstance(value, dict):
        return {to_camel(k): camel_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camel_keys(v) for v in value]
    return value


def add_counts(*counts: dict[str, int]) -> dict[str, int]:
    """키별 개수를 더한 새 dict. 입력은 바꾸지 않는다."""
    total: dict[str, int] = {}
    for c in counts:
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
    return total
