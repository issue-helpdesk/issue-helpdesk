"""업로드 파일 저장 (DC-07·10). 받는 동안 크기와 해시를 재고, 내용을 확인한 뒤에야 정식 파일 이름으로 남긴다."""
import hashlib
import logging
import time
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO

from app.constants import file as file_constants
from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.rag.ingest import ROOT
from app.rag.ingest.upload import resolve_file
from app.rag.parser import ParseError, check_file

logger = logging.getLogger(__name__)

STORAGE_DIR = ROOT / "storage" / "documents"


class StagedFile:
    """임시 파일. keep() 전에 끝나면 discard() 가 지운다."""

    def __init__(self, temp: Path, target: Path, sha256: str) -> None:
        self.temp, self.target, self.sha256 = temp, target, sha256

    def keep(self) -> Path:
        self.temp.rename(self.target)
        return self.target

    def discard(self) -> None:
        self.temp.unlink(missing_ok=True)


def stage_file(file: BinaryIO, document_id: int, suffix: str) -> StagedFile:
    """크기를 재며 임시 파일에 받고 내용을 확인한다."""
    folder = STORAGE_DIR / str(document_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    temp, target = folder / f"{name}{file_constants.TEMP_SUFFIX}", folder / f"{name}{suffix}"
    limit, size = file_constants.MAX_DOCUMENT_FILE_MB * 1024 * 1024, 0
    digest = hashlib.sha256()
    try:
        with temp.open("wb") as out:
            while chunk := file.read(file_constants.READ_SIZE_BYTES):
                size += len(chunk)
                if size > limit:
                    raise AppError(ErrorCode.DOCUMENT_FILE_TOO_LARGE, [
                        {"field": "file", "reason": "OUT_OF_RANGE", "message": "최대 크기",
                         "value": f"{file_constants.MAX_DOCUMENT_FILE_MB}MB"},
                    ])
                digest.update(chunk)
                out.write(chunk)
        check_content(temp, suffix)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return StagedFile(temp, target, digest.hexdigest())


def check_content(path: Path, suffix: str) -> None:
    """확장자가 아니라 파일 내용이 그 형식인지 본다. 잘못된 파일은 저장·적재하기 전에 거절한다."""
    try:
        check_file(str(path), suffix)       # 빈 파일, PDF 머리, zip 여부, 암호
        if suffix in file_constants.ZIP_REQUIRED_MEMBER:
            with zipfile.ZipFile(path) as archive:
                if file_constants.ZIP_REQUIRED_MEMBER[suffix] not in archive.namelist():
                    raise ParseError("corrupt", str(path), f"{file_constants.ZIP_REQUIRED_MEMBER[suffix]} 없음")
        if suffix in file_constants.TEXT_SUFFIXES:
            check_text(path)
    except ParseError as error:
        raise field_error(ErrorCode.DOCUMENT_FILE_FORMAT_UNSUPPORTED, "file", "INVALID_VALUE", error.message) from error
    except zipfile.BadZipFile as error:
        raise field_error(ErrorCode.DOCUMENT_FILE_FORMAT_UNSUPPORTED, "file", "INVALID_VALUE",
                          ParseError("corrupt").message) from error


def check_text(path: Path) -> None:
    """글자 파일인지 본다. 파서가 읽는 인코딩(utf-8, cp949)과 같다. 실행 파일 등은 NUL 바이트가 있다."""
    data = path.read_bytes()
    if b"\x00" in data:
        raise ParseError("corrupt", str(path), "NUL 바이트")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            data.decode(encoding)
            return
        except UnicodeDecodeError:
            continue
    raise ParseError("encoding", str(path))


def to_stored_path(path: Path) -> str:
    """DB 의 file_path. 저장소 루트 기준 상대 경로라 적재가 루트 밖 경로를 거부할 수 있다."""
    return path.relative_to(ROOT).as_posix()


def stored_file(file_path: str | None) -> Path:
    """DB 의 file_path → 실제 파일 위치. 저장소 루트 밖이거나 비어 있으면 IngestError (적재와 같은 규칙)."""
    return resolve_file(file_path, ROOT)


def remove_stored(file_path: str | None) -> None:
    """업로드로 저장한 파일만 지운다. dataset 의 가이드 원본은 file_path 가 있어도 지우지 않는다."""
    if not file_path:
        return
    path = (ROOT / file_path).resolve()
    if path.is_relative_to(STORAGE_DIR.resolve()):
        path.unlink(missing_ok=True)


def cleanup_temp_files(*, known_paths: set[str] | None = None, now: float | None = None) -> int:
    """오래된 임시 파일을 지우고 지운 수를 돌려준다. 받는 중인 파일을 건드리지 않게 오래된 것만 본다.

    known_paths 를 주면 DB 에 없는 저장 파일을 로그로 알린다. 잘못 지우면 되돌릴 수 없어 지우지는 않는다.
    """
    if not STORAGE_DIR.exists():
        return 0
    cutoff = (now or time.time()) - file_constants.TEMP_FILE_MAX_AGE_HOURS * 3600
    removed = 0
    for path in STORAGE_DIR.rglob("*"):
        if not path.is_file() or path.stat().st_mtime > cutoff:
            continue
        if path.suffix == file_constants.TEMP_SUFFIX:
            path.unlink(missing_ok=True)
            removed += 1
        elif known_paths is not None and to_stored_path(path) not in known_paths:
            logger.warning("DB 에 없는 업로드 파일: %s", to_stored_path(path))
    if removed:
        logger.info("오래된 업로드 임시 파일 %d개를 지웠습니다", removed)
    return removed
