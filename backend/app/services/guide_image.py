"""가이드 그림 (DC-11). 파일은 DB 에 넣지 않고 dataset/guide_images/{key} 에 둔다 (청크_메타데이터.md 5장 그림).

매뉴얼 그림은 담당자용이라 정적 경로로 열지 않고, 그림을 쓰는 청크의 열람 범위를 요청마다 본다.
"""
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from app.core.config import ROOT
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.core.permissions import visible_scopes
from app.models import User
from app.repositories.document import DocumentRepositoryDep
from app.schemas.common import GuideImage

IMAGE_DIR = ROOT / "dataset" / "guide_images"
KEY_RE = re.compile(r"^[A-Z]+/[A-Za-z0-9][A-Za-z0-9._-]*\.(png|jpe?g)$")


def images_of(metas: Iterable[dict | None]) -> list[GuideImage]:
    """청크 meta 들의 그림을 나온 순서대로. 같은 그림은 한 번만."""
    found = {image["key"]: image["caption"] for meta in metas for image in (meta or {}).get("images", [])}
    return [GuideImage(key=key, caption=caption) for key, caption in found.items()]


class GuideImageService:
    def __init__(self, documents: DocumentRepositoryDep) -> None:
        self.documents = documents

    def find_file(self, key: str, viewer: User) -> Path:
        """이름표 형식·열람 범위·파일을 확인한다. 어느 쪽이든 안 되면 같은 404 로 그림이 있는지 알리지 않는다."""
        path = (IMAGE_DIR / key).resolve()
        visible = KEY_RE.fullmatch(key) and path.is_relative_to(IMAGE_DIR.resolve()) and path.is_file()
        if not visible or not self.documents.image_scopes(key) & set(visible_scopes(viewer.service_role)):
            raise AppError(ErrorCode.GUIDE_IMAGE_NOT_FOUND)
        return path


GuideImageServiceDep = Annotated[GuideImageService, Depends(GuideImageService)]
