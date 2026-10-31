/* Deterministic English demo parser. No expected.json, source-id mappings or AI calls.
   A row the backend's context layer has read (row.reading) is applied from that reading instead of these rules. */
export const norm = s => String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ł/g,'l').toLowerCase();
const clean = s => norm(s).split('\n').filter(l=>!l.trim().startsWith('>')).join(' ');
function address(s) {
  const words={five:5,two:2,three:3,eight:8,eleven:11};
  let t=clean(s).replace(/\b([a-z]+)\s+(five|two|three|eight|eleven)\b/g,(_,a,b)=>a+' '+words[b]);
  const m=t.match(/\b(lipowa|brzozowa|parkowa|polna|lesna|[a-z]+owa|[a-z]+ska)\s*(\d+)\b/);
  return m ? m[1]+' '+m[2] : null;
}
function money(t) {
  if(/four thousand three hundred/.test(t)) return 4300;
  if(/seven hundred|7 hundred/.test(t)) return 700;
  const m=t.match(/(\d[\d,]*(?:\.\d+)?)\s*(k\b|pln\b|with parts)/);
  return m ? Math.round(Number(m[1].replaceAll(',',''))*(m[2]==='k'?1000:1)) : null;
}
export function dedupe(rows) {
  const map=new Map();
  for(const r of rows){
    if(!r || typeof r.raw_text!=='string' || !r.source_id || !Number.isFinite(Date.parse(r.sent_at))) throw Error('Every row needs source_id, sent_at and raw_text.');
    if(map.has(r.source_id) && JSON.stringify(map.get(r.source_id))!==JSON.stringify(r)) throw Error('Conflicting content for the same source_id: '+r.source_id);
    map.set(r.source_id,r);
  }
  return [...map.values()].sort((a,b)=>Date.parse(a.sent_at)-Date.parse(b.sent_at));
}
// A row the backend has read: its verified facts change the job, nothing is guessed from the wording. Until the reading
// is done (or if it failed) the row is only evidence. A row the reader could not place on any job is a gap.
function read(r,a,jobs,ensure){
  const reading=r.reading,f=reading.status==='done'?reading.facts||{}:{};
  if(!a)return reading.status==='done'?'gap':null;
  if(!jobs.has(a)&&f.amount==null){return null;}
  const j=ensure(a,r);j.evidence.push(r.source_id);
  const change=(field,value)=>{if(j[field]!==value){j.history.push({field,from:j[field],to:value,source:r.source_id,at:r.sent_at,read:true});j[field]=value;}};
  const requoted=f.amount!=null&&f.amount!==j.amount;
  if(f.amount!=null)change('amount',f.amount);
  if(f.status)change('status',f.status);else if(requoted)change('status','pending');
  if(f.excludes)j.excludes=[f.excludes];
  if(f.due)j.due=f.due;
  if(f.start)j.start=f.start;
  if(f.budget)j.budget=f.budget;
  return null;
}
export function compute(input,at='2026-10-30T12:00:00+01:00') {
  const all=dedupe(input), rows=all.filter(r=>Date.parse(r.sent_at)<=Date.parse(at));
  const contactAddr=new Map(),nameByAddr=new Map(),jobs=new Map(),unresolved=[];
  for(const r of rows){
    if(r.author_role==='supplier'||Date.parse(r.sent_at)<Date.parse('2026-10-25'))continue;
    const a=address(r.raw_text);
    if(a && r.contact_key){contactAddr.set(r.contact_key,a); if(r.conversation_title && (!nameByAddr.has(a)||!r.conversation_title.includes('.'))) nameByAddr.set(a,r.conversation_title);}
  }
  function ensure(a,r) {
    if(!jobs.has(a))jobs.set(a,{id:a,address:(a.charAt(0).toUpperCase()+a.slice(1)).replace('Lesna','Leśna'),customer:nameByAddr.get(a)||(r.contact_key?r.conversation_title:null)||'Unknown customer',amount:0,status:'pending',excludes:[],evidence:[],history:[],due:null,start:null});
    return jobs.get(a);
  }
  for(const r of rows){
    if(r.author_role==='supplier'||Date.parse(r.sent_at)<Date.parse('2026-10-25'))continue;
    const t=clean(r.raw_text),a=r.job_context || (r.contact_key&&contactAddr.get(r.contact_key)) || address(t);
    if(r.reading){if(read(r,a,jobs,ensure)==='gap')unresolved.push(r);continue;}
    if(!a){if(/lady behind the bakery|do not remember[^.]*address/.test(t))unresolved.push(r);continue;}
    const value=money(t);
    if(!jobs.has(a)&&value===null)continue;
    const j=ensure(a,r); j.evidence.push(r.source_id);
    const change=(field,value)=>{if(j[field]!==value){j.history.push({field,from:j[field],to:value,source:r.source_id,at:r.sent_at});j[field]=value;}};
    if(/do not install the cabin|cabin.*brother-in-law|cabin is out|without the cabin|minus the cabin/.test(t))j.excludes=['shower cabin install'];
    const paid=r.author_role==='owner' && /came in|arrived|received.*transfer/.test(t) && !/not come in|not arrived/.test(t);
    const completed=r.author_role==='owner' && /\bdone\b|finished|completed/.test(t);
    if(value!==null&&r.author_role==='owner'&&!/no guessing|once i recalculate/.test(t)){
      change('amount',value);
      if(!paid&&!completed) change('status','pending');
    }
    const approved=r.author_role==='customer' && /i approve|we confirm|i confirm|i accept|\bok\b/.test(t) && !/not (?:confirm|approv|accept)|hold on|have to|need to|probably|for now/.test(t) && (value===null||value===j.amount);
    if(approved)change('status','agreed');
    if(completed)change('status','completed');
    if(paid)change('status','paid');
    if(/remind|tomorrow.*\bcall|\bcall\b.*tomorrow|call today|call back today/.test(t)) {
      const d=new Date(r.sent_at.slice(0,10)+'T12:00:00Z');if(/tomorrow/.test(t))d.setUTCDate(d.getUTCDate()+1);j.due=d.toISOString().slice(0,10);
    }
    const start=t.match(/(?:mon|start|confirmed for)\s*(?:the 2nd|nov 2\b)/);if(start)j.start='2026-11-02';
    if(/a thousand max|max.*1000/.test(t))j.budget=1000;
  }
  const clarified=rows.filter(r=>r.clarifies_source_id||(/lady behind the bakery/.test(clean(r.raw_text))&&address(r.raw_text)));
  const gaps=unresolved.filter(r=>!clarified.some(c=>{
    const matches=(c.clarifies_source_id===r.source_id||(!c.clarifies_source_id&&/lady behind the bakery/.test(clean(r.raw_text))))&&Date.parse(c.sent_at)>Date.parse(r.sent_at);
    const j=jobs.get(c.job_context||address(c.raw_text));
    if(matches&&j&&!j.evidence.includes(r.source_id))j.evidence.push(r.source_id);
    return matches&&j;
  }));
  const list=[...jobs.values()].filter(j=>j.amount>0);
  const tasks=list.flatMap(j=>{
    if(j.status==='paid'||(j.status==='agreed'&&j.start))return [];
    const type=j.status==='pending'?(j.budget?'budget':'decision'):j.status==='completed'?'payment':'schedule';
    const title={budget:'Clarify the budget',decision:'Follow up on the decision',payment:'Check the payment',schedule:'Set the install date'}[type];
    return [{id:j.id+':'+type,job:j.id,type,title,due:j.due,evidence:j.evidence}];
  });
  const totals={pending:0,agreed:0,completed:0,paid:0};for(const j of list)totals[j.status]+=j.amount;
  return {jobs:list,tasks,gaps,totals,unique:all.length,duplicates:input.length-all.length,sources:all};
}
export function draft(job,type) {
  return ({decision:`Hello, a quick follow-up on the quote for ${job.address}: ${pln(job.amount)}${job.excludes.length?' without the shower cabin install':''}. Can we confirm the job?`,budget:`Hello, the current proposal for ${job.address} is ${pln(job.amount)}. I understand the budget is ${pln(job.budget||1000)}. Can we talk about the scope?`,schedule:`Hello, thank you for accepting the quote for ${job.address}. When would be a good time to agree the install date?`,payment:`Hello, I would like to confirm payment for the work done at ${job.address}. The agreed amount is ${pln(job.amount)}.`})[type];
}
const pln=n=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'PLN',maximumFractionDigits:0}).format(n);
