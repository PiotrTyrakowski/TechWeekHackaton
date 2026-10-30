"""Development-only packing audit; gold is used by diagnostics, never retrieval."""
import json,time
from pathlib import Path
from collections import defaultdict
import retrieval_memory as m
from official.score import normalize
qs={x['question_id']:x for x in map(json.loads,open('experiments/offline-sprint/development-questions.jsonl'))}
gs={x['question_id']:x for x in map(json.loads,open('data/dev/gold.jsonl'))}
byh=defaultdict(list)
for q in qs.values():byh[q['history_id']].append(q)
source_n=packed_n=answerable_n=0
index_s=query_s=0;card_n=0;h_n=0
for line in open('data/dev/histories.jsonl'):
 h=json.loads(line)
 if h['history_id'] not in byh:continue
 tick=time.perf_counter();index=m._index(h);index_s+=time.perf_counter()-tick;card_n+=len(index[0]);h_n+=1
 for q in byh[h['history_id']]:
  tick=time.perf_counter();rows=m.retrieve(q,h,method='memory-facts');query_s+=time.perf_counter()-tick
  g=gs[q['question_id']]
  if g['abstain']:continue
  answerable_n+=1
  aliases=[normalize(x) for x in [g['answer']]+g['aliases'] if x]
  ids={r['id'] for r in rows}
  full=normalize('\n'.join(t['content'] for s in h['sessions'] if s['session_id'] in ids for t in s['turns']))
  packed=normalize('\n'.join(r['text'] for r in rows))
  source_n+=any(a in full for a in aliases)
  packed_n+=any(a in packed for a in aliases)
result={'partition':'development','answerable_n':answerable_n,'exact_normalized_answer_or_alias_in_selected_full_sessions_n':source_n,'exact_normalized_answer_or_alias_in_packed_cards_n':packed_n,'retention_conditional_on_answer_in_selected_session':packed_n/source_n,'history_preprocessing_s':index_s,'history_n':h_n,'sentence_card_n':card_n,'warm_query_s':query_s,'query_n':len(qs),'notes':'Literal answer-span retention only, not answer accuracy; computed on development only. Includes unsupported answers that coincidentally occur in other selected sessions. Final packing preserves original whitespace between merged snippets.'}
Path('experiments/memory-r2/packing-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
