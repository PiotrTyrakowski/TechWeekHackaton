// The link to the context layer (backend/server.py): inputs go to POST /notes with the jobs as the engine sees them,
// readings come back through a long-poll on /state. Without the backend (opened as plain files, or hosted as a static
// site) everything here stays quiet and the app runs on its rules alone.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pln=n=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'PLN',maximumFractionDigits:0}).format(n);
const STATUS={pending:'awaiting decision',agreed:'agreed',completed:'done · not paid',paid:'paid'};
const FACT={amount:'Price',status:'Status',due:'Contact by',start:'Starts',excludes:'Out of scope',budget:'Budget'};
const KIND={'work order':'Work order',schedule:'Schedule','order parts':'Order parts','follow-up':'Follow-up'};

async function api(path,body){
 const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const data=await r.json().catch(()=>({}));
 if(!r.ok)throw Error(data.error||'The context layer answered '+r.status);
 return data;
}

export async function health(){try{return await api('/health');}catch{return null;}}

// Keeps calling onRows with every input the backend holds; returns a function that stops it.
export function follow(onRows){
 let stop=false,version=null;
 (async()=>{while(!stop){try{const st=await api(version==null?'/state':`/state?since=${version}&wait=25`);if(st.version!==version){version=st.version;onRows(st.rows);}}catch{await new Promise(r=>setTimeout(r,5000));}}})();
 return()=>{stop=true;};
}

// The jobs and earlier messages the reader gets: the picked job's own messages, else the newest ones.
export function context(model,job){
 const jobs=model.jobs.map(j=>({id:j.id,address:j.address,customer:j.customer,amount:j.amount,status:j.status,excludes:j.excludes,due:j.due||undefined,start:j.start||undefined,budget:j.budget||undefined}));
 const ids=job?model.jobs.find(j=>j.id===job)?.evidence||[]:model.sources.slice(-12).map(r=>r.source_id);
 const passages=ids.map(id=>model.sources.find(r=>r.source_id===id)).filter(Boolean).sort((a,b)=>Date.parse(a.sent_at)-Date.parse(b.sent_at)).slice(-12)
  .map(r=>({id:r.source_id,date:r.sent_at.slice(0,10),text:`[${r.channel.replace('_',' ')}, ${r.author_role}] ${r.raw_text}`}));
 return {jobs,passages};
}

export const send=(text,model,{date,job,author_role='owner',channel='note',clarifies}={})=>
 api('/notes',{text,date,job:job||undefined,author_role,channel,clarifies:clarifies||undefined,...context(model,job)});
