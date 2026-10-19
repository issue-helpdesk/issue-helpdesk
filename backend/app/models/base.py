from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, Text
from sqlalchemy.orm import DeclarativeBase

# 제약조건 이름 규칙. 이름이 있어야 나중에 마이그레이션으로 수정·삭제할 수 있다
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    # 파이썬 타입 → DB 타입 기본값
    type_annotation_map = {
        str: Text,
        int: BigInteger,
        datetime: DateTime(timezone=True),
    }
