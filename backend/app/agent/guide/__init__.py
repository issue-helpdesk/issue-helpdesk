"""해결 사례 AI 가이드화 (M4, 기획_해결사례_가이드화). 7일 단위 실행이 run_round 를 부른다.

    from app.agent.guide import run_round
    judged, drafted = run_round(session, port, search_fn, embed_fn)   # 판단 → 묶기 → 초안

설명은 README.md.
"""
from app.agent.guide.case import CaseFns
from app.agent.guide.run import DraftRun, Forwarded, JudgeRun, draft_round, judge_round, run_round

__all__ = ['CaseFns', 'DraftRun', 'Forwarded', 'JudgeRun', 'draft_round', 'judge_round', 'run_round']