export const decide=(id,decision)=>api('/actions/'+encodeURIComponent(id),{decision});
export const reset=()=>api('/reset',{}).catch(()=>null);
export const speak=text=>fetch('/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});

// The input's words with the reader's quotes marked, so every fact points at where it was said.
export function marked(row){
 const text=row.raw_text,low=text.toLowerCase(),spans=[];
 for(const [key,phrase] of Object.entries(row.reading?.quotes||{})){const at=low.indexOf(phrase.toLowerCase());if(at>=0)spans.push([at,at+phrase.length,key]);}
 spans.sort((a,b)=>a[0]-b[0]||b[1]-a[1]);let out='',pos=0;
 for(const [a,b,key] of spans){if(a<pos)continue;out+=esc(text.slice(pos,a))+`<mark title="${esc(FACT[key])}">${esc(text.slice(a,b))}</mark>`;pos=b;}
 return out+esc(text.slice(pos));
}

export function factText(key,v){return key==='amount'||key==='budget'?pln(v):key==='status'?STATUS[v]||v:String(v);}

function readerName(h){if(!h)return null;const m=h.model||'';return h.reader==='reactor'?'Reactor':m?m.split('/').pop().replace(/-\d{4}$/,''):'Model';}

export function sidebar(h){
 const dot=document.querySelector('#reader-dot');if(!dot)return;
 dot.classList.toggle('off',!h||!h.ready);
 document.querySelector('#reader-name').textContent=h?'Context layer connected':'Saved on this device';
 document.querySelector('#reader-detail').innerHTML=h?`Reads inputs with ${esc(readerName(h))}<br>${h.ready?'Ready':esc(h.reason||'Not ready')}`:'Rules engine only<br>Context layer not connected';
}

// The four stages of the workflow, each with the one number that matters now.
export function workflow(el,model,rows,h){
 const done=rows.filter(r=>r.reading?.status==='done');
 const facts=done.reduce((n,r)=>n+Object.keys(r.reading.facts||{}).length,0);
 const conflicts=done.filter(r=>r.reading.conflict?.verified).length;
 const changed=model.jobs.reduce((n,j)=>n+j.history.filter(x=>x.from!==0).length,0);
 const unknown=model.gaps.length+done.filter(r=>r.reading.unknown).length;
 const waiting=rows.filter(r=>r.reading?.action?.status==='proposed').length;
 const channels=new Set(model.sources.map(r=>r.channel)).size;
 const stage=(n,title,big,label,line,go)=>`<button class="stage" ${go?`data-goto="${go}"`:''}><span class="stage-n">${n}</span><span class="stage-title">${title}</span><strong>${big}</strong><span class="stage-label">${label}</span><small>${line}</small></button>`;
 el.innerHTML=`<div class="panel-heading"><div><h2>From messy inputs to approved next steps</h2></div><span class="mini-label">${h?'LIVE · '+esc(readerName(h)).toUpperCase():'RULES ONLY'}</span></div><div class="stages">`
  +stage(1,'Messy inputs',model.sources.length,'entries',`${channels} channels · ${rows.length} new`,'sources')
  +stage(2,'Context layer',h?facts:'—',h?'facts verified':'not connected',h?`${conflicts} conflict${conflicts===1?'':'s'} · every fact quoted`:'rules read the messages')
  +stage(3,'Verified context',model.jobs.length,'jobs known',`${changed} changes · ${unknown} unknown`,'jobs')
  +stage(4,'Agents',model.tasks.length+waiting,'next steps',waiting?`${waiting} waiting for your OK`:'you approve each one','tasks')
  +'</div>';
}

function actionBlock(row,full){
 const a=row.reading?.action;if(!a)return'';
 const head=`<span class="kind">${esc(KIND[a.kind]||a.kind)}</span><strong>${esc(a.text)}</strong>`;
 const reply=full&&row.reading.reply?`<p class="reply">“${esc(row.reading.reply)}”</p>`:'';
 if(a.status!=='proposed')return `<div class="action ${a.status}">${head}${reply}<span class="decided">${a.status==='approved'?'✓ Approved':'Dismissed'}</span></div>`;
 return `<div class="action">${head}${reply}<div class="action-buttons"><button class="primary" data-decide="approved" data-id="${esc(row.source_id)}">Approve</button><button class="quiet" data-decide="dismissed" data-id="${esc(row.source_id)}">Dismiss</button></div></div>`;
}

// The newest input and what the context layer made of it.
export function latest(el,rows,model){
 const row=rows[rows.length-1];el.hidden=!row;if(!row)return;
 const r=row.reading||{},job=model.jobs.find(j=>j.id===row.job_context);
 const who=({owner:'owner',customer:'customer',worker:'crew'})[row.author_role]||row.author_role;
 let body;
 if(r.status==='reading')body='<p class="reading">Reading against the job history…</p>';
 else if(r.status==='failed')body=`<p class="failed">Not read: ${esc(r.error)}. Kept as a message.</p>`;
 else{
  const facts=Object.entries(r.facts||{}).map(([k,v])=>`<li><span>${FACT[k]}</span><strong>${esc(factText(k,v))}</strong></li>`).join('');
  body=(facts?`<ul class="facts">${facts}</ul>`:'<p class="muted">Nothing in it changes a job.</p>')
   +(r.conflict?`<p class="finding conflict"><b>Conflict</b> ${esc(r.conflict.text)}</p>`:'')
   +(r.unknown?`<p class="finding unknown"><b>Still unknown</b> ${esc(r.unknown)}</p>`:'')
   +(r.rejected?.length?`<p class="finding rejected"><b>Not applied</b> ${r.rejected.map(x=>esc(FACT[x.key]||x.key)).join(', ')}: the words were not in the input</p>`:'')
   +actionBlock(row,true);
 }
 el.innerHTML=`<div class="panel-heading"><div><h2>Latest input · ${job?esc(job.address+' · '+job.customer):r.status==='done'?'customer not found':'…'}</h2><p class="muted">${esc(row.channel)} from the ${esc(who)} · ${esc(row.sent_at.slice(0,16).replace('T',' '))}</p></div><span class="mini-label">${r.reader?esc((r.reader.source==='cache'?'CACHED · ':'')+(r.reader.reader==='llm'?'MODEL':'REACTOR')+(r.reader.latency_s?' · '+Math.round(r.reader.latency_s)+'S':'')):'CONTEXT LAYER'}</span></div><blockquote>${marked(row)}</blockquote>${body}`;
}

// Every step the agents proposed, newest first; nothing happens until a person approves.
export function proposals(el,rows,model){
 const list=rows.filter(r=>r.reading?.action).reverse();el.hidden=!list.length;if(!list.length)return;
 const waiting=list.filter(r=>r.reading.action.status==='proposed').length;
 el.innerHTML=`<div class="panel-heading"><h2>Proposed by the agents · ${waiting} waiting</h2><span class="mini-label">HUMAN APPROVAL</span></div>`
  +list.map(r=>{const j=model.jobs.find(j=>j.id===r.job_context);return `<div class="proposal"><small>${esc(j?j.address+' · '+j.customer:'Unplaced input')}</small>${actionBlock(r,false)}</div>`;}).join('');
}
