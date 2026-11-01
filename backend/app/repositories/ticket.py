from typing import Annotated, TypeVar

from fastapi import Depends

from app.db.session import DbSession
from app.models import TicketDraft

T = TypeVar("T")


class TicketRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, row: T) -> T:
        self.db.add(row)
        self.db.flush()
        return row

    def get_draft(self, draft_id: int) -> TicketDraft | None:
        return self.db.get(TicketDraft, draft_id)

    def get_draft_for_update(self, draft_id: int) -> TicketDraft | None:
        # 잠그기 전에 읽어 둔 값이 있어도 잠근 뒤의 값으로 다시 읽는다
        return self.db.get(TicketDraft, draft_id, with_for_update=True, populate_existing=True)


TicketRepositoryDep = Annotated[TicketRepository, Depends(TicketRepository)]
