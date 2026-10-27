from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints
from pydantic.alias_generators import to_camel

from app.core.clock import to_kst


class CamelModel(BaseModel):
    """API JSON 은 camelCase, Backend 내부는 snake_case (docs/07.API_설계서.md 2.3)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


# 응답 시각은 KST, ISO 8601 (2.4)
KstDatetime = Annotated[datetime, PlainSerializer(lambda v: to_kst(v).isoformat(), return_type=str)]

# 일반 문자열은 앞뒤 공백을 제거한다. 비밀번호·토큰에는 쓰지 않는다 (2.6)
def trimmed_str(min_length: int | None = None, max_length: int | None = None):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]
