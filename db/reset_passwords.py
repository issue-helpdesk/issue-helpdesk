"""users.password_hash 만 SEED_INITIAL_PASSWORD 의 Argon2id 해시로 바꾼다. 다른 컬럼·테이블은 건드리지 않는다.

    python db/reset_passwords.py --dry-run              # 바꿀 사용자 수만 확인
    python db/reset_passwords.py                        # 전체 사용자
    python db/reset_passwords.py -e E2024017 -e E2019042   # 지정한 사번만
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select, update             # noqa: E402
from sqlalchemy.orm import Session                # noqa: E402

from app.core.security import hash_password       # noqa: E402
from app.db.session import get_engine             # noqa: E402
from app.models import User                       # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-e", "--employee-no", action="append", help="바꿀 사번 (여러 번 지정 가능). 없으면 전체")
    parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 대상 수만 출력")
    args = parser.parse_args()

    password = os.environ.get("SEED_INITIAL_PASSWORD")
    if not password:
        sys.exit("SEED_INITIAL_PASSWORD 가 없습니다. 루트 .env 를 확인하세요.")

    where = [User.employee_no.in_(args.employee_no)] if args.employee_no else []
    with Session(get_engine()) as db:
        targets = db.scalars(select(User.employee_no).where(*where)).all()
        if args.employee_no:
            missing = sorted(set(args.employee_no) - set(targets))
            if missing:
                print("없는 사번:", ", ".join(missing))
        print(f"대상 {len(targets)}명")
        if args.dry_run or not targets:
            return

        # 사용자마다 솔트가 달라야 하므로 해시를 한 명씩 만든다
        for employee_no in targets:
            db.execute(update(User).where(User.employee_no == employee_no).values(password_hash=hash_password(password)))
        db.commit()
        print(f"{len(targets)}명 비밀번호 교체 완료")


if __name__ == "__main__":
    main()
