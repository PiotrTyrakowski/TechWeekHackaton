"""Collate the fixed paired offline runs; never calls Reactor or a model."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluate import jsonl, partition, retrieval_metrics, summarize


def main():
    gold = {g['question_id']: g for g in jsonl(ROOT / 'data/dev/gold.jsonl')}
    unified = sorted((ROOT / 'experiments/offline-sprint/unified').glob('*/0-bm25-k4-details.jsonl'))[-1].parent
    specs = [
        ('BM25-4', unified / '0-bm25-k4-details.jsonl'),
        ('BM25-8', unified / '1-bm25-k8-details.jsonl'),
        ('Adaptive-4', unified / '2-adaptive-k4-details.jsonl'),
        ('Adaptive-8', unified / '3-adaptive-k8-details.jsonl'),
        ('Dense-hybrid-4', ROOT / 'experiments/dense-full16/dense-hybrid-k4-details.jsonl'),
        ('Dense-hybrid-8', ROOT / 'experiments/dense-full16/dense-hybrid-k8-details.jsonl'),
        ('Dense-4', ROOT / 'experiments/dense-full16/dense-k4-details.jsonl'),
        ('Dense-8', ROOT / 'experiments/dense-full16/dense-k8-details.jsonl'),
        ('Rejected-rerank-4', ROOT / 'experiments/rerank-offline/rerank-k4-details.jsonl'),
    ]
    reports = []
    baseline = None
    for name, path in specs:
        raw = list(jsonl(path))
        assert len(raw) == len(gold) and {r['question_id'] for r in raw} == set(gold), path
        rows = []
        for r in raw:
            g = gold[r['question_id']]
            assert set(r['gold_sessions']) == set(g['evidence']), path
            assert r['partition'] == partition(r['question_id']), path
            rows.append({**r, 'gold_abstain': g['abstain'], 'question_type': g['question_type'],
                         **retrieval_metrics(r['retrieved_sessions'], g['evidence'])})
        if baseline is None:
            baseline = {r['question_id']: r for r in rows}
        report = {'name': name, 'metrics': summarize(rows),
                  'validation': summarize([r for r in rows if r['partition'] == 'validation']),
                  'development': summarize([r for r in rows if r['partition'] == 'development']),
                  'by_type': {t: summarize([r for r in rows if r['question_type'] == t])
                              for t in sorted({r['question_type'] for r in rows})},
                  'artifact': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        report['paired_vs_bm25_4'] = {}
        for metric in ['recall', 'evidence_f1', 'all_hit']:
            deltas = [r[metric] - baseline[r['question_id']][metric] for r in rows if r[metric] is not None]
            report['paired_vs_bm25_4'][metric] = {
                'wins': sum(d > 1e-12 for d in deltas), 'losses': sum(d < -1e-12 for d in deltas),
                'ties': sum(abs(d) <= 1e-12 for d in deltas), 'mean_delta': sum(deltas) / len(deltas)}
        reports.append(report)
    result = {'scope_n': len(gold), 'answerable_n': sum(not g['abstain'] for g in gold.values()),
              'reactor_calls': 0, 'reports': reports,
              'note': 'Session retrieval proxies, not answer accuracy or Reactor-selected citation F1. Validation is a reused development partition, not an untouched final holdout. Dense warm timings exclude initial embeddings.'}
    out = Path(__file__).with_name('comparison.json')
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'out': str(out), 'scope_n': result['scope_n'], 'configs': len(reports), 'reactor_calls': 0}))


if __name__ == '__main__':
    main()
