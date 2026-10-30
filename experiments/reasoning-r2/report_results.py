"""Summarize the fixed two-candidate experiment; does not run retrieval."""
from pathlib import Path
import json
from evaluate import summarize

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'experiments/reasoning-r2'

def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]

def groups(rows):
    return {
        'all': summarize(rows),
        'by_partition': {p: summarize([r for r in rows if r['partition'] == p]) for p in ('development', 'validation')},
        'by_type': {t: summarize([r for r in rows if r['question_type'] == t]) for t in sorted({r['question_type'] for r in rows})},
    }

def paired(rows, baseline):
    lookup = {r['question_id']: r for r in baseline}
    result = {}
    for scope in ('all', 'development', 'validation'):
        subset = [r for r in rows if not r['gold_abstain'] and (scope == 'all' or r['partition'] == scope)]
        result[scope] = {'answerable_n': len(subset)}
        for key in ('recall', 'precision', 'evidence_f1', 'all_hit'):
            differences = [r[key] - lookup[r['question_id']][key] for r in subset]
            result[scope][key] = {'wins': sum(d > 1e-12 for d in differences), 'losses': sum(d < -1e-12 for d in differences), 'ties': sum(abs(d) <= 1e-12 for d in differences)}
    return result

gold = {r['question_id']: r for r in read(ROOT / 'data/dev/gold.jsonl')}
final_path = next((BASE / 'final').glob('*/*details.jsonl'))
rows = read(final_path)
results = {'selection': 'Two bounded candidates evaluated on development only; conservative selected by higher development F1; selected candidate full evaluation includes the first and only validation evaluation.', 'scope': {'questions': 526, 'answerable': 496, 'development': 433, 'validation': 93}, 'selected': groups(rows), 'baselines': {}, 'paired': {}, 'reactor_call_count': 0, 'answer_metrics': None}
for name in ('bm25-k4', 'dense-hybrid-k4'):
    baseline = read(ROOT / f'experiments/dense-full16/{name}-details.jsonl')
    for row in baseline:
        row['question_type'] = gold[row['question_id']]['question_type']
    results['baselines'][name] = groups(baseline)
    results['paired'][name] = paired(rows, baseline)
(BASE / 'comparison.json').write_text(json.dumps(results, indent=2) + '\n')

def fmt(m):
    return ' | '.join([str(m['n']), str(m['answerable_n'])] + [f"{m[key]*100:.2f}" for key in ('recall','precision','evidence_f1','all_hit')])

lines = ['# Complementary reasoning R2', '', 'Do not promote: both question-derived candidates improve fixed-k evidence coverage, but lose too much citation precision. No runtime files were changed. The selected conservative candidate returns at most four sessions and adds at most one distinct session beyond the BM25 top-four-turn session set.', '', 'The two tested candidates preserve the original BM25 sessions, derive up to four event anchors by splitting explicit question clauses, and greedily add sessions using query-term novelty, anchor coverage and redundancy. The broader candidate fills all four session slots; the conservative candidate adds one. They use only the question text and supplied history, with no question-type/gold routing, model, network, event invention, or date arithmetic.', '', '## Selection and scope', '', 'Both candidates were evaluated on development (433 questions / 408 answerable). Conservative was selected by development evidence F1: **71.40%** versus broader **67.84%**. Its full evaluation then included validation exactly once. No test data was accessed. Baselines are the existing full526 dense-full16 artifacts; their latency was recorded in separate runs.', '', 'Evidence F1 is a retrieval proxy that treats every retrieved session as cited. It is not Reactor answer accuracy. No supported-case exact-answer diagnostic was attempted, and no Reactor calls/resets/paid models were used.', '', '| Method/scope | N | Answerable | Recall % | Precision % | F1 proxy % | All gold % |', '|---|---:|---:|---:|---:|---:|---:|']
for name, data in [('BM25 k4',results['baselines']['bm25-k4']),('Dense hybrid k4',results['baselines']['dense-hybrid-k4']),('Complementary conservative k4',results['selected'])]:
    for scope in ('all','development','validation'):
        lines.append(f"| {name}, {scope} | {fmt(data['all'] if scope == 'all' else data['by_partition'][scope])} |")
lines += ['', '## Full526 category metrics', '', '| Method/category | N | Answerable | Recall % | Precision % | F1 proxy % | All gold % |', '|---|---:|---:|---:|---:|---:|---:|']
for name, data in [('BM25 k4',results['baselines']['bm25-k4']),('Dense hybrid k4',results['baselines']['dense-hybrid-k4']),('Complementary conservative k4',results['selected'])]:
    for category, metric in data['by_type'].items():
        lines.append(f'| {name}, {category} | {fmt(metric)} |')
m=results['selected']['all']
lines += ['', '## Size, latency and paired changes', '', f"Selected candidate: mean {m['latency_ms']:.2f} ms, p95 {m['latency_p95_ms']:.2f} ms; mean {m['packed_chars']:.0f} packed characters and {m['unique_sessions']:.2f} unique sessions. Budget remains 12,000 text characters; k remains four. Two strongest turns plus fitting neighbors are packed per session with source IDs, source dates and explicit roles.", '', '| Baseline, answerable scope | Recall win/loss/tie | F1 win/loss/tie | All-gold win/loss/tie |', '|---|---:|---:|---:|']
for name, data in results['paired'].items():
    for scope, metric in data.items():
        def triple(key):
            x=metric[key]; return f"{x['wins']}/{x['losses']}/{x['ties']}"
        lines.append(f"| {name}, {scope} ({metric['answerable_n']}) | {triple('recall')} | {triple('evidence_f1')} | {triple('all_hit')} |")
lines += ['', 'The coverage gain is not merely higher k: duplicate turn slots are converted to complementary source sessions while the cap stays four. However, count/order wording also occurs in single-session questions. Those questions gain unnecessary sessions, while aggregate questions can still require more than four sources. The experiment does not meet the precision-preservation objective, so the existing dense/BM25 pipeline should remain selected.', '', 'Validation: six dependency-free unit tests passed, covering complementary anchors, strict history-local IDs and dates, text budgets including tiny budgets, explicit roles at normal budgets, input immutability, no cross-history cache contamination, gold/type independence, and invalid/empty inputs.', '', 'Artifacts: `experiments/reasoning-r2/comparison.json` contains all full/split/category metrics and paired win/loss counts; `development/` contains both development candidates; `final/` contains the one selected full evaluation. `report_results.py` only summarizes completed artifacts.']
(ROOT/'reports/reasoning-r2.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines[:26]))
