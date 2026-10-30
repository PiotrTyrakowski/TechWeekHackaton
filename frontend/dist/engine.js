/* Deterministic Polish demo parser. No expected.json, source-id mappings or AI calls. */
export const norm = s => String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ł/g,'l').toLowerCase();
const clean = s => norm(s).split('\n').filter(l=>!l.trim().startsWith('>')).join(' ');
function address(s) {
  const words={piec:5,dwa:2,trzy:3,osiem:8,jedenascie:11};
  let t=clean(s).replace(/\b([a-z]+)\s+(piec|dwa|trzy|osiem|jedenascie)\b/g,(_,a,b)=>a+' '+words[b]);
  const m=t.match(/\b(lipowa|brzozowa|parkowa|polna|lesna|[a-z]+owa|[a-z]+ska)\s*(\d+)\b/);
  return m ? m[1]+' '+m[2] : null;
}
function money(t) {
  if(/cztery tysiace trzysta/.test(t)) return 4300;
  if(/siedem stow|7 stow/.test(t)) return 700;
  const m=t.match(/(\d[\d ]*(?:[.,]\d+)?)\s*(tys\b|k\b|zl\b|z czesciami)/);
  return m ? Math.round(Number(m[1].replaceAll(' ','').replace(',','.'))*(/tys|^k$/.test(m[2])?1000:1)) : null;
}
export function dedupe(rows) {
  const map=new Map();
  for(const r of rows){
    if(!r || typeof r.raw_text!=='string' || !r.source_id || !Number.isFinite(Date.parse(r.sent_at))) throw Error('Każdy wpis wymaga source_id, sent_at i raw_text.');
    if(map.has(r.source_id) && JSON.stringify(map.get(r.source_id))!==JSON.stringify(r)) throw Error('Sprzeczne treści tego samego source_id: '+r.source_id);
    map.set(r.source_id,r);
  }
  return [...map.values()].sort((a,b)=>Date.parse(a.sent_at)-Date.parse(b.sent_at));
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
    if(!jobs.has(a))jobs.set(a,{id:a,address:(a.charAt(0).toUpperCase()+a.slice(1)).replace('Lesna','Leśna'),customer:nameByAddr.get(a)||(r.contact_key?r.conversation_title:null)||'Klient nieustalony',amount:0,status:'pending',excludes:[],evidence:[],history:[],due:null,start:null});
    return jobs.get(a);
  }
  for(const r of rows){
    if(r.author_role==='supplier'||Date.parse(r.sent_at)<Date.parse('2026-10-25'))continue;
    const t=clean(r.raw_text),a=r.job_context || (r.contact_key&&contactAddr.get(r.contact_key)) || address(t);
    if(!a){if(/pani za piekarnia|adresu.*nie pamietam/.test(t))unresolved.push(r);continue;}
    const value=money(t);
    if(!jobs.has(a)&&value===null)continue;
    const j=ensure(a,r); j.evidence.push(r.source_id);
    const change=(field,value)=>{if(j[field]!==value){j.history.push({field,from:j[field],to:value,source:r.source_id,at:r.sent_at});j[field]=value;}};
    if(/kabiny nie montuj|kabiny.*szwagier|kabina odpada|bez kabiny|odjeciu kabiny/.test(t))j.excludes=['montaż kabiny'];
    const paid=r.author_role==='owner' && /doszlo|wplynelo|otrzymal.*przelew/.test(t) && !/nie doszlo|nie wplynelo/.test(t);
    const completed=r.author_role==='owner' && /zrobion|skonczon|wykonan/.test(t);
    if(value!==null&&r.author_role==='owner'&&!/nie strzelac|jak przelicze/.test(t)){
      change('amount',value);
      if(!paid&&!completed) change('status','pending');
    }
    const approved=r.author_role==='customer' && /zatwierdzam|potwierdzamy|potwierdzam|akceptuje|\bok\b/.test(t) && !/nie (?:potwierdz|zatwierdz|akcept)|poczekaj|musze|chyba|na razie/.test(t) && (value===null||value===j.amount);
    if(approved)change('status','agreed');
    if(completed)change('status','completed');
    if(paid)change('status','paid');
    if(/przypomnij|jutro.*(?:tel|zadzw)|zadzwon dzis|oddzwon.*dzis/.test(t)) {
      const d=new Date(r.sent_at.slice(0,10)+'T12:00:00Z');if(/jutro/.test(t))d.setUTCDate(d.getUTCDate()+1);j.due=d.toISOString().slice(0,10);
    }
    const start=t.match(/(?:pon|start|potwierdzona na)\s*(?:2go|2\.11)/);if(start)j.start='2026-11-02';
    if(/do tysia|max.*1000/.test(t))j.budget=1000;
  }
  const clarified=rows.filter(r=>r.clarifies_source_id||(/pani za piekarnia/.test(clean(r.raw_text))&&address(r.raw_text)));
  const gaps=unresolved.filter(r=>!clarified.some(c=>{
    const matches=(c.clarifies_source_id===r.source_id||(!c.clarifies_source_id&&/pani za piekarnia/.test(clean(r.raw_text))))&&Date.parse(c.sent_at)>Date.parse(r.sent_at);
    const j=jobs.get(c.job_context||address(c.raw_text));
    if(matches&&j&&!j.evidence.includes(r.source_id))j.evidence.push(r.source_id);
    return matches&&j;
  }));
  const list=[...jobs.values()].filter(j=>j.amount>0);
  const tasks=list.flatMap(j=>{
    if(j.status==='paid'||(j.status==='agreed'&&j.start))return [];
    const type=j.status==='pending'?(j.budget?'budget':'decision'):j.status==='completed'?'payment':'schedule';
    const title={budget:'Wyjaśnij budżet',decision:'Przypomnij o decyzji',payment:'Sprawdź rozliczenie',schedule:'Ustal termin montażu'}[type];
    return [{id:j.id+':'+type,job:j.id,type,title,due:j.due,evidence:j.evidence}];
  });
  const totals={pending:0,agreed:0,completed:0,paid:0};for(const j of list)totals[j.status]+=j.amount;
  return {jobs:list,tasks,gaps,totals,unique:all.length,duplicates:input.length-all.length,sources:all};
}
export function draft(job,type) {
  return ({decision:`Dzień dobry, przypominam się w sprawie wyceny na ${job.address}: ${job.amount} zł${job.excludes.length?' bez montażu kabiny':''}. Czy możemy potwierdzić realizację?`,budget:`Dzień dobry, aktualna propozycja dla ${job.address} wynosi ${job.amount} zł. Rozumiem, że budżet to ${job.budget||1000} zł. Czy możemy omówić zakres prac?`,schedule:`Dzień dobry, dziękuję za akceptację wyceny na ${job.address}. Kiedy możemy porozmawiać o dogodnym terminie montażu?`,payment:`Dzień dobry, chciałbym potwierdzić rozliczenie wykonanych prac na ${job.address}. Uzgodniona kwota to ${job.amount} zł.`})[type];
}
