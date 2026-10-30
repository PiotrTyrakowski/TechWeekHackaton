import json,time
from pathlib import Path
from collections import defaultdict
import retrieval_memory as m
from evaluate import retrieval_metrics
qs={q['question_id']:q for q in map(json.loads,Path('experiments/offline-sprint/development-questions.jsonl').open())}
gold={g['question_id']:g for g in map(json.loads,Path('data/dev/gold.jsonl').open())}
byh=defaultdict(list)
for q in qs.values(): byh[q['history_id']].append(q)
rows=[]; start=time.perf_counter()
for line in Path('data/dev/histories.jsonl').open():
 h=json.loads(line)
 for q in byh.get(h['history_id'],[]):
  _,_,ranked,scores=m._ranking(q,h,'memory-facts')
  rows.append({'question_id':q['question_id'],'scores':[(h['sessions'][si]['session_id'],scores[si]) for si in ranked[:4]],'gold':gold[q['question_id']]['evidence']})
Path('experiments/memory-r2/development-ranks.json').write_text(json.dumps(rows))
for ratio in [0, .4,.5,.6,.65,.7,.75,.8,.85,.9,.95,1]:
 vals=[]
 for r in rows:
  if not r['gold']: continue
  kept=[sid for sid,sc in r['scores'] if sc>=ratio*r['scores'][0][1]]
  vals.append(retrieval_metrics(kept,r['gold']))
 print(ratio,{key:round(sum(v[key] for v in vals)/len(vals)*100,2) for key in ['recall','precision','evidence_f1','all_hit']},flush=True)
print('runtime_s',time.perf_counter()-start, 'cache',m._cards.cache_info())
