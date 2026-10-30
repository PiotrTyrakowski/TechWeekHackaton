"""Append fixed full-comparison tables to the research note; no tuning."""
import json
from pathlib import Path

folder=Path('experiments/dense-full16')
s=json.loads((folder/'summary.json').read_text())
lines=[f"Full run finished in **{s['runtime_s']:.2f} seconds** with four CPU threads and zero Reactor calls. Summary: `experiments/dense-full16/summary.json`; paired details are adjacent JSONL files.", '', '| Split | Method | k | Recall % | Precision % | Session F1 % | All-hit % |', '|---|---|---:|---:|---:|---:|---:|']
for split in ('all','development','validation'):
 for report in s['reports']:
  c=report['config'];m=report['metrics'] if split=='all' else report['by_partition'][split]
  lines.append('| '+ ' | '.join([split,c['method'],str(c['k'])]+[f'{m[key]*100:.2f}' for key in ('recall','precision','evidence_f1','all_hit')])+' |')
lines += ['', '| Method | k | Mean chars | Mean unique sessions | Mean latency ms | P95 latency ms |', '|---|---:|---:|---:|---:|---:|']
for report in s['reports']:
 c=report['config'];m=report['metrics'];lines.append('| '+' | '.join([c['method'],str(c['k'])]+[f'{m[key]:.2f}' for key in ('packed_chars','unique_sessions','latency_ms','latency_p95_ms')])+' |')
lines += ['', 'Latency rows are ordered: BM25-k4, BM25-k8, dense-k4, dense-k8, hybrid-k4, hybrid-k8. Thus the first dense pass includes model/document encoding and subsequent variants are warm-cache timings. These are not six independent cold-run performance measurements.', '', '| Split | Comparison | Paired F1 wins | Losses | Ties | Mean delta pp |', '|---|---|---:|---:|---:|---:|']
for split in ('development','validation'):
 for method in ('dense','dense-hybrid'):
  for k in (4,8):
   def load(m):return {r['question_id']:r for r in map(json.loads,(folder/f'{m}-k{k}-details.jsonl').read_text().splitlines()) if r['partition']==split and not r['gold_abstain']}
   baseline=load('bm25');candidate=load(method);deltas=[candidate[q]['evidence_f1']-r['evidence_f1'] for q,r in baseline.items()]
   lines.append(f'| {split} | {method}-k{k} vs BM25-k{k} | {sum(d>1e-9 for d in deltas)} | {sum(d< -1e-9 for d in deltas)} | {sum(abs(d)<=1e-9 for d in deltas)} | {sum(deltas)/len(deltas)*100:+.2f} |')
p=Path('reports/dense-offline.md');text=p.read_text();text=text.replace('Pending the bounded full paired run. No recommendation is based on validation results until the fixed run completes.','\n'.join(lines));p.write_text(text)
