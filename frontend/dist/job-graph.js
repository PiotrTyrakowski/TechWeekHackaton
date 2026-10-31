const NS='http://www.w3.org/2000/svg';
const COLORS={company:'#d7e1e8',customer:'#88b7da',job:'#91cba6',fact:'#e1c484',gap:'#dab385'};
const STATUS={pending:'Awaiting decision',agreed:'Agreed',completed:'Done · not paid',paid:'Paid'};
const PLAIN_STATUS={pending:'No decision yet',agreed:'Confirmed',completed:'Awaiting payment',paid:'Paid'};
const html=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function svgElement(tag,attributes={},text){const node=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attributes))node.setAttribute(k,String(v));if(text!==undefined)node.textContent=text;return node;}

export function graphData(model){
 const nodes=[{id:'company',type:'company',label:'Company',radius:25}],edges=[];
 model.jobs.forEach((job,row)=>{
  const customer='customer:'+job.id,fact='fact:'+job.id;
  nodes.push({id:customer,type:'customer',label:job.customer.split(' ')[0],title:job.customer,radius:26,job,row,column:1},
   {id:job.id,type:'job',label:job.address,title:job.address,radius:30,job,row,column:2},
   {id:fact,type:'fact',label:job.amount.toLocaleString('en-GB')+' PLN',title:STATUS[job.status],radius:29,job,row,column:3});
  edges.push({from:'company',to:customer,label:'CUSTOMER'},{from:customer,to:job.id,label:'ORDERS'},{from:job.id,to:fact,label:'CURRENTLY'});
 });
 model.gaps.forEach((record,i)=>nodes.push({id:'gap:'+record.source_id,type:'gap',label:'?',title:'Needs clarifying · '+record.source_id,radius:23,record,gapIndex:i}));
 return {nodes,edges};
}

