from typing import Any

from pydantic.alias_generators import to_camel


def camel_keys(value: Any) -> Any:
    """저장된 JSON 의 키를 안쪽까지 camelCase 로 바꾼다. 값은 그대로 둔다."""
    if isinstance(value, dict):
        return {to_camel(k): camel_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camel_keys(v) for v in value]
    return value
