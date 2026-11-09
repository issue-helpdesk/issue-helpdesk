"""해결 사례 AI 가이드화 (M4, 기획_해결사례_가이드화). 7일 단위 실행이 judge_round 를 부른다.

    from app.agent.guide import judge_round
    run = judge_round(session, port, search_fn)     # 티켓 판단 → run.forwarded 를 묶기·초안으로

설명은 README.md.
"""
from app.agent.guide.run import Forwarded, JudgeRun, judge_round

__all__ = ['Forwarded', 'JudgeRun', 'judge_round']
