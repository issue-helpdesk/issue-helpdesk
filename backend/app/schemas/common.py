from math import ceil
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints
from pydantic.alias_generators import to_camel

from app.utils.datetime_utils import to_kst


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

class GuideImage(CamelModel):
    """출처 본문의 '[그림] 설명' 에 대응하는 그림. 파일은 DC-11 로 받는다."""
    key: str
    caption: str


# 목록 응답 (2.5). JSON 은 items·page·size·totalCount·totalPages
class Page[T](CamelModel):
    items: list[T]
    page: int
    size: int
    total_count: int
    total_pages: int

    @classmethod
    def of(cls, items: list[T], page: int, size: int, total_count: int, **extra) -> "Page[T]":
        return cls(items=items, page=page, size=size, total_count=total_count,
                   total_pages=ceil(total_count / size) if total_count else 0, **extra)


class CountedPage[T](Page[T]):
    """상태 탭이 있는 목록. status_counts 는 상태 필터만 뺀 나머지 조건으로 센 상태별 건수다."""
    status_counts: dict[str, int]

    @classmethod
    def counted(cls, items: list[T], page: int, size: int, total_count: int, counts: dict, statuses: tuple[str, ...]):
        """statuses 의 모든 값을 키로 준다. 없는 상태는 0 이고, statuses 밖의 값(null 등)은 세지 않는다."""
        return cls.of(items, page, size, total_count, status_counts={s: counts.get(s, 0) for s in statuses})


# 페이지가 없는 목록
class ItemList[T](CamelModel):
    items: list[T]


# 목록 Query 공통 (2.5). sort 는 API 마다 허용 필드가 달라 하위 모델에서 정한다
class PageQuery(CamelModel):
    model_config = ConfigDict(extra="ignore")

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def sort_param(*fields: str):
    """'필드,방향' 형식. 허용 필드만 통과한다."""
    return Annotated[str, StringConstraints(pattern=rf"^({'|'.join(fields)}),(asc|desc)$")]


def parse_sort(sort: list[str]) -> list[tuple[str, bool]]:
    """['name,asc'] → [('name', False)]. 두 번째 값은 내림차순 여부."""
    return [(field, direction == "desc") for field, direction in (s.split(",") for s in sort)]