export class JobGraph{
 constructor(container,callbacks){
  this.container=container;this.callbacks=callbacks;this.focus='';this.selected=null;this.camera={x:0,y:0,k:1};this.positions=new Map();
  container.classList.add('knowledge-graph');
  container.innerHTML=`<div class="kg-toolbar"><div class="kg-label">COMPANY MEMORY <span class="kg-live">● current state</span></div><label class="kg-filter">Job <select aria-label="Filter the graph by job"><option value="">All jobs</option></select></label></div><div class="kg-canvas"><svg role="group" aria-label="Graph of customers, jobs and current facts"></svg><div class="kg-zoom"><button type="button" data-zoom="in" aria-label="Zoom in">＋</button><button type="button" data-zoom="out" aria-label="Zoom out">−</button><button type="button" data-zoom="reset" aria-label="Re-centre">↺</button></div></div><div class="kg-legend"><span><i style="background:${COLORS.company}"></i>Company</span><span><i style="background:${COLORS.customer}"></i>Customer</span><span><i style="background:${COLORS.job}"></i>Job</span><span><i style="background:${COLORS.fact}"></i>Current fact</span><span class="kg-help">Drag nodes · scroll to zoom</span></div><div class="kg-selection" aria-live="polite"><div><strong class="kg-selection-title">Click a node to trace a fact.</strong><p class="kg-selection-description">You will see the current state, the sources and the next step.</p></div><button type="button" class="kg-open" disabled>Open sources ↗</button></div>`;
  this.advanced=document.createElement('div');this.advanced.className='kg-advanced';while(container.firstChild)this.advanced.append(container.firstChild);this.advanced.hidden=true;
  this.modebar=document.createElement('div');this.modebar.className='kg-modebar';this.modebar.innerHTML='<button type="button" class="kg-mode-toggle" aria-expanded="false">Relationship graph</button>';
  this.simple=document.createElement('div');this.simple.className='kg-simple';container.append(this.modebar,this.simple,this.advanced);
  this.modebar.querySelector('button').onclick=e=>{const advancedVisible=this.advanced.hidden;this.advanced.hidden=!advancedVisible;this.simple.hidden=advancedVisible;e.currentTarget.textContent=advancedVisible?'Simple view':'Relationship graph';e.currentTarget.setAttribute('aria-expanded',String(advancedVisible));if(advancedVisible)requestAnimationFrame(()=>this.layout());};
  this.simple.addEventListener('click',e=>{const open=e.target.closest('[data-simple-job]');if(open)this.callbacks.onJob(open.dataset.simpleJob);const task=e.target.closest('[data-simple-task]');if(task)this.callbacks.onTask?.(task.dataset.simpleTask,task.dataset.taskType);const gap=e.target.closest('[data-simple-gap]');if(gap){const record=this.model.gaps.find(r=>r.source_id===gap.dataset.simpleGap);if(record)this.callbacks.onGap(record);}});
  this.simple.addEventListener('click',e=>{const more=e.target.closest('[data-show-all]');if(more){this.showAll=more.dataset.showAll==='true';this.renderSimple();}});
  this.svg=container.querySelector('svg');this.filter=container.querySelector('select');this.surface=container.querySelector('.kg-canvas');this.title=container.querySelector('.kg-selection-title');this.description=container.querySelector('.kg-selection-description');this.open=container.querySelector('.kg-open');
  this.filter.onchange=()=>{this.focus=this.filter.value;this.highlight();if(this.focus){const n=this.data.nodes.find(n=>n.id===this.focus);if(n)this.choose(n);}else{this.selected=null;this.highlight();this.showSelection();}};
  this.open.onclick=()=>{const n=this.data.nodes.find(n=>n.id===this.selected);if(n?.job)this.callbacks.onJob(n.job.id);else if(n?.record)this.callbacks.onGap(n.record);};
  container.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{if(b.dataset.zoom==='reset'){this.camera={x:0,y:0,k:1};this.positions.clear();this.layout();}else this.zoom(b.dataset.zoom==='in'?1.2:1/1.2);});
  this.svg.addEventListener('pointerdown',e=>{this.drag={pan:true,x:e.clientX,y:e.clientY,ox:this.camera.x,oy:this.camera.y};this.svg.setPointerCapture(e.pointerId);});
  this.svg.addEventListener('pointermove',e=>{const d=this.drag;if(!d)return;d.moved ||= Math.hypot(e.clientX-d.x,e.clientY-d.y)>4;if(d.pan){this.camera.x=d.ox+e.clientX-d.x;this.camera.y=d.oy+e.clientY-d.y;this.transform();}else{const rect=this.svg.getBoundingClientRect();d.node.x=(e.clientX-rect.left-this.camera.x)/this.camera.k;d.node.y=(e.clientY-rect.top-this.camera.y)/this.camera.k;this.positions.set(d.node.id,{x:d.node.x,y:d.node.y});this.updatePositions();}});
  this.svg.addEventListener('pointerup',e=>{if(this.drag?.node&&!this.drag.moved)this.choose(this.drag.node);this.drag=null;if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);});
  this.svg.addEventListener('pointercancel',()=>this.drag=null);
  this.svg.addEventListener('wheel',e=>{e.preventDefault();const r=this.svg.getBoundingClientRect();this.zoom(e.deltaY<0?1.1:1/1.1,e.clientX-r.left,e.clientY-r.top);},{passive:false});
  this.resizeObserver=new ResizeObserver(entries=>{if(entries[0].contentRect.width>0){this.positions.clear();this.layout();}});this.resizeObserver.observe(this.surface);
 }
 setModel(model,date){
  this.model=model;this.date=date;this.data=graphData(model);
  if(this.focus&&!model.jobs.some(j=>j.id===this.focus))this.focus='';
  this.filter.replaceChildren(new Option('All jobs',''),...model.jobs.map(j=>new Option(j.address+' · '+j.customer,j.id)));this.filter.value=this.focus;
  const meta=this.container.querySelector('.kg-live');meta.textContent='● '+date+' · '+model.jobs.length+' jobs';
  if(this.selected&&!this.data.nodes.some(n=>n.id===this.selected))this.selected=null;
  this.render();this.showSelection();this.renderSimple();
 }
 renderSimple(){
  const tasks=new Map(this.model.tasks.map(t=>[t.job,t]));
  const needs=this.model.jobs.filter(j=>tasks.has(j.id)).sort((a,b)=>{const ad=tasks.get(a.id).due||'9999',bd=tasks.get(b.id).due||'9999';return ad.localeCompare(bd)||a.address.localeCompare(b.address,'pl');}),others=this.model.jobs.filter(j=>!tasks.has(j.id));
  const heading='<div class="hs-columns" aria-hidden="true"><span>Customer</span><span>Job</span><span>Amount</span><span>Action</span></div>';
  const row=j=>{const task=tasks.get(j.id),plain=PLAIN_STATUS[j.status]||'To check';
   const due=task?.due?(task.due===this.date?'Today':task.due<this.date?'Overdue':new Date(task.due+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'long'})):'';
   const action=task?{decision:'Ask for a decision',budget:'Discuss the price',schedule:'Set the date',payment:'Ask about payment'}[task.type]||'Write to the customer':'';
   const date=j.start&&j.status==='agreed'?new Date(j.start+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'long'}):'';
   return `<article class="hs-row ${task?'hs-needs':''}" data-updated="${this.lastAmounts?.has(j.id)&&this.lastAmounts.get(j.id)!==j.amount}" aria-label="${html(j.customer+', '+j.address)}"><button type="button" class="hs-person" data-simple-job="${html(j.id)}" aria-label="Facts: ${html(j.customer)}"><strong>${html(j.customer)} <span class="hs-open-mark" aria-hidden="true">↗</span></strong></button><button type="button" class="hs-place hs-connected" data-simple-job="${html(j.id)}"><strong>${html(j.address)}</strong>${date?`<small>${html(date)}</small>`:''}</button><div class="hs-amount hs-connected"><strong>${j.amount.toLocaleString('en-GB')} <span>PLN</span></strong><span class="hs-status ${html(j.status)}">${html(plain)}</span>${j.budget&&j.amount>j.budget?`<small class="hs-budget">Budget: ${j.budget.toLocaleString('en-GB')} PLN</small>`:''}</div><div class="hs-action hs-connected">${due?`<span class="hs-due">${html(due)}</span>`:''}${task?`<button type="button" data-simple-task="${html(j.id)}" data-task-type="${html(task.type)}">${html(action)}</button>`:`<button type="button" class="hs-secondary" data-simple-job="${html(j.id)}">Details</button>`}</div></article>`;
  };
  const visibleNeeds=this.showAll?needs:needs.slice(0,6),visibleOthers=this.showAll?others:others.slice(0,3);
  this.simple.innerHTML=`<section class="hs-group"><div class="hs-group-title"><h3>${needs.length?'To do':'All taken care of'}</h3>${needs.length?`<span>${needs.length}</span>`:''}</div>${needs.length?heading+visibleNeeds.map(row).join(''):''}</section>${others.length?`<section class="hs-group"><div class="hs-group-title"><h3>Other jobs</h3><span>${others.length}</span></div>${visibleOthers.map(row).join('')}</section>`:''}${needs.length>6||others.length>3?`<button type="button" class="hs-show-all" data-show-all="${!this.showAll}">${this.showAll?'Show less':'All jobs ('+this.model.jobs.length+')'}</button>`:''}${this.model.gaps.map(r=>`<section class="hs-gap"><div><strong>Customer missing</strong><p>“${html(r.raw_text.slice(0,65))}${r.raw_text.length>65?'…':''}”</p></div><button type="button" data-simple-gap="${html(r.source_id)}">Fill in</button></section>`).join('')}`;
  this.lastAmounts=new Map(this.model.jobs.map(j=>[j.id,j.amount]));
 }

 render(){
  this.svg.replaceChildren();this.root=svgElement('g');this.svg.append(this.root);
  this.edgeElements=this.data.edges.map(edge=>{const g=svgElement('g'),line=svgElement('line',{class:'kg-edge'});g.append(line);let text=null;if(edge.from!=='company'){text=svgElement('text',{class:'kg-edge-label'},edge.label);g.append(text);}this.root.append(g);return {edge,g,line,text};});
  this.nodeElements=this.data.nodes.map(node=>{const g=svgElement('g',{class:'kg-node',role:'button',tabindex:0,'aria-label':node.type==='fact'?'Fact: '+node.job.address+', '+node.label+', '+node.title:(node.type==='job'?'Job: ':'')+(node.title||node.label)});g.append(svgElement('title',{},node.title||node.label));g.append(svgElement('circle',{r:node.radius,fill:COLORS[node.type]}));
   const lines=node.type==='job'?node.label.split(' '):[node.label];lines.forEach((line,i)=>g.append(svgElement('text',{y:(i-(lines.length-1)/2)*12+4},line)));
   if(node.type==='fact')g.append(svgElement('text',{y:node.radius+18,class:'kg-node-caption'},STATUS[node.job.status]));
   if(node.type==='gap')g.append(svgElement('text',{y:node.radius+17,class:'kg-node-caption'},'To clarify'));
   g.addEventListener('pointerdown',e=>{e.stopPropagation();this.drag={node,x:e.clientX,y:e.clientY,moved:false};this.svg.setPointerCapture(e.pointerId);});
   g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();this.choose(node);}});this.root.append(g);return {node,g};
  });this.layout();
 }
 layout(){if(!this.data)return;this.width=this.surface.clientWidth||700;this.network=this.model.jobs.length>8&&this.width>=700;this.height=this.network?850:Math.max(560,130+this.model.jobs.length*102+Math.ceil(this.model.gaps.length/5)*50);this.surface.style.height=this.height+'px';const w=this.width,h=this.height,compact=w<480;
  this.data.nodes.forEach(n=>{const cached=this.positions.get(n.id);if(cached){Object.assign(n,cached);return;}if(this.network){if(n.type==='company'){n.x=w/2;n.y=h/2;}else if(n.type==='gap'){const a=n.gapIndex/Math.max(1,this.model.gaps.length)*Math.PI*2;n.x=w/2+Math.cos(a)*80;n.y=h/2+Math.sin(a)*80;}else{const a=-Math.PI/2+n.row/this.model.jobs.length*Math.PI*2;const radius={1:.21,2:.32,3:.43}[n.column];n.x=w/2+Math.cos(a)*w*radius;n.y=h/2+Math.sin(a)*h*(radius*.92);}}else if(n.type==='company'){n.x=Math.max(28,w*.055);n.y=compact?28:(h-70)/2;}else if(n.type==='gap'){n.x=w*(.28+(n.gapIndex%5)*.14);n.y=h-45-Math.floor(n.gapIndex/5)*55;}else{n.x=w*((compact?{1:.23,2:.52,3:.80}:{1:.28,2:.56,3:.84})[n.column]);n.y=(compact?100:62)+n.row*102;}});this.updatePositions();this.transform();
 }
 updatePositions(){const nodes=new Map(this.data.nodes.map(n=>[n.id,n]));for(const {edge,line,text}of this.edgeElements){const a=nodes.get(edge.from),b=nodes.get(edge.to),dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1;for(const [attr,value]of Object.entries({x1:a.x+dx/d*a.radius,y1:a.y+dy/d*a.radius,x2:b.x-dx/d*b.radius,y2:b.y-dy/d*b.radius}))line.setAttribute(attr,value);if(text){text.setAttribute('x',(a.x+b.x)/2);text.setAttribute('y',(a.y+b.y)/2-6);}}for(const {node,g}of this.nodeElements)g.setAttribute('transform',`translate(${node.x},${node.y})`);this.highlight();}
 transform(){this.root?.setAttribute('transform',`translate(${this.camera.x},${this.camera.y}) scale(${this.camera.k})`);}
 zoom(f,x=this.width/2,y=this.height/2){const k=Math.max(.5,Math.min(3,this.camera.k*f)),r=k/this.camera.k;this.camera.x=x-(x-this.camera.x)*r;this.camera.y=y-(y-this.camera.y)*r;this.camera.k=k;this.transform();}
 choose(node){this.selected=node.id;this.focus=node.job?.id||'';this.filter.value=this.focus;this.showSelection();this.highlight();}
 showSelection(){const node=this.data?.nodes.find(n=>n.id===this.selected);this.open.disabled=!node?.job&&!node?.record;
  if(node?.job){const j=node.job,t=this.model.tasks.find(t=>t.job===j.id);this.title.textContent=j.customer+' · '+j.address+' · '+j.amount.toLocaleString('en-GB')+' PLN';this.description.textContent=STATUS[j.status]+' · '+j.evidence.length+' sources'+(t?' · Next step: '+t.title:'')+(j.excludes.length?' · Without the cabin install':'');this.open.textContent='Open sources ↗';}
  else if(node?.record){this.title.textContent='Note '+node.record.source_id+' · customer unknown';this.description.textContent=node.record.raw_text;this.open.textContent='Clarify →';}
  else{this.title.textContent='Click a node to trace a fact.';this.description.textContent='You will see the current state, the sources and the next step.';this.open.textContent='Open sources ↗';}
 }
 highlight(){if(!this.nodeElements)return;const chosen=this.data.nodes.find(n=>n.id===this.selected);for(const {node,g}of this.nodeElements){const matches=!this.focus||(node.id==='company'||node.job?.id===this.focus);g.classList.toggle('kg-dim',!matches);g.classList.toggle('kg-selected',node.id===chosen?.id);}for(const {edge,g,text}of this.edgeElements){g.classList.toggle('kg-dim',!!this.focus&&!edge.to.endsWith(this.focus));if(text)text.style.display=this.network&&!this.focus?'none':'';}}
}
