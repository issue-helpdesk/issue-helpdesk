"""청크 결과 확인용 명령.

    cd backend
    python -m app.rag.chunker <파일 또는 폴더> [...] [--out 결과폴더] [--baseline 기준표.json]

파일마다 청크 수·길이·검증 결과를 출력하고, --out 을 주면 <이름>.chunks.md 미리보기를 저장한다.
--baseline 을 주면 문서별 청크·항목·단위 수 기준표를 쓴다 (정리본은 app/rag/chunker/baseline.json).
"""
from . import main

raise SystemExit(main())
