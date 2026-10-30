"""Paired, deterministic offline evidence retrieval comparison. No model APIs."""
import argparse, hashlib, json, os, sys, time
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate
import retrieval
import retrieval_dense

p=argparse.ArgumentParser();p.add_argument('--sample',type=int,default=24);p.add_argument('--out',default='experiments/dense-pilot');args=p.parse_args()
qs=list(evaluate.jsonl('data/dev/questions.jsonl'))
if args.sample:
 qs=sorted((q for q in qs if evaluate.partition(q['question_id'])=='development'),key=lambda q: hashlib.sha256(q['question_id'].encode()).hexdigest())[:args.sample]
qids={q['question_id'] for q in qs};gold={g['question_id']:g for g in evaluate.jsonl('data/dev/gold.jsonl') if g['question_id'] in qids}
grouped=defaultdict(list)
for q in qs: grouped[q['history_id']].append(q)
configs=[dict(method=m,k=k,budget=12000) for m in ('bm25','dense','dense-hybrid') for k in (4,8)]
rows=[[] for _ in configs];out=Path(args.out);out.mkdir(parents=True,exist_ok=True);started=time.monotonic();n=0
for h in evaluate.jsonl('data/dev/histories.jsonl'):
 for q in grouped.pop(h['history_id'],[]):
  g=gold[q['question_id']];dates={s['session_id']:s['date'] for s in h['sessions']}
  for config,records in zip(configs,rows):
   tick=time.monotonic();fn=retrieval.retrieve if config['method']=='bm25' else retrieval_dense.retrieve
   passages=fn(q,h,**config);latency=(time.monotonic()-tick)*1000
   assert all(p['id'] in dates and p['date']==dates[p['id']] for p in passages)
   ids=list(dict.fromkeys(p['id'] for p in passages))
   records.append(dict(question_id=q['question_id'],history_id=q['history_id'],partition=evaluate.partition(q['question_id']),gold_abstain=g['abstain'],retrieved_sessions=ids,gold_sessions=g['evidence'],latency_ms=latency,packed_chars=sum(len(p['text']) for p in passages),unique_sessions=len(ids),**evaluate.retrieval_metrics(ids,g['evidence'])))
  n+=1
  if n%8==0: print(json.dumps(dict(done=n,total=len(qs),elapsed_s=round(time.monotonic()-started,1))),flush=True)
assert not grouped
reports=[]
for c,rs in zip(configs,rows):
 report=dict(config=c,metrics=evaluate.summarize(rs),by_partition={part:evaluate.summarize([r for r in rs if r['partition']==part]) for part in ('development','validation')})
 reports.append(report)
 with (out/f"{c['method']}-k{c['k']}-details.jsonl").open('w') as f:
  for r in rs:f.write(json.dumps(r)+'\n')
summary=dict(scope_n=len(qs),sample_selection='sha256(question_id) ascending, development only' if args.sample else 'all526 with fixed sha256 modulo5 split',reports=reports,runtime_s=time.monotonic()-started,model_id=retrieval_dense.MODEL_ID,model_revision=retrieval_dense.MODEL_REVISION,candidate_limit=int(os.environ.get('DENSE_CANDIDATE_LIMIT','16')),encoding='raw turn content/query; no prefixes; max256 tokens; masked mean pooling; L2 normalization; quantized ONNX CPU',rrf_constant=60,rrf_weights=[1,1],threads=int(os.environ.get("DENSE_THREADS","2")),batch_size=16,reactor_call_count=0,source_sha256={p:evaluate.digest(p) for p in ['retrieval_dense.py','retrieval.py','experiments/dense-run.py','experiments/dense-model/model_quantized.onnx','experiments/dense-model/tokenizer.json','data/dev/questions.jsonl','data/dev/histories.jsonl','data/dev/gold.jsonl']},git=evaluate.revision(),limitation='Session evidence proxy only. Not answer accuracy or actual Reactor citation F1. Cold model/document embedding cost attributed to dense-k4; subsequent dense variants use cache.')
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
