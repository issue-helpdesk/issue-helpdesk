"""Opt-in synthetic prompt evaluation. Default performs no network calls or model spending."""
import argparse
import json
from pathlib import Path

from app.agent.llm import AIInput, CategoryInfo, Taxonomy, TypeInfo, UserContext, call_judge, get_llm_adapter

ROOT = Path(__file__).resolve().parents[3]


def evaluation_taxonomy() -> Taxonomy:
    source = json.loads((ROOT / 'dataset/data/taxonomy.json').read_text())
    return Taxonomy(
        tuple(CategoryInfo(c['code'], c['name'], c.get('scope', '')) for c in source['category_detail']),
        tuple(TypeInfo(c['id'], c['cat'], c['sub'],
                       {'장애': 'INCIDENT', '요청': 'REQUEST', '문의': 'QUESTION'}.get(c['type'], c['type']), c['urg'])
              for c in source['scenarios']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Call the configured LLM using only synthetic fixtures')
    parser.add_argument('--limit', type=int, default=140)
    parser.add_argument('--output', type=Path, default=Path('/tmp/security-evaluation.json'))
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    cases = json.loads((ROOT / 'tests/fixtures/security_scenarios.json').read_text())[:args.limit]
    if not args.live:
        print(f'{len(cases)} synthetic cases ready. No LLM calls. Use --live to run paid evaluation.')
        return
    taxonomy = evaluation_taxonomy()
    port = get_llm_adapter()
    results = []
    for case in cases:
        inp = AIInput(session_id='synthetic', inquiry_id=case['id'], message=case['message'], history=case['history'],
            ask_more_count=0, user_context=UserContext(employee_no='SYNTHETIC', service_role='EMPLOYEE'), search=None)
        judged = call_judge(inp, port, taxonomy, [], 'SECURITY_EVAL')
        out = judged.output
        rules = set(out.security_rule_ids)
        if out.facts.security_suspected:
            rules.add('S01')
        passed = (judged.failure is None and set(case['required_rules']) <= rules
                  and bool(rules) == case['expected_review']
                  and out.urgent_signal == case['expected_urgent'])
        results.append({'id': case['id'], 'passed': passed, 'rules': sorted(rules),
                        'urgent': out.urgent_signal, 'failure': judged.failure})
        args.output.write_text(json.dumps({'model': port.model, 'results': results}, ensure_ascii=False, indent=2))
        print(f"{case['id']}: {'PASS' if passed else 'FAIL'}", flush=True)
    print(f"{sum(r['passed'] for r in results)}/{len(results)} passed. {args.output}")
    if not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
