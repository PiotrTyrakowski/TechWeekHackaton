import json,re
from evaluate import retrieval_metrics
rs=json.load(open('experiments/memory-r2/development-ranks.json')); qs={x['question_id']:x['question'] for x in map(json.loads,open('experiments/offline-sprint/development-questions.jsonl'))}
pattern=r'\b(how many|how much|how long|how old|how often|total|average|combined|between|compared|than|percentage|order|earliest|before|after|both|initially|initial|previous|currently|current|now|since|first|last|ago|weeks|months|years)\b'
results=[]
for low in [.4,.45,.5,.55,.6,.65]:
 for high in [.7,.75,.8,.85,.9,.95,1]:
  vals=[];counts=[]
  for r in rs:
   if not r['gold']:continue
   ratio=low if re.search(pattern,qs[r['question_id']],re.I) else high
   keep=[sid for sid,sc in r['scores'] if sc>=ratio*r['scores'][0][1]]
   vals.append(retrieval_metrics(keep,r['gold']));counts.append(len(keep))
  results.append({'low':low,'high':high,**{key:sum(v[key] for v in vals)/len(vals)*100 for key in ['recall','precision','evidence_f1','all_hit']},'unique_sessions':sum(counts)/len(counts)})
results.sort(key=lambda x:-x['evidence_f1'])
print(json.dumps(results[:8],indent=2))
open('experiments/memory-r2/policy-calibration.json','w').write(json.dumps({'pattern':pattern,'results':results},indent=2))
