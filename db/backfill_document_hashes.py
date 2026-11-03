"""document_versions.file_sha256 이 빈 행을 파일 내용으로 채운다. 다른 칸은 건드리지 않는다. 다시 돌려도 된다.

마이그레이션 e4b81d6f20a7 을 먼저 반영한다.

    python db/backfill_document_hashes.py --dry-run     # 바꿀 행과 문제만 확인
    python db/backfill_document_hashes.py
"""
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select                     # noqa: E402
from sqlalchemy.orm import Session                # noqa: E402

from app.db.session import get_engine             # noqa: E402
from app.models import DocumentVersion            # noqa: E402
from app.rag.ingest import ROOT                   # noqa: E402
from app.utils.file_utils import sha256_of        # noqa: E402


@dataclass
class Report:
    filled: list[int] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)            # 파일이 없거나 file_path 가 없는 버전
    duplicates: list[tuple[int, int]] = field(default_factory=list)   # (이 버전, 내용이 같은 버전). 비워 두고 알린다


def backfill(db: Session, root: Path = ROOT, *, dry_run: bool = False) -> Report:
    """커밋은 부르는 쪽이 한다. 같은 내용의 행은 UNIQUE 때문에 먼저 처리한 하나만 채운다."""
    report = Report()
    rows = db.scalars(select(DocumentVersion).order_by(DocumentVersion.id)).all()
    seen = {row.file_sha256: row.id for row in rows if row.file_sha256}
    for row in rows:
        if row.file_sha256:
            continue
        path = root / row.file_path if row.file_path else None
        if path is None or not path.is_file():
            report.missing.append(row.id)
            continue
        sha256 = sha256_of(path)
        if sha256 in seen:
            report.duplicates.append((row.id, seen[sha256]))
            continue
        seen[sha256] = row.id
        report.filled.append(row.id)
        if not dry_run:
            row.file_sha256 = sha256
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 대상만 출력")
    args = parser.parse_args()

    with Session(get_engine()) as db:
        report = backfill(db, dry_run=args.dry_run)
        print(f"채울 행 {len(report.filled)}개")
        if report.missing:
            print("파일이 없어 건너뜀 (버전 id):", ", ".join(map(str, report.missing)))
        for version_id, same_as in report.duplicates:
            print(f"내용이 같아 건너뜀: 버전 {version_id} = 버전 {same_as}")
        if args.dry_run:
            db.rollback()
            return
        db.commit()
        print(f"{len(report.filled)}개 채움")


if __name__ == "__main__":
    main()
