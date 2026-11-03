import hashlib
from pathlib import Path

READ_SIZE_BYTES = 1024 * 1024


def sha256_of(path: Path) -> str:
    """파일 내용의 SHA-256. 큰 파일도 메모리에 다 올리지 않는다."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(READ_SIZE_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
