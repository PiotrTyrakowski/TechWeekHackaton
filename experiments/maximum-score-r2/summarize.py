"""Rebuild the round-two offline leaderboard and paired uncertainty; no APIs."""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluate import jsonl, partition


def one(pattern):
    paths = sorted(ROOT.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f'Expected exactly one artifact for {pattern}, found {len(paths)}')
    return paths[0]


def paired(a, b, ids):
    delta = [a[q]['evidence_f1'] - b[q]['evidence_f1'] for q in ids]
    rng = random.Random(20261030)
    samples = sorted(sum(rng.choice(delta) for _ in delta) / len(delta) for _ in range(2000))
    return {'answerable_n': len(delta), 'mean_delta': sum(delta)/len(delta),
            'wins': sum(d > 1e-12 for d in delta), 'losses': sum(d < -1e-12 for d in delta),
            'paired_question_bootstrap95': [samples[49], samples[1949]],
            'note': 'Exploratory paired question bootstrap; does not adjust for repeated validation use or history clustering.'}


def main():
    rows = []
    specs = [
        ('dev', 'BM25-4', 'experiments/offline-sprint/unified/*/0-bm25-k4-summary.json'),
        ('dev', 'dense-hybrid-4', 'experiments/dense-full16/summary.json'),
        ('dev', 'calibrated-4', 'experiments/calibration-r2/final/*/*summary.json'),
        ('dev-large', 'BM25-4', 'experiments/maximum-score-r2/dev-large-baseline/*/0-bm25-k4-summary.json'),
        ('dev-large', 'BM25-8', 'experiments/maximum-score-r2/dev-large-baseline/*/1-bm25-k8-summary.json'),
        ('dev-large', 'calibrated-4', 'experiments/maximum-score-r2/dev-large-calibrated-full/*/*summary.json'),
        ('dev-large', 'dense-hybrid-4 validation only', 'experiments/maximum-score-r2/dev-large-dense-validation/*/*summary.json'),
    ]
    for dataset, name, pattern in specs:
        path = one(pattern)
        r = json.load(path.open())
        if name == 'dense-hybrid-4':
            r = next(x for x in r['reports'] if x['config']['method'] == 'dense-hybrid' and x['config']['k'] == 4)
        metrics = r.get('retrieval_metrics', r.get('metrics'))
        rows.append({'dataset': dataset, 'name': name, 'metrics': metrics,
                     'validation': r['by_partition']['validation'],
                     'artifact': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'training_note': 'Calibrated used433 dev question IDs for fitting; full526 includes these training IDs. Dev-large reuses the same questions.' if 'calibrated' in name else 'No challenge-gold relevance fitting.'})
    a_path = one('experiments/maximum-score-r2/dev-large-calibrated-validation/*/*details.jsonl')
    b_path = one('experiments/maximum-score-r2/dev-large-dense-validation/*/*details.jsonl')
    a = {r['question_id']: r for r in jsonl(a_path)}
    b = {r['question_id']: r for r in jsonl(b_path)}
    assert set(a) == set(b)
    ids = [q for q in a if a[q]['evidence_f1'] is not None]
    training_histories = {q['history_id'] for q in jsonl(ROOT / 'data/dev/questions.jsonl') if partition(q['question_id']) == 'development'}
    unseen = [q for q in ids if a[q]['history_id'] not in training_histories]
    result = {'reactor_calls_this_round': 0, 'leaderboard': rows,
              'dev_large_validation_calibrated_minus_dense': paired(a, b, ids),
              'dev_large_unseen_history_calibrated_minus_dense': paired(a, b, unseen),
              'live_total_unchanged': {'completed_unique_questions': 1, 'exact_gold_matches': 1,
                                     'unjudged': 0, 'evidence_f1': 0, 'unanswerable_cases_tested': 0,
                                     'benchmark_requests': 19, 'reset_requests': 5,
                                     'question_request_attempts': 14, 'unsuccessful_question_attempts': 13},
              'limits': 'Retrieval-set evidence metrics are not Reactor answer accuracy or actual citation F1. Validation is reused exploratory data, dev-large is not independent, and there is no complete citation-validated live configuration.'}
    output = Path(__file__).with_name('leaderboard.json')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'rows': len(rows), 'paired': result['dev_large_validation_calibrated_minus_dense'],
                      'unseen': result['dev_large_unseen_history_calibrated_minus_dense']}, indent=2))


if __name__ == '__main__':
    main()
