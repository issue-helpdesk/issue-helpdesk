"""시연용 운영 데이터 (도입 뒤 2026-09-01 ~ 2026-11-05) 를 DB 에 넣는다. 사람이 직접 실행할 때만 돈다.

대시보드(/dashboard/overview·me·ai-usage)·문의 목록·담당자 대기열이 비어 보이지 않게
문의 → 대화 → AI 판단·근거 → LLM 호출 → (담당자 연결이면) 초안 → 티켓 → 배정·상태 이력·알림 을 만든다.

    python db/demo_seed.py --database-url <DB> --plan                 # 넣을 양만 (쓰지 않음)
    python db/demo_seed.py --database-url <DB> --apply                # 넣고 id 목록 demo_seed_ids_*.json 을 남김
    python db/demo_seed.py --database-url <DB> --delete <ids.json>    # 그 id 만 지움 (넣은 것 되돌리기)
    --env : 주소를 저장소 .env 의 DATABASE_URL 에서 (출력하지 않음). 원격 DB 면 --allow-remote 도 필요
    --out : id 목록을 남길 폴더 (기본 현재 폴더). 이 파일이 있어야 넣은 것만 지울 수 있으니 보관한다

- backend 의존성으로 돈다 (backend 폴더에서 `uv run python ../db/demo_seed.py ...`).
- 테이블·사용자·지원 그룹·문의 유형·가이드 청크·과거 이력이 먼저 있어야 한다 (alembic, db/seed.py, 가이드 적재).
- 다시 넣을 때는 먼저 --delete 로 지운다 (그냥 다시 --apply 하면 600건이 더 들어간다).

규칙
- 문의자: 활성 사용자(EMP- 사번) 모두 1건 이상, 나머지는 일반 임직원 위주. 시연 계정은 더 많이 (--demo-*)
- 내용: dataset/data/history.csv 의 제목·설명·해결 (세부 유형·긴급도 그대로). LLM 은 부르지 않는다
- 담당: 세부 유형의 기본 그룹 → 그 그룹 활성·배정 가능 구성원 (전문 분야 우선, 문의자 본인 제외)
- 근거: 그 세부 유형의 현행·전체 공개 가이드 청크 (+ 가끔 같은 유형 과거 이력)
- Jira: 키 없음, jira_sync_status=SYNCED, 연동 작업(integration_jobs) 안 만듦 → worker 가 집어 가지 않음
  (그래서 시연 데이터의 열린 티켓 상태를 화면에서 바꾸면 Jira 연동이 실패한다. 실시간 시연은 새 문의로)
- 가이드화: 해결 내용이 결과 한 줄뿐이라 모든 시연 티켓을 ticket_guide_states EXCLUDED 로 넣어 회차 대상에서 뺀다
- 같은 --seed 면 같은 결과. 한 트랜잭션.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
MODEL, ADAPTER = 'claude-sonnet-5-5', 'Claude'

# 처리 결과 비율 (history 의 처리 방식·긴급도로 조금씩 기울인다)
OUTCOMES = {                       # 이름: (가중치)
    'ai_resolved': 46,             # ANSWER → 해결 확인
    'answer_then_ticket': 12,      # ANSWER → 미해결 → 담당자 연결
    'escalate_ticket': 28,         # ESCALATE → 담당자 연결
    'escalate_declined': 3,        # ESCALATE 제안했지만 연결 안 하고 끝냄
    'out_of_scope': 4,
    'ask_more_no_reply': 4,        # 되묻기 뒤 답 없음
    'answer_unconfirmed': 3,       # 최근 며칠만: 답했지만 해결 확인 전
}


def kst(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KST)


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def load_ref(cur) -> dict:
    q = lambda s, *a: cur.execute(s, a).fetchall()
    ref = {}
    ref['users'] = q("select id, employee_no, name, service_role from users where account_status='ACTIVE' "
                     "and employee_no like 'EMP-%%' order by id")
    ref['types'] = {code: dict(id=i, cat=cat, group=g, urg=u, name=n, kind=k) for i, code, cat, g, u, n, k in
                    q('select id, code, category_code, default_group_id, default_urgency, name, request_kind '
                      'from inquiry_types where is_active')}
    ref['groups'] = {i: n for i, n in q('select id, name from support_groups where is_active')}
    ref['triage'] = q('select id from support_groups where is_triage and is_active')[0][0]
    members = defaultdict(list)
    for g, u in q('select group_id, user_id from support_group_members where is_active and assignable'):
        members[g].append(u)
    ref['members'] = members
    skills = defaultdict(set)
    for u, t in q('select user_id, inquiry_type_id from member_skills'):
        skills[t].add(u)
    ref['skills'] = skills
    chunks = defaultdict(list)
    for cid, code, doc, ver, loc, content in q(
            "select c.id, x.code, d.doc_code, v.version, c.location, c.content from document_chunks c "
            "join document_versions v on v.id = c.version_id join knowledge_documents d on d.id = v.document_id "
            "cross join lateral jsonb_array_elements_text(coalesce(c.meta->'inquiry_type_codes', '[]')) x(code) "
            "where v.is_current and v.view_scope = 'ALL' and c.chunk_type = 'ITEM'"):
        chunks[code].append((cid, doc, ver, loc, content))
    ref['chunks'] = chunks
    legacy = defaultdict(list)
    for lid, tid in q("select id, inquiry_type_id from legacy_inquiries where view_scope = 'ALL'"):
        legacy[tid].append(lid)
    ref['legacy'] = legacy
    return ref


def read_history() -> list[dict]:
    with open(ROOT / 'dataset' / 'data' / 'history.csv', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def plan(ref: dict, history: list[dict], args) -> list[dict]:
    rnd = random.Random(args.seed)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    days = business_days(start, end)
    rows = [h for h in history if h['scenario_id'] in ref['types']]
    users = ref['users']
    by_no = {u[1]: u for u in users}
    # 문의자: 모두 1건 + 시연 계정 추가 + 나머지는 일반 임직원 위주
    requesters = [u[0] for u in users]
    for no, extra in ((args.demo_employee, args.demo_extra), (args.demo_employee2, args.demo_extra)):
        if no in by_no:
            requesters += [by_no[no][0]] * extra
    employees = [u[0] for u in users if u[3] == 'EMPLOYEE']
    others = [u[0] for u in users if u[3] != 'EMPLOYEE']
    while len(requesters) < args.count:
        requesters.append(rnd.choice(employees) if rnd.random() < 0.9 else rnd.choice(others))
    rnd.shuffle(requesters)
    demo_agent = by_no.get(args.demo_agent, (None,))[0]

    # 날짜: 뒤로 갈수록 조금 많게 (도입 뒤 쓰는 사람이 늘어나는 모양)
    weights = [1 + 0.8 * i / len(days) for i in range(len(days))]
    out = []
    for n, uid in enumerate(requesters):
        h = rnd.choice(rows)
        t = ref['types'][h['scenario_id']]
        d = rnd.choices(days, weights)[0]
        hour = rnd.choices(range(9, 18), [5, 9, 8, 4, 6, 8, 8, 7, 4])[0]
        at = kst(d, hour, rnd.randrange(60)) + timedelta(seconds=rnd.randrange(60))
        age = (kst(end, 18, 0) - at).days
        w = dict(OUTCOMES)
        if h['urgency'] in ('P1', 'P2'):
            w['escalate_ticket'] *= 3
            w['ai_resolved'] //= 2
        if h['handling_type'] == '즉시 처리':
            w['ai_resolved'] *= 2
        if t['kind'] == 'REQUEST':
            w['answer_then_ticket'] += 4
        if age > 3:
            w['answer_unconfirmed'] = 0
        outcome = rnd.choices(list(w), list(w.values()))[0]
        if not ref['chunks'].get(h['scenario_id']) and outcome in ('ai_resolved', 'answer_then_ticket', 'answer_unconfirmed'):
            outcome = 'escalate_ticket'          # 근거로 쓸 가이드 청크가 없는 유형은 답하지 않는다
        item = dict(n=n, user=uid, h=h, type=t, at=at, outcome=outcome)
        if outcome in ('answer_then_ticket', 'escalate_ticket'):
            group = t['group'] or ref['triage']
            pool = [u for u in ref['members'].get(group, []) if u != uid] or \
                   [u for u in ref['members'].get(ref['triage'], []) if u != uid]
            skilled = [u for u in pool if u in ref['skills'].get(t['id'], set())]
            if demo_agent in pool and demo_agent != uid and rnd.random() < args.demo_agent_share:
                assignee = demo_agent
            else:
                assignee = rnd.choice(skilled if skilled and rnd.random() < 0.8 else pool)
            # 업무 상태: 오래된 것은 대부분 끝남, 최근은 열려 있음
            if age >= 7:
                work = rnd.choices(['CLS', 'FIN'], [93, 7])[0]
            elif age >= 2:
                work = rnd.choices(['CLS', 'FIN', 'WIP', 'RDY'], [55, 20, 18, 7])[0]
            else:
                work = rnd.choices(['CLS', 'FIN', 'WIP', 'RDY'], [15, 15, 35, 35])[0]
            item.update(group=group, assignee=assignee, work=work)
        out.append(item)
    return out


def minutes(rnd, lo, hi):
    return timedelta(minutes=rnd.uniform(lo, hi))


def resolution_text(h) -> str:
    r = (h['resolution'] or '').strip()
    return r.split('—', 1)[-1].strip() if r.startswith('[') and '—' in r else r


def insert(cur, table: str, row: dict, ids: dict) -> int:
    cols = list(row)
    # jsonb 칸은 Jsonb 로 감싼다. missing_items 는 text[] 라 목록 그대로
    vals = [Jsonb(v) if isinstance(v, dict) or (isinstance(v, list) and k != 'missing_items') else v
            for k, v in row.items()]
    rid = cur.execute(f"insert into {table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) returning id",
                      vals).fetchone()[0]
    ids[table].append(rid)
    return rid


def apply(cur, ref: dict, items: list[dict], args) -> dict:
    rnd = random.Random(args.seed + 1)
    ids: dict[str, list[int]] = defaultdict(list)
    for it in items:
        h, t, at, oc, uid = it['h'], it['type'], it['at'], it['outcome'], it['user']
        ticketed = oc in ('answer_then_ticket', 'escalate_ticket')
        action = {'ai_resolved': 'ANSWER', 'answer_then_ticket': 'ANSWER', 'answer_unconfirmed': 'ANSWER',
                  'escalate_ticket': 'ESCALATE', 'escalate_declined': 'ESCALATE', 'out_of_scope': 'OUT_OF_SCOPE',
                  'ask_more_no_reply': 'ASK_MORE'}[oc]
        cat = None if oc == 'out_of_scope' else t['cat']
        tid = None if oc == 'out_of_scope' else t['id']
        urg = None if oc == 'out_of_scope' else h['urgency']
        group = it.get('group') or (None if oc == 'out_of_scope' else (t['group'] or ref['triage']))
        chunks = ref['chunks'].get(h['scenario_id'], [])
        src = rnd.sample(chunks, min(len(chunks), rnd.choice([1, 2, 2, 3]))) if chunks and action == 'ANSWER' else []

        # 시각
        ai_at = at + timedelta(seconds=rnd.uniform(5, 14))
        end_at = ai_at + minutes(rnd, 1, 8)
        # 대화
        user_msg = h['description'] or h['title']
        if action == 'ANSWER':
            doc = f" 자세한 절차는 {src[0][1]} {src[0][3]}을 참고해 주세요." if src else ''
            reply = (resolution_text(h) or '가이드에 따라 조치해 보세요.') + doc
        elif action == 'ESCALATE':
            reply = '말씀하신 내용은 담당자 확인이 필요해요. 담당자에게 연결해 드릴까요? 연결하면 지금까지 내용으로 접수 초안을 만들어 드려요.'
        elif action == 'OUT_OF_SCOPE':
            reply = 'IT 헬프데스크에서 도와드릴 수 있는 범위 밖의 문의예요. 해당 부서에 문의해 주세요.'
        else:
            reply = '어떤 시스템(프로그램·장비)에서 어떤 증상이 나는지 조금 더 알려 주세요.'

        status, result, closed, end_reason = {
            'ai_resolved': ('AI_RESOLVED', 'RESOLVED', end_at, 'USER_END'),
            'answer_unconfirmed': ('IN_PROGRESS', None, None, None),
            'escalate_declined': ('CLOSED_UNRESOLVED', None, end_at, 'USER_END'),
            'out_of_scope': ('CLOSED_UNRESOLVED', None, end_at, 'USER_END'),
            'ask_more_no_reply': ('CLOSED_UNRESOLVED', 'NO_RESPONSE', end_at + timedelta(minutes=30), 'NO_RESPONSE'),
            'answer_then_ticket': ('HANDED_OFF', 'UNRESOLVED', None, 'HANDED_OFF'),
            'escalate_ticket': ('HANDED_OFF', None, None, 'HANDED_OFF'),
        }[oc]

        inq = insert(cur, 'inquiries', dict(
            user_id=uid, title=h['title'], status=status, category_code=cat, inquiry_type_id=tid, urgency=urg,
            action=action, recommended_group_id=group if action in ('ANSWER', 'ESCALATE') else None,
            resolution_result=result, created_at=at, updated_at=closed or end_at, closed_at=closed), ids)
        sess = insert(cur, 'chat_sessions', dict(inquiry_id=inq, started_at=at,
                                                  ended_at=None if oc == 'answer_unconfirmed' else (closed or end_at),
                                                  end_reason=end_reason), ids)
        insert(cur, 'messages', dict(session_id=sess, seq=1, sender='USER', content=user_msg, created_at=at), ids)
        ai_msg = insert(cur, 'messages', dict(session_id=sess, seq=2, sender='AI', content=reply, created_at=ai_at), ids)
        for rank, (cid, doc, ver, loc, content) in enumerate(src, 1):
            insert(cur, 'message_sources', dict(message_id=ai_msg, source_kind='DOCUMENT', chunk_id=cid, doc_code=doc,
                                                version=ver, location=loc, excerpt=content[:200], rank=rank), ids)
        legacy = ref['legacy'].get(tid or -1, [])
        if legacy and action in ('ANSWER', 'ESCALATE') and rnd.random() < 0.3:
            insert(cur, 'message_sources', dict(message_id=ai_msg, source_kind='LEGACY',
                                                legacy_inquiry_id=rnd.choice(legacy), rank=len(src) + 1), ids)
        urgent = urg == 'P1'
        reason = f"{t['name']} 기본 긴급도 {t['urg']}에서 시작해요." + (' 업무가 멈춘 범위가 넓어 올렸어요.' if urg and urg < t['urg'] else '')
        facts = {'summary': h['title'], 'symptom': h['subcategory'], 'target_system': h['tool'],
                 'impact_scope': {'개인': 'PERSONAL', '부서': 'TEAM', '전사': 'COMPANY'}.get(h['impact_scope']),
                 'occurred_at': None, 'tried_actions': [], 'work_stopped': 'unknown'}
        out = {'schema_version': '1.0', 'title': h['title'], 'action': action, 'category_code': cat,
               'inquiry_type_code': None if oc == 'out_of_scope' else h['scenario_id'], 'urgency': urg,
               'urgent_signal': urgent, 'missing_items': ['symptom'] if action == 'ASK_MORE' else [],
               'reply': reply, 'facts': facts, 'confidence': round(rnd.uniform(0.62, 0.93), 2),
               'evidence': [{'kind': 'DOCUMENT', 'source_id': f'{d}@{v}', 'quote': c[:80]} for _, d, v, _, c in src],
               'rationale': {'category': f"{t['name']}({h['scenario_id']}) 문의로 분류했어요.", 'urgency_reasons': [reason]}}
        insert(cur, 'inquiry_assessments', dict(
            inquiry_id=inq, facts=facts, missing_items=out['missing_items'], urgent_signal=urgent, category_code=cat,
            inquiry_type_id=tid, urgency=urg, urgency_reason=None if urg is None else reason, action=action,
            ai_output=out, override_reasons=[], created_at=ai_at), ids)
        # LLM 호출: 판단 1번, 답변이면 답변 1번. 가끔 실패 후 다시
        calls = [('CLASSIFY', 6600, 7900, 760)] + ([('ANSWER', 8300, 13600, 1040)] if action == 'ANSWER' else [])
        for purpose, lat, inp, outp in calls:
            if rnd.random() < 0.02:
                insert(cur, 'llm_calls', dict(inquiry_id=inq, purpose=purpose, model=MODEL, adapter=ADAPTER,
                                              latency_ms=int(rnd.uniform(20000, 30000)), success=False,
                                              error_code='TIMEOUT', created_at=at + timedelta(seconds=1)), ids)
            insert(cur, 'llm_calls', dict(
                inquiry_id=inq, purpose=purpose, model=MODEL, adapter=ADAPTER,
                latency_ms=max(1500, int(rnd.gauss(lat, lat * 0.25))), input_tokens=max(1500, int(rnd.gauss(inp, inp * 0.2))),
                output_tokens=max(150, int(rnd.gauss(outp, outp * 0.3))), success=True,
                created_at=ai_at - timedelta(seconds=rnd.uniform(0.5, 3))), ids)

        if not ticketed:
            continue
        # 초안 → 티켓
        draft_at = end_at
        made_at = draft_at + minutes(rnd, 0.5, 4)
        draft = insert(cur, 'ticket_drafts', dict(
            inquiry_id=inq, session_id=sess, summary=h['description'] or h['title'], target_system=h['tool'],
            symptom=h['subcategory'], occurred_at='오늘', category_code=cat, inquiry_type_id=tid, urgency=urg,
            urgency_reason=reason, business_impact={'개인': '개인 업무 지장', '부서': '부서 업무 지장', '전사': '전사 업무 지장'}.get(h['impact_scope']),
            tried_actions='안내받은 조치를 해 봤지만 해결되지 않음' if oc == 'answer_then_ticket' else None,
            recommended_group_id=group, status='CONFIRMED', created_at=draft_at, updated_at=made_at), ids)
        speed = {'P1': 0.15, 'P2': 0.4, 'P3': 1.0, 'P4': 1.6}.get(urg, 1.0)
        assign_at = made_at + minutes(rnd, 1, 25 * speed)
        wip_at = assign_at + minutes(rnd, 5, 180 * speed)
        fin_at = wip_at + minutes(rnd, 20, 1500 * speed)
        cls_at = fin_at + minutes(rnd, 30, 1200)
        work = it['work']
        now_cap = kst(date.fromisoformat(args.end), 18, 0)
        # 열린 티켓은 지금보다 뒤 시각이 생기지 않게 자른다
        if work == 'RDY':
            wip_at = fin_at = cls_at = None
        elif work == 'WIP':
            fin_at = cls_at = None
        elif work == 'FIN':
            cls_at = None
        assign_at = min(assign_at, now_cap)
        wip_at = wip_at and min(wip_at, now_cap)
        fin_at = fin_at and min(fin_at, now_cap)
        cls_at = cls_at and min(cls_at, now_cap)
        last = cls_at or fin_at or wip_at or assign_at
        tk_id = cur.execute("select nextval(pg_get_serial_sequence('tickets', 'id'))").fetchone()[0]
        note = resolution_text(h) or '조치 완료'
        cur.execute(
            'insert into tickets (id, receipt_no, draft_id, inquiry_id, session_id, summary, target_system, symptom, '
            'occurred_at, category_code, inquiry_type_id, urgency, urgency_reason, business_impact, tried_actions, '
            'group_id, assignee_id, jira_key, jira_sync_status, assign_status, work_status, resolution_note, created_at, '
            'finished_at, closed_at, requested_work_status, transition_status, work_status_confirmed_at, '
            'resolution_confirmed_at, assignment_revision) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'
            'null,%s,%s,%s,%s,%s,%s,%s,null,%s,%s,%s,%s)',
            (tk_id, f'RCPT-{tk_id:04d}', draft, inq, sess, h['description'] or h['title'], h['tool'], h['subcategory'],
             '오늘', cat, tid, urg, reason, None, None, it['group'], it['assignee'], 'SYNCED', 'ASSIGNED', work,
             note if work in ('FIN', 'CLS') else None, made_at, fin_at, cls_at, 'IDLE', last, cls_at, 1))
        ids['tickets'].append(tk_id)
        cur.execute("insert into ticket_guide_states (ticket_id, status, exclude_reason) "
                    "values (%s, 'EXCLUDED', '시연 데이터')", (tk_id,))
        insert(cur, 'assignment_logs', dict(ticket_id=tk_id, event='RECOMMEND', group_id=it['group'],
                                             reason='세부 유형 기본 그룹', created_at=made_at), ids)
        insert(cur, 'assignment_logs', dict(ticket_id=tk_id, event='ASSIGN', group_id=it['group'], assignee_id=it['assignee'],
                                             reason='전문 분야·업무량 기준 자동 배정', created_at=assign_at), ids)
        insert(cur, 'notifications', dict(ticket_id=tk_id, recipient_id=it['assignee'], kind='ASSIGNED', created_at=assign_at,
                                           read_at=wip_at), ids)
        steps = [('RDY', 'WIP', wip_at, it['assignee'], None), ('WIP', 'FIN', fin_at, it['assignee'], note),
                 ('FIN', 'CLS', cls_at, uid, None)]
        for frm, to, when, actor, rn in steps:
            if when is None:
                break
            insert(cur, 'ticket_status_history', dict(ticket_id=tk_id, from_status=frm, to_status=to, source='ITSSUE',
                                                       actor_id=actor, changed_at=when, resolution_note=rn), ids)
        if fin_at:
            insert(cur, 'notifications', dict(ticket_id=tk_id, recipient_id=uid, kind='FIN', created_at=fin_at, read_at=cls_at), ids)
        if cls_at:
            insert(cur, 'audit_logs', dict(event_type='CONFIRM', target_type='ticket', target_id=tk_id, actor_id=uid,
                                            result=f'RCPT-{tk_id:04d}', created_at=cls_at), ids)
        cur.execute('update inquiries set resolution_result = %s, updated_at = %s, closed_at = %s where id = %s',
                    ('RESOLVED' if cls_at else result, last, cls_at, inq))
    return ids


DELETE_ORDER = ['audit_logs', 'notifications', 'ticket_status_history', 'assignment_logs', 'tickets',
                'llm_calls', 'inquiry_assessments', 'message_sources', 'messages', 'ticket_drafts', 'chat_sessions', 'inquiries']


def summary(items):
    from collections import Counter
    c = Counter(i['outcome'] for i in items)
    w = Counter(i.get('work') for i in items if i.get('work'))
    return {'문의': len(items), '결과': dict(c), '티켓 업무 상태': dict(w),
            '문의자 수': len({i['user'] for i in items}), '담당자 수': len({i['assignee'] for i in items if i.get('assignee')})}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--database-url')
    ap.add_argument('--env', action='store_true', help='주소를 저장소 .env DATABASE_URL 에서 (출력하지 않음)')
    ap.add_argument('--allow-remote', action='store_true')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--plan', action='store_true')
    g.add_argument('--apply', action='store_true')
    g.add_argument('--delete', metavar='IDS_JSON')
    ap.add_argument('--start', default='2026-09-01')
    ap.add_argument('--end', default='2026-11-05')
    ap.add_argument('--count', type=int, default=600)
    ap.add_argument('--seed', type=int, default=20261105)
    ap.add_argument('--demo-employee', default='EMP-1114')
    ap.add_argument('--demo-employee2', default='EMP-1001')
    ap.add_argument('--demo-extra', type=int, default=12, help='시연 문의자 계정마다 더 줄 문의 수')
    ap.add_argument('--demo-agent', default='EMP-1321')
    ap.add_argument('--demo-agent-share', type=float, default=0.35, help='시연 담당자 그룹 티켓 중 그 사람에게 줄 비율')
    ap.add_argument('--out', default='.', help='id 목록을 남길 폴더')
    args = ap.parse_args()
    if args.env:
        from dotenv import dotenv_values
        url = dotenv_values(ROOT / '.env')['DATABASE_URL']
    else:
        url = args.database_url
    if not url:
        sys.exit('--database-url 또는 --env')
    url = url.replace('postgresql+psycopg://', 'postgresql://')
    if urlparse(url).hostname not in ('localhost', '127.0.0.1') and not args.allow_remote:
        sys.exit('원격 DB 입니다. --allow-remote 를 주세요')
    with psycopg.connect(url, connect_timeout=15) as conn, conn.cursor() as cur:
        if args.delete:
            ids = json.loads(Path(args.delete).read_text(encoding='utf-8'))
            if ids.get('tickets'):
                cur.execute('delete from ticket_guide_states where ticket_id = any(%s)', (ids['tickets'],))
                print(f'지움 ticket_guide_states: {cur.rowcount}')
            for t in DELETE_ORDER:
                if ids.get(t):
                    cur.execute(f'delete from {t} where id = any(%s)', (ids[t],))
                    print(f'지움 {t}: {cur.rowcount}')
            conn.commit()
            return
        ref = load_ref(cur)
        items = plan(ref, read_history(), args)
        print(json.dumps(summary(items), ensure_ascii=False))
        if args.plan:
            return
        ids = apply(cur, ref, items, args)
        # id 목록을 먼저 남기고 확정한다 (파일을 못 쓰면 확정하지 않아 되돌릴 수 없는 일이 없게)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        out = Path(args.out) / f'demo_seed_ids_{stamp}.json'
        out.write_text(json.dumps(ids, ensure_ascii=False), encoding='utf-8')
        conn.commit()
        print('넣음', {t: len(v) for t, v in ids.items()}, '→', out)


if __name__ == '__main__':
    main()
