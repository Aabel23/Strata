"use strict";
// App shell. Read-only except writes through POST /api/project and POST /api/item (token-guarded). All text goes through textContent (el() from page.js); never assigns markup.
// el, get, enc and renderPage come from page.js (STRATA_SHELL makes it skip its own routing).
const $=id=>document.getElementById(id);
const TABS=[["task","Task","t"],["docs","Docs","r"],["c4","Architecture","a"],["audit","Log","l"],["codemap","Code map","m"]];
const TAB_LABEL=Object.fromEntries(TABS.map(t=>[t[0],t[1]]));
const ST_ITEM=["proposed","approved","open","doing","review","done","rejected"];
const ST_DOC=["current","draft","outdated","missing"], KIND_DOC=["research","architect","review","plan","other"];
const store={get(k){try{return localStorage.getItem(k)}catch{return null}},set(k,v){try{localStorage.setItem(k,v)}catch{}}};
const NOGRP="Ungrouped";
let PROJ=[], byId={}, token=0;

/* ---------- ornament + icons: constant SVG strings only (numbers computed here, never user text) ---------- */
const svg=s=>document.importNode(new DOMParser().parseFromString(s,"image/svg+xml").documentElement,true);
const S=(vb,body,extra)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb}" fill="none" stroke="currentColor" aria-hidden="true" ${extra||""}>${body}</svg>`;
const O={
  // crescent moon: logo mark
  moon:S("0 0 24 24",'<path d="M15.5 3.2a9 9 0 1 0 5.6 14.6A7.4 7.4 0 0 1 15.5 3.2z" stroke-width="1.3"/><circle cx="18.6" cy="5.4" r=".7" fill="currentColor" stroke="none" opacity=".7"/>'),
  // 夔龙 (HSK QuyLongBand): empty states only. A band, so running off the edge is allowed.
  dragon:'<svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><pattern id="kl" width="72" height="24" patternUnits="userSpaceOnUse">'+
    '<g fill="none" stroke="currentColor" stroke-width=".9" stroke-linejoin="round"><path d="M4 18 V8 H16 V4 H26 V18 Z"/><path d="M10 12 a2.5 2.5 0 1 0 0.01 0" stroke-width=".7"/>'+
    '<path d="M26 11 H40 V6 H52 V16 H62 V10 H68"/><path d="M40 16 H50" stroke-width=".6" opacity=".75"/><path d="M30 18 V22 M46 18 V22 M58 16 V22" stroke-width=".7" opacity=".8"/>'+
    '<path d="M68 10 a3 3 0 0 1 2 5"/></g></pattern></defs><rect width="100%" height="100%" fill="url(#kl)"/></svg>',
};
// procedural fading contour lines: sidebar header (fixed seed), overview background + project cards (seeded by id)
function contours(seed,w=480,h=200,n=8){
  let s=seed%233280;const r=()=>((s=(s*9301+49297)%233280)/233280), ph=[r()*6,r()*6,r()*6];let p="";
  for(let i=0;i<n;i++){const k=h/200, y0=h*(.3+.6*i/(n-1));let d="M0 "+y0.toFixed(1);
    for(let x=-32;x<=w+32;x+=8)d+=" L"+x+" "+(y0-k*(Math.sin(x/90+ph[0]+i*.3)*14+Math.sin(x/37+ph[1])*6*(1-i/n)+Math.sin(x/170+ph[2])*22)).toFixed(1);
    p+=`<path d="${d}" stroke-opacity="${(.9*(1-i/n)).toFixed(2)}"/>`}
  return S(`0 0 ${w} ${h}`,p,'stroke-width="1" vector-effect="non-scaling-stroke" preserveAspectRatio="none"');
}
// traced hero art (static asset from scripts/trace_hero.py), fetched once and inlined so CSS can colour fills and strokes
const HERO={};const heroArt=n=>HERO[n]||(HERO[n]=fetch("/assets/hero-"+n+".svg").then(r=>r.ok?r.text():Promise.reject()).then(svg));
const hash=s=>{let h=7;for(const c of String(s))h=(h*31+c.charCodeAt(0))>>>0;return h};
// one status icon for every list (Linear geometry: dashed / ring / half / filled check / x / !)
const SI={
  dash:'<circle cx="7" cy="7" r="5.5" stroke-width="1.5" stroke-dasharray="2 2.3"/>',
  ring:'<circle cx="7" cy="7" r="5.5" stroke-width="1.5"/>',
  half:'<circle cx="7" cy="7" r="5.5" stroke-width="1.5"/><path d="M7 3.5A3.5 3.5 0 0 1 7 10.5Z" fill="currentColor" stroke="none"/>',
  done:'<circle cx="7" cy="7" r="6.5" fill="currentColor" stroke="none"/><path d="M4.4 7.2l1.8 1.8 3.5-3.7" stroke-width="1.5" style="stroke:var(--bg)"/>',
  x:'<circle cx="7" cy="7" r="6.5" fill="currentColor" stroke="none"/><path d="M5 5l4 4M9 5l-4 4" stroke-width="1.5" style="stroke:var(--bg)"/>',
};
const SHAPE={review:"half",proposed:"dash",draft:"half",approved:"ring",open:"ring",outdated:"ring",doing:"half",done:"done",current:"done",accepted:"done",rejected:"x",missing:"x",superseded:"x"};
function statusIcon(st){const e=svg(S("0 0 14 14",SI[SHAPE[st]]||SI.ring,'class="si"'));e.classList.add("s-"+st);return e}
const PRI={low:'<rect x="2" y="10" width="3" height="4" rx="1" fill="currentColor" stroke="none"/><rect x="6.5" y="6" width="3" height="8" rx="1" fill="currentColor" stroke="none" opacity=".3"/><rect x="11" y="2" width="3" height="12" rx="1" fill="currentColor" stroke="none" opacity=".3"/>',
  medium:'<rect x="2" y="10" width="3" height="4" rx="1" fill="currentColor" stroke="none"/><rect x="6.5" y="6" width="3" height="8" rx="1" fill="currentColor" stroke="none"/><rect x="11" y="2" width="3" height="12" rx="1" fill="currentColor" stroke="none" opacity=".3"/>',
  high:'<rect x="2" y="10" width="3" height="4" rx="1" fill="currentColor" stroke="none"/><rect x="6.5" y="6" width="3" height="8" rx="1" fill="currentColor" stroke="none"/><rect x="11" y="2" width="3" height="12" rx="1" fill="currentColor" stroke="none"/>',
  urgent:'<rect x="1" y="1" width="14" height="14" rx="3" fill="currentColor" stroke="none" style="color:var(--st-block)"/><path d="M8 4.5v4.5M8 11.2v.3" stroke-width="1.8" style="stroke:var(--bg)"/>',
  none:'<path d="M2 8h2.5M6.75 8h2.5M11.5 8H14" stroke-width="1.5" opacity=".5"/>'};
const priIcon=p=>{const e=svg(S("0 0 16 16",PRI[p]||PRI.none,'class="pri"')), t=document.createElementNS("http://www.w3.org/2000/svg","title");t.textContent=p||"no priority";e.append(t);return e};
const IC={edit:'<path d="M3 13l.6-2.8 7-7a1.4 1.4 0 0 1 2 2l-7 7z"/>',plus:'<path d="M8 3.5v9M3.5 8h9"/>',trash:'<path d="M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.5 8h5l.5-8"/>',overview:'<path d="M2.5 13.5h11M4 11V7M8 11V3.5M12 11V6"/>',task:'<circle cx="8" cy="8" r="5.5"/><path d="M5.6 8.1l1.6 1.6 3.2-3.4"/>',
  docs:'<path d="M4 2.5h5.5L12 5v8.5H4z"/><path d="M6 8h4M6 10.5h4"/>',
  c4:'<rect x="2.5" y="2.5" width="4" height="4" rx="1"/><rect x="9.5" y="9.5" width="4" height="4" rx="1"/><path d="M6.5 4.5h3a2 2 0 0 1 2 2v3"/>',
  codemap:'<circle cx="4" cy="4" r="1.6"/><circle cx="12" cy="5" r="1.6"/><circle cx="7" cy="12" r="1.6"/><path d="M5.4 4.3l5 .5M4.8 5.4l1.6 5M10.9 6.4l-3 4.2"/>',
  audit:'<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3l2 1.5"/>',folder:'<path d="M2.5 4.5h4l1.5 1.5h5.5v6.5h-11z"/>',proj:'<path d="M2 12.5l3.5-6 2.5 3.5 2-2.5 4 5z"/>',
  chev:'<path d="M6 4l4 4-4 4"/>',prev:'<path d="M10 4L6 8l4 4"/>',reload:'<path d="M13 8a5 5 0 1 1-1.5-3.5M13 3v2.5h-2.5"/>',
  ext:'<path d="M9 3h4v4M13 3L7.5 8.5M11 9.5V13H3V5h3.5"/>',copy:'<rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.5"/><path d="M10.5 5.5V3H3v7.5h2.5"/>',
  sun:'<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>'};
const icon=k=>svg(S("0 0 16 16",IC[k],'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"'));
const orn=(cls,s)=>{const d=el("div",cls);d.setAttribute("aria-hidden","true");d.append(svg(s));return d};
function empty(title,hint,code,tail){
  const d=el("div","empty");d.append(orn("dragon",O.dragon),el("b","",title));
  if(hint){const p=el("p","muted",hint);if(code)p.append(" ",el("code","",code));if(tail)p.append(tail);d.append(p)}
  return d;
}

/* ---------- routing ---------- */
const hashFor=(p,tab,id)=>"#/p/"+enc(p)+"/"+(tab||"task")+(id!=null&&id!==""?"/"+String(id).split("/").map(enc).join("/"):"");
function link(text,href,cls){const a=el("a",cls||"",text);a.href=href;return a}
const hq=()=>{const i=location.hash.indexOf("?");return new URLSearchParams(i<0?"":location.hash.slice(i+1))};
function route(){
  const i=location.hash.indexOf("?"), raw=i<0?location.hash:location.hash.slice(0,i);
  const h=raw.startsWith("#/")?raw.slice(2).split("/").map(decodeURIComponent):[];
  if(h[0]==="p"&&byId[h[1]]) return {p:h[1],tab:h[2]==="issue"?"task":TAB_LABEL[h[2]]?h[2]:"task",id:h.slice(3).join("/")};
  return {p:(PROJ.find(x=>!x.parent)||PROJ[0]||{}).id,tab:"task",id:""};
}
const total=o=>Object.values(o||{}).reduce((a,b)=>a+b,0);
function counts(p){return {task:total(p.tasks),docs:p.docs}}
let CUR={};

/* ---------- writes: project add/edit/delete (POST /api/project) and task add/edit/delete (POST /api/item), all via service + audit. ---------- */
let TOK=null;
// every write: JSON + X-Strata-Edit + per-start token; one refetch/retry on 403 (server restart changes the token)
async function api(url,body){
  const send=async()=>{
    if(!TOK)TOK=(await get("/api/session")).token;
    return fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-Strata-Edit":"1","X-Strata-Token":TOK},body:JSON.stringify(body)});
  };
  let r=await send();
  if(r.status===403){TOK=null;r=await send()}
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.error||("HTTP "+r.status));
  return d;
}
const projectPost=body=>api("/api/project",body);
function dialog(title,body,actions){
  const d=el("dialog","pdlg edge");d.setAttribute("aria-labelledby","pdt");
  const f=el("form");f.method="dialog";const h=el("h2","",title);h.id="pdt";
  const err=el("p","perr");err.setAttribute("role","alert");err.hidden=true;
  const foot=el("div","pfoot");f.append(h,...body,err,foot);d.append(f);
  const fail=m=>{err.textContent=m;err.hidden=!m};
  const cancel=el("button","","Cancel");cancel.type="button";cancel.onclick=()=>d.close();
  foot.append(cancel,...actions(d,fail));
  d.addEventListener("close",()=>d.remove());
  document.body.append(d);d.showModal();
  return d;
}
function field(label,id,attrs,node){
  const w=el("label","pfield");w.htmlFor=id;w.append(el("span","",label));
  const i=node||el("input");i.id=id;Object.entries(attrs||{}).forEach(([k,v])=>i.setAttribute(k,v));w.append(i);return w;
}
function addProject(){
  const name=field("Name","pn",{autocomplete:"off",required:""}), pid=field("ID","pi",{autocomplete:"off",required:"",pattern:"[a-z0-9][a-z0-9_-]{0,39}",placeholder:"lowercase, digits, - or _"});
  const root=field("Code folder (optional)","pr",{autocomplete:"off",placeholder:"/home/you/project/app"});
  const docs=field("Docs folder (optional)","pdocs",{autocomplete:"off",placeholder:"defaults to nothing; relative paths start at the code folder"});
  const sel=el("select");sel.append(new Option("none",""));PROJ.forEach(p=>sel.append(new Option(p.name+" ("+p.id+")",p.id)));
  const par=field("Inside project (optional)","pp",null,sel);
  const desc=field("Description (optional)","pd",{autocomplete:"off"});
  const ni=name.lastChild, ii=pid.lastChild;let touched=false;
  ii.addEventListener("input",()=>{touched=true});
  ni.addEventListener("input",()=>{if(!touched)ii.value=ni.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/đ/g,"d").replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,40)});
  const setup=el("input");setup.type="checkbox";setup.id="psetup";setup.checked=false;setup.disabled=true;
  const sl=el("label","pcheck");sl.htmlFor="psetup";const hint=el("small","","Enter a code folder to turn this on.");sl.append(setup,el("span","","Set up docs, architecture map and code map"),hint);
  const sync=()=>{const has=!!root.lastChild.value.trim();if(has&&setup.disabled)setup.checked=true;if(!has)setup.checked=false;setup.disabled=!has;hint.hidden=has};
  ["input","change","paste"].forEach(ev=>root.lastChild.addEventListener(ev,()=>setTimeout(sync)));sync();
  const STEP={project:["Project registered","Could not register the project"],docs:["Docs folders created","Docs folders failed"],c4:["Starter architecture map created","Architecture map failed"],codemap:["Code map is ready","Code map failed"]};
  const line=s=>{const t=STEP[s.step]||[s.step,s.step],d=s.detail?": "+s.detail:"";
    if(s.status==="done")return["✓ "+t[0]];
    if(s.status==="started")return["… "+(s.step==="codemap"?"Code map is building in the background":t[0]+" (in progress)")];
    if(s.status==="skipped")return["– "+(s.step==="codemap"?"No code found, code map skipped":s.step==="docs"?"Docs folders already there":s.step==="c4"?"Architecture map already there":s.step==="project"?"Already set up as "+((s.detail||"").match(/registered as (\S+)/)||[0,"an existing project"])[1]:t[0].replace(/ created| registered/,"")+" skipped"+d)];
    return["✗ "+t[1]+d]};
  const d=dialog("Add project",[name,pid,root,docs,par,desc,sl],(d,fail)=>{
    const ok=el("button","primary","Add project");ok.type="submit";
    d.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
      try{const id=ii.value.trim(),body={op:"add",id,name:ni.value,root:root.lastChild.value,docs_dir:docs.lastChild.value,parent:sel.value,description:desc.lastChild.value};
        if(setup.checked)body.setup=true;
        const r=await projectPost(body),go=()=>{d.close();location.hash=hashFor(r.id||id,"task");render()};
        if(!setup.checked||!r.steps)return go();
        const f=d.firstChild,ul=el("ul","psteps");r.steps.forEach(s=>{const li=el("li","pstep "+s.status,line(s)[0]);ul.append(li)});
        d.querySelector("h2").textContent=r.steps.some(s=>s.step==="project"&&s.status==="skipped")?"Project ready":"Project added";
        const open=el("button","primary","Open project");open.type="button";open.onclick=go;
        f.replaceChildren(f.querySelector("h2"),ul,f.querySelector(".perr"),el("div","pfoot"));f.lastChild.append(open);open.focus();await render(true)}
      catch(x){fail(x.message);ok.disabled=false}};
    return [ok]});
  ni.focus();return d;
}
function editProject(p){
  const name=field("Name","pn",{autocomplete:"off",required:""}), root=field("Code folder","pr",{autocomplete:"off"}), docs=field("Docs folder","pdocs",{autocomplete:"off"});
  const sel=el("select");sel.append(new Option("none",""));
  PROJ.filter(x=>x.id!==p.id&&!isUnder(x,p.id)).forEach(x=>sel.append(new Option(x.name+" ("+x.id+")",x.id)));
  const par=field("Inside project","pp",null,sel), desc=field("Description","pd",{autocomplete:"off"});
  name.lastChild.value=p.name||"";root.lastChild.value=p.root||"";docs.lastChild.value=p.docs_dir||"";sel.value=p.parent||"";desc.lastChild.value=p.description||"";
  const info=el("p","pinfo","ID "+p.id+" cannot change. Empty fields are cleared.");
  return dialog("Edit “"+p.name+"”",[info,name,root,docs,par,desc],(d,fail)=>{
    const ok=el("button","primary","Save");ok.type="submit";
    d.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
      try{await projectPost({op:"edit",id:p.id,name:name.lastChild.value,root:root.lastChild.value,docs_dir:docs.lastChild.value,parent:sel.value,description:desc.lastChild.value});d.close();await render(true)}
      catch(x){fail(x.message);ok.disabled=false}};
    return [ok]});
}
const isUnder=(x,id)=>{for(let q=x;q;q=byId[q.parent])if(q.parent===id)return true;return false};
async function deleteProject(p){
  const kids=PROJ.filter(x=>x.parent===p.id);
  let use={};try{use=await get("/api/project-usage?project="+enc(p.id))}catch{}
  const LABEL={item:"tasks and issues",doc:"indexed docs",page:"pages",c4_object:"map objects",c4_connection:"map links",c4_flow:"flows",c4_contract:"contracts",c4_behavior:"behaviors",c4_link:"task-to-map links"};
  const lines=Object.entries(use).filter(([k])=>LABEL[k]).map(([k,n])=>n+" "+LABEL[k]);
  const info=el("p","pinfo");
  info.textContent=kids.length?"This project contains "+kids.map(k=>k.name).join(", ")+". Delete or move those first."
    :"Removes "+(lines.join(", ")||"nothing but the project entry")+" from Strata. Your files on disk and the Log are not touched.";
  const conf=field("Type "+p.id+" to confirm","pc",{autocomplete:"off"});
  return dialog("Delete “"+p.name+"”",kids.length?[info]:[info,conf],(d,fail)=>{
    if(kids.length)return [];
    const ok=el("button","danger","Delete project");ok.type="submit";ok.disabled=true;
    conf.lastChild.addEventListener("input",()=>{ok.disabled=conf.lastChild.value!==p.id});
    d.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
      try{await projectPost({op:"delete",id:p.id,confirm:conf.lastChild.value});d.close();
        if(CUR.p===p.id)location.hash="#/";await render()}
      catch(x){fail(x.message);ok.disabled=false}};
    return [ok]});
}

/* ---------- sidebar + breadcrumb ---------- */
function side(r){
  // flat list of real projects; groups (anything that is some project's parent) stay reachable via breadcrumb/palette
  const leaf=PROJ.filter(p=>!PROJ.some(x=>x.parent===p.id));
  $("tree").replaceChildren(...leaf.map(p=>{
    const a=link("",hashFor(p.id,"task"),"it"+(p.id===r.p?" on":""));
    if(p.id===r.p)a.setAttribute("aria-current","page");
    a.append(icon("proj"),el("span","l",p.name));
    const x=el("button","pdel ib");x.type="button";x.append(icon("trash"));x.title=x.ariaLabel="Delete project "+p.name;x.onclick=()=>deleteProject(p);
    const e=el("button","pdel pedit ib");e.type="button";e.append(icon("edit"));e.title=e.ariaLabel="Edit project "+p.name;e.onclick=()=>editProject(p);
    const w=el("div","pi");w.append(a,e,x);return w}));
  const c=r.p?counts(byId[r.p]):{};
  $("tablabel").hidden=!r.p;
  $("tabs").replaceChildren(...(r.p?TABS.map(([k,l])=>{
    const a=link("",hashFor(r.p,k),"it"+(k===r.tab?" on edge":""));a.append(icon(k),el("span","l",l));
    if(k===r.tab)a.setAttribute("aria-current","page");
    if(c[k])a.append(el("span","n",c[k]));a.title=l+" (G "+TABS.find(t=>t[0]===k)[2].toUpperCase()+")";return a}):[]));
}
function crumbs(r){
  const chain=[];for(let p=byId[r.p];p;p=byId[p.parent])chain.unshift(p);
  const parts=[], sep=()=>el("span","sep","›");
  chain.forEach((p,i)=>{if(i)parts.push(sep());parts.push(link(p.name,hashFor(p.id,"task")))});
  if(r.p){parts.push(sep(),r.id?link(TAB_LABEL[r.tab],hashFor(r.p,r.tab)):el("b","",TAB_LABEL[r.tab]));
    if(r.id)parts.push(sep(),el("b","",r.id.split("/").pop()))}
  $("crumbs").replaceChildren(...parts);
}

async function render(keep){
  const my=++token;
  document.body.classList.remove("menu");
  try{PROJ=await get("/api/projects");byId=Object.fromEntries(PROJ.map(p=>[p.id,p]))}catch(e){return $("content").replaceChildren(el("p","err",e.message))}
  if(my!==token)return;
  const r=route();CUR=r;side(r);crumbs(r);chatProjectChanged();
  const box=el("div");
  try{
    if(!r.p){box.append(empty("No projects yet","Run","strata init"," in your project folder, or click + to add one."))}
    else await VIEW[r.tab](box,r.p,r.id);
  }catch(e){box.append(el("p","err",e.message))}
  if(my!==token)return;
  document.title=(r.p?byId[r.p].name+" · "+TAB_LABEL[r.tab]+" · ":"")+"Strata";
  const rd=box.querySelector(":scope>.reader");
  if(!rd&&!box.className)box.className="page"+(r.tab==="task"?" wide":"");
  const sc=$("content").scrollTop;
  $("content").replaceChildren(rd||box);
  $("content").scrollTop=keep===true?sc:0;
}
/* gold sheen: one global scheduler, strictly sequential. Wait 6-12s, sweep ONE random visible title once, repeat. */
const calm=matchMedia("(prefers-reduced-motion: reduce)");
(function sheenLoop(){setTimeout(()=>{
  const ts=[...document.querySelectorAll(".foil,#pg header h1")].filter(e=>e.getClientRects().length);
  if(document.hidden||calm.matches||!ts.length)return sheenLoop();
  const e=ts[Math.floor(Math.random()*ts.length)], done=()=>{if(over)return;over=1;e.classList.remove("sweep");sheenLoop()};let over=0;
  e.addEventListener("animationend",done,{once:true});e.addEventListener("animationcancel",done,{once:true});
  setTimeout(done,6500); // title removed mid-sweep fires no animationend
  e.classList.add("sweep")},6e3+Math.random()*6e3)})();

/* ---------- small builders ---------- */
const ago=s=>(s||"").slice(0,16).replace("T"," ");
function rel(s){
  if(!s)return "";const m=(Date.now()-Date.parse(s))/6e4;
  return m<1?"just now":m<60?Math.round(m)+"p":m<1440?Math.round(m/60)+"h":m<43200?Math.round(m/1440)+"d":Math.round(m/43200)+"th";
}
function dateCell(s){const d=el("span","d",rel(s));d.title=ago(s);return d}
function pill(st){const p=el("span","pill s-"+st);p.append(el("i"),st);return p}
function head(title,n){const h=el("div","head");h.append(el("h1","foil",title));if(n!=null)h.append(el("span","n",n));return h}
function fbar(groups){
  const b=el("div","fbar");b.append(el("span","lbl","Filter"));
  groups.forEach(([opts,cur,on,plain],i)=>{if(i)b.append(el("span","sp"));
    ["",...opts].forEach(o=>{const x=el("button",o===cur?"on":"");if(o&&!plain)x.append(statusIcon(o));x.append(o||"all");
      x.setAttribute("aria-pressed",o===cur);x.onclick=()=>on(o);b.append(x)})});
  return b;
}
function grouped(rows,key,order,label,mkRow){
  const out=[], g={};rows.forEach(x=>(g[key(x)]=g[key(x)]||[]).push(x));
  [...order.filter(k=>g[k]),...Object.keys(g).filter(k=>!order.includes(k)).sort((a,b)=>(a===NOGRP)-(b===NOGRP)||a.localeCompare(b))].forEach(k=>{
    const h=el("div","grouph");label(k,h);h.append(el("span","n",g[k].length));out.push(h,...g[k].map(mkRow))});
  return out;
}
function card(title,tab,p,rows,emptyText,n){
  const c=el("div","card edge"), h=el("h2","",title);if(n!=null)h.append(el("span","n",n));h.append(link("View all →",hashFor(p,tab)));
  const ul=el("ul");
  if(!rows.length)ul.append(el("li","muted",emptyText||"Empty"));
  rows.forEach(([st,t,href,extra])=>{const li=el("li");if(st)li.append(statusIcon(st));li.append(link(t,href));if(extra)li.append(extra);ul.append(li)});
  c.append(h,ul);return c;
}

const VIEW={
  task:(box,p,id)=>boardView(box,p,id),
  async docs(box,p,id){
    const docs=await get("/api/docs?project="+enc(p));
    docs.forEach(x=>{try{x.code=JSON.parse(x.code||"[]")||[]}catch{x.code=[]}});
    if(id)return docReader(box,p,id,docs);
    if(!docs.length){box.append(head("Contents",0));return box.append(empty("No docs yet","A doc is a short YAML page of notes or decisions. Add one, for example:",(byId[p].docs_dir||"docs")+"/research/notes.yaml"))}
    toc(box,p,docs.filter(x=>x.status!=="missing"),docs.filter(x=>x.status==="missing").length);
  },
  async c4(box,p,id){
    const r=el("div","reader c4"), f=el("iframe","frame c4");
    f.src="/c4?project="+enc(p)+"&embed=1"+(id?"#"+enc(id):"");f.title="C4 architecture";r.append(f);box.append(r);
  },
  async codemap(box,p){
    const r=el("div","reader c4"), f=el("iframe","frame c4");
    f.src="/codemap/?project="+enc(p);f.title="Code map";r.append(f);box.append(r);
  },
  async audit(box,p){
    const rs=await get("/api/audit?limit=200&project="+enc(p));
    box.append(head("Log",rs.length));
    if(!rs.length)return box.append(empty("No records yet","Every change via CLI/MCP is recorded here."));
    const day=d=>d.toDateString(), today=new Date(), yest=new Date(Date.now()-864e5);
    let last="";
    rs.forEach(x=>{const d=new Date(x.ts);
      if(day(d)!==last){last=day(d);box.append(el("div","dayh",last===day(today)?"Today":last===day(yest)?"Yesterday":d.toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"})))}
      const a=x.after||"", r=el("div","arow");
      r.append(el("span","tm",isNaN(d)?"":d.toTimeString().slice(0,5)),el("span","ac",x.actor_role||""),el("span","v",x.tool||""),el("span","",x.target||""),el("span","df",a.length>160?a.slice(0,160)+"…":a));
      r.title=ago(x.ts);box.append(r)});
  },
};

/* ---------- contents: chapter = subfolder of docs_dir, left tree = folder tree ---------- */
const NOCODE="General", CHAP={architect:"Engineering",research:"Research",plan:"Plan",review:"Review"}, CHAP_ORDER=["architect","research","plan","review"];
const dirOf=x=>x.path.includes("/")?x.path.replace(/\/[^/]*$/,"")+"/":"";
const docGroup=x=>{const i=x.path.indexOf("/");return i<0?NOCODE:x.path.slice(0,i)};
const chapName=k=>CHAP[k]||k;
function dirTree(docs){
  const root={name:"",path:"",kids:{},n:0};
  docs.forEach(d=>{let n=root;n.n++;const segs=dirOf(d).split("/").filter(Boolean);
    segs.forEach((sg,i)=>{n=n.kids[sg]||(n.kids[sg]={name:sg,path:segs.slice(0,i+1).join("/")+"/",kids:{},n:0});n.n++})});
  return root;
}
const chapSort=(a,b)=>(a===NOCODE)-(b===NOCODE)||((CHAP_ORDER.indexOf(a)+1||99)-(CHAP_ORDER.indexOf(b)+1||99))||a.localeCompare(b);
function toc(box,p,docs,missing){
  let sel=null, q="";
  try{sel=sessionStorage.getItem("strata-toc-"+p)}catch{}
  const wrap=el("div","toc"), side=el("nav","ctree"), list=el("div","chapters");
  const h=el("header","toch");
  h.append(el("div","eyebrow","Docs · "+(byId[p]?byId[p].name:p)),el("h1","foil","Contents"),
    el("p","muted",docs.length+" docs in "+new Set(docs.map(docGroup)).size+" chapters"+(missing?" · "+missing+" files missing":"")));
  const f=el("input");f.type="search";f.id="tocq";f.placeholder="Search contents…";f.setAttribute("aria-label","Search docs");
  f.oninput=()=>{q=f.value.toLowerCase();draw()};h.append(f);
  side.setAttribute("aria-label","Docs folder tree");
  const pick=v=>{sel=v;try{v==null?sessionStorage.removeItem("strata-toc-"+p):sessionStorage.setItem("strata-toc-"+p,v)}catch{};drawTree();draw()};
  const tree=dirTree(docs), loose=docs.filter(x=>!dirOf(x)).length;
  function node(n,depth){
    const b=el("button","tn"+(sel===n.path?" on":"")), kids=Object.values(n.kids).sort((a,b)=>depth?a.name.localeCompare(b.name):chapSort(a.name,b.name));
    b.style.setProperty("--d",depth);
    b.append(el("span","tg",kids.length?"▾":"·"),el("span","nm",depth?n.name+"/":chapName(n.name)),el("span","n",n.n));
    b.title=n.path;b.onclick=()=>pick(sel===n.path?null:n.path);
    return [b,...kids.flatMap(k=>node(k,depth+1))];
  }
  function drawTree(){
    const all=el("button","tn root"+(sel==null?" on":""));all.append(el("span","nm","All"),el("span","n",docs.length));all.onclick=()=>pick(null);
    const kids=Object.values(tree.kids).sort((a,b)=>chapSort(a.name,b.name)).flatMap(k=>node(k,0));
    if(loose){const b=el("button","tn"+(sel===""?" on":""));b.append(el("span","tg","·"),el("span","nm",NOCODE),el("span","n",loose));b.onclick=()=>pick(sel===""?null:"");kids.push(b)}
    side.replaceChildren(el("div","slabel","Folders"),all,...kids);
  }
  const match=x=>(sel==null||(sel===""?!dirOf(x):dirOf(x).startsWith(sel)))
    &&(!q||(x.title+" "+(x.summary||"")+" "+x.path+" "+x.code.join(" ")).toLowerCase().includes(q));
  const entry=x=>{
    const li=el("li"), a=link("",hashFor(p,"docs",x.path),"entry");
    const line=el("span","line");line.append(el("span","tt",x.title),el("span","dots"),dateCell(x.updated_at));a.append(line);
    if(x.summary)a.append(el("span","sum",x.summary));
    const meta=el("span","em");x.code.forEach(c=>meta.append(el("code","",c)));
    const ext=x.path.split(".").pop();if(ext!=="yaml")meta.append(el("span","fmt",ext));
    if(x.status!=="current")meta.append(pill(x.status));
    if(meta.childNodes.length)a.append(meta);
    li.append(a);return li;
  };
  function draw(){
    const rows=docs.filter(match);
    if(!rows.length){const e=empty("No matching docs");const c=el("button","","Clear filter");c.onclick=()=>{q="";f.value="";pick(null)};e.append(c);return list.replaceChildren(e)}
    const g={};rows.forEach(x=>(g[docGroup(x)]=g[docGroup(x)]||[]).push(x));
    list.replaceChildren(...Object.keys(g).sort(chapSort).map(k=>{
      const sec=el("section","chap"), hh=el("h2");hh.append(el("span","cn",chapName(k)));if(k!==NOCODE)hh.append(el("code","",k+"/"));hh.append(el("span","n",g[k].length+" docs"));sec.append(hh);
      // sections inside a chapter = deeper folders (architect/features/…)
      const sub={};g[k].forEach(x=>{const d=dirOf(x).split("/").slice(1).join("/");(sub[d]=sub[d]||[]).push(x)});
      Object.keys(sub).sort((a,b)=>(a!=="")-(b!=="")||a.localeCompare(b)).forEach(d=>{
        if(d)sec.append(el("h3","sub",d.replace(/\/$/,"").replace(/\//g," › ")));
        const ol=el("ol");sub[d].sort((a,b)=>a.ord-b.ord||a.title.localeCompare(b.title)).forEach(x=>ol.append(entry(x)));sec.append(ol)});
      return sec}));
  }
  drawTree();draw();wrap.append(side,list);box.append(h,wrap);
}

/* one YAML doc rendered with the page blocks; re-renders when the file changes on disk */
function docView(f,p,path){
  const api="/api/doc?project="+enc(p)+"&path="+enc(path);let mt=null;
  const linkFor=l=>/^https?:\/\//.test(l)?l:hashFor(p,"docs",(l.startsWith("/")?l.slice(1):(path.includes("/")?path.replace(/[^/]*$/,""):"")+l).replace(/(\.yaml)?$/,".yaml"));
  const render=d=>{
    const art=el("article","doc");
    const hd=el("header");
    if(d.code.length){const e=el("div","eyebrow");d.code.forEach(c=>e.append(el("code","",c)));hd.append(e)}
    hd.append(el("h1","",d.title||path));if(d.summary)hd.append(el("p","lede",d.summary));art.append(hd);
    if(d.errors.length){const e=el("div","docerr");e.append(el("b","","Doc has structural errors"));const ul=el("ul");d.errors.forEach(x=>ul.append(el("li","",x)));e.append(ul);art.append(e)}
    d.blocks.forEach(b=>{const s=el("section");
      try{s.append(b.type==="c4"?c4(b,p):b.type==="query"?query(b):b.type==="diagram"||b.type==="statemachine"?({diagram,statemachine})[b.type](b,linkFor):R[b.type]?R[b.type](b):el("p","err","Unknown block type: "+b.type))}
      catch(e){s.append(el("p","err",e.message))}
      art.append(s)});
    f.replaceChildren(art);
  };
  const load=()=>get(api).then(d=>{if(d.mtime!==mt){mt=d.mtime;render(d)}}).catch(e=>f.replaceChildren(el("p","err",e.message)));
  load();
  const t=setInterval(()=>{if(!f.isConnected)return clearInterval(t);load()},2000);
  return ()=>{mt=null;load()};
}

function toolBtn(ic,title,href,on){
  const a=el(href?"a":"button","ib");a.append(icon(ic));a.title=title;a.setAttribute("aria-label",title);
  if(href){a.href=href;a.target="_blank";a.rel="noopener"}else a.onclick=on;return a;
}
function docReader(box,p,id,docs){
  const d=docs.find(x=>x.path===id), url="/docs/"+enc(p)+"/"+id.split("/").map(enc).join("/");
  const sib=docs.filter(x=>x.status!=="missing"&&(!d||docGroup(x)===docGroup(d))), i=sib.findIndex(x=>x.path===id);
  const r=el("div","reader"), t=el("div","tbar"), back=link("",hashFor(p,"docs"),"back");back.append(icon("prev"),"Docs");
  t.append(back,el("span","ttl",d?d.title:id));
  if(d)t.append(el("span","kind",d.kind),pill(d.status));
  const nav=(k,ic,lbl)=>{const x=sib[i+k], b=toolBtn(ic,lbl+" (Alt "+(k<0?"←":"→")+")",null,()=>{if(x)location.hash=hashFor(p,"docs",x.path)});b.disabled=!x;b.dataset.nav=k;return b};
  const nx=nav(1,"chev","Next doc");
  t.append(nav(-1,"prev","Previous doc"),nx);
  r.append(t);box.append(r);
  if(!d||d.status==="missing")return r.append(empty("File is gone from disk or not yet scanned","Run again:","strata.py doc scan --project "+p));
  const isY=id.endsWith(".yaml"), isMd=id.endsWith(".md"), f=isY||isMd?el("div","frame mdoc"):el("iframe","frame");
  const load=isY?docView(f,p,id):()=>isMd?fetch(url).then(x=>x.text()).then(s=>f.replaceChildren(md(s))):(f.src=url);f.title=d.title;if(!isY)load();
  t.append(toolBtn("reload","Reload",null,load),toolBtn("ext","Open in new tab",url),
    toolBtn("copy","Copy link",null,()=>{navigator.clipboard&&navigator.clipboard.writeText(location.href).catch(()=>{})}));
  r.append(f);
}

/* ---------- task board (read-only): status columns, task popup. Filters live in the hash query. ---------- */
const COLS=["open","proposed","approved","doing","review"], FOLD=["done","rejected"], COLLBL={open:"To do"};
const PRI_TAG={p0:"P0",p1:"P1",p2:"P2",p3:"P3"};
const BKIND=["task","step"];
const DAY=864e5;
function tag(text,cls,title){const t=el("span","tag"+(cls?" "+cls:""),text);if(title)t.title=title;return t}
const acN=x=>((x.spec&&x.spec.acceptance)||[]).length;
function claimAge(x){return x.status==="doing"&&x.claimed_at?rel(x.claimed_at):""}
const stale=x=>x.status==="doing"&&x.claimed_at&&Date.now()-Date.parse(x.claimed_at)>DAY;
function boardHref(p,id,qs){const s=qs.toString();return hashFor(p,"task",id)+(s?"?"+s:"")}
function itemCard(x,p,qs,sel,blockedBy){
  const a=link("",boardHref(p,x.id,qs),"tcard"+(String(x.id)===sel?" sel":""));
  const m=el("span","mono","#"+x.id+(x.kind!=="task"?" "+x.kind:"")+(x.owner?" · "+x.owner:"")+(claimAge(x)?" · "+claimAge(x):""));
  const row=el("span","trow");
  if(x.label)row.append(tag(x.label,"lbl-"+x.label));
  if(x.priority)row.append(tag(PRI_TAG[String(x.priority).toLowerCase()]||x.priority,"pri-"+String(x.priority).toLowerCase()));
  if(acN(x))row.append(tag("AC "+acN(x)));
  if(blockedBy&&blockedBy.length)row.append(tag("blocked by "+blockedBy.map(i=>"#"+i).join(" "),"block"));
  else if(x.spec&&x.spec.blocked)row.append(tag("blocked","block"));
  if(stale(x))row.append(tag("over 24h","stale","Claimed more than 24 hours ago"));
  a.append(m,el("span","t",x.title),row);return a;
}
function fold(label,items,mk){
  const d=el("details","tfold");d.append(el("summary","",label+" · "+items.length));
  const c=el("div","cards");items.forEach(x=>c.append(mk(x)));d.append(c);return d;
}
function chipRow(label,opts,cur,set){
  const r=el("div","tchips");r.append(el("span","lbl",label));
  ["",...opts].forEach(o=>{const b=el("button",o===cur?"on":"",o||"all");b.setAttribute("aria-pressed",o===cur);b.onclick=()=>set(o);r.append(b)});
  return r;
}
async function boardView(box,p,id){
  const bg=el("div","herobg");bg.setAttribute("aria-hidden","true");const mt=el("div","mtn"), wv=el("div","waves");bg.append(wv,mt);box.append(bg);
  heroArt("mountains").then(x=>mt.append(x.cloneNode(true))).catch(()=>{});
  heroArt("mountains-waves").then(x=>wv.append(x.cloneNode(true))).catch(()=>{});
  const qs=hq(), f={kind:qs.get("kind")||"",status:qs.get("status")||"",owner:qs.get("owner")||"",q:qs.get("q")||""};
  const go=patch=>{const n=new URLSearchParams(qs);Object.entries(patch).forEach(([k,v])=>v?n.set(k,v):n.delete(k));location.hash=boardHref(p,CUR.id?id:"",n)};
  const all=await get("/api/items?project="+enc(p));
  const owners=[...new Set(all.map(x=>x.owner).filter(Boolean))].sort();
  all.sort((a,b)=>(b.label==="issue")-(a.label==="issue")); // stable: issues first, API order otherwise
  const needle=f.q.toLowerCase();
  const vis=all.filter(x=>(!f.kind||x.kind===f.kind)&&(!f.status||x.status===f.status)&&(!f.owner||x.owner===f.owner)&&(!needle||(x.title+" #"+x.id).toLowerCase().includes(needle)));
  const hd=head("Board",vis.length), nb=el("button","primary tadd","+ Task");nb.type="button";nb.onclick=()=>taskForm(p,null);hd.append(nb);box.append(hd);
  const bar=el("div","tbar2");
  const search=el("input");search.type="search";search.id="tq";search.placeholder="Search titles…";search.value=f.q;search.setAttribute("aria-label","Search titles");
  search.onchange=()=>go({q:search.value.trim()});
  bar.append(chipRow("Kind",BKIND,f.kind,v=>go({kind:v})),chipRow("Status",ST_ITEM,f.status,v=>go({status:v})));
  if(owners.length)bar.append(chipRow("Owner",owners,f.owner,v=>go({owner:v})));
  bar.append(search);box.append(bar);
  const act=[...Object.entries(f)].filter(([,v])=>v);
  if(act.length){const c=el("div","tactive");act.forEach(([k,v])=>{const b=el("button","chipx",k+": "+v+" ×");b.onclick=()=>go({[k]:""});c.append(b)});box.append(c)}
  const main=el("div","tmain"), board=el("div","tboard"), mk=x=>itemCard(x,p,qs,id);
  COLS.forEach(st=>{
    const its=vis.filter(x=>x.status===st), col=el("section","tcol"), h=el("h3");
    h.append(statusIcon(st),(COLLBL[st]||st)+" · "+its.length);col.append(h);
    const c=el("div","cards");its.forEach(x=>c.append(mk(x)));if(!its.length)c.append(el("p","muted tnone","Empty"));col.append(c);board.append(col);
  });
  const folds=el("div","tfolds");
  FOLD.forEach(st=>{const its=vis.filter(x=>x.status===st);if(its.length){const d=fold(st,its,mk);if(its.some(x=>String(x.id)===String(id)))d.open=true;folds.append(d)}});
  const left=el("div","tleft");left.append(board);if(folds.children.length)left.append(folds);
  main.append(left);box.append(main);
  if(!all.length)box.prepend(empty("No work items yet","Add via CLI:","strata.py item add --project "+p+" --kind task --title ..."));
  if(!id)return;
  const d=(await get("/api/items?id="+enc(id)))[0];
  if(!d||d.project!==p)return;
  const popup=el("aside","tdetail");popup.setAttribute("role","dialog");popup.setAttribute("aria-label","Task details");
  const close=el("button","tdetail-close","×");close.type="button";close.setAttribute("aria-label","Close task details");close.onclick=closeTaskPopup;
  popup.append(close);detailPane(popup,d,p,qs);box.append(popup);
  requestAnimationFrame(()=>{if(popup.isConnected)placeTaskPopup(popup,box.querySelector(".tcard.sel"))});
}
function closeTaskPopup(refresh=false){
  const r=route();if(r.tab!=="task"||!r.id)return;
  const s=hq().toString(), base=hashFor(r.p,"task")+(s?"?"+s:"");
  history.replaceState(null,"",base);
  if(refresh)return render(true);
  CUR={...r,id:""};document.querySelector(".tdetail")?.remove();
  document.querySelectorAll(".tcard.sel").forEach(c=>c.classList.remove("sel"));crumbs(CUR);
}
function placeTaskPopup(popup,card){
  if(matchMedia("(max-width: 600px)").matches)return;
  const gap=12,m=12,w=popup.offsetWidth,h=popup.offsetHeight,W=innerWidth,H=innerHeight;
  const r=card&&card.getBoundingClientRect();
  if(!r||!r.width||!r.height){popup.style.left=Math.max(m,(W-w)/2)+"px";popup.style.top=Math.max(m,(H-h)/2)+"px";return}
  const left=r.right+gap+w+m<=W?r.right+gap:Math.max(m,r.left-gap-w);
  popup.style.left=Math.max(m,Math.min(W-w-m,left))+"px";
  popup.style.top=Math.max(m,Math.min(H-h-m,r.top))+"px";
}
/* ---------- task write forms: add / edit / delete ---------- */
const PRIS=["p0","p1","p2","p3"], KINDS_ADD=["task","issue","step","gate","rule","knowledge","draft","note"];
const splitLines=v=>v.split("\n").map(x=>x.trim()).filter(Boolean);
const ta=(label,id,rows,val,ph)=>{const t=el("textarea");t.rows=rows;t.value=val||"";return field(label,id,ph?{placeholder:ph,autocomplete:"off"}:null,t)};
const selField=(label,id,opts,cur)=>{const s=el("select");opts.forEach(o=>s.append(new Option(o||"none",o)));if(cur&&!opts.includes(cur))s.append(new Option(cur,cur));s.value=cur||"";return field(label,id,null,s)};
const val=f=>f.lastChild.value;
// d == null: add; else edit. After a write the board reloads; add selects the new task.
function taskForm(p,d){
  const sp=(d&&d.spec)||{}, sc=sp.scope||{}, need0=d?d.deps.needs.map(x=>x.id):[];
  const title=field("Title","tt",{autocomplete:"off",required:""}), kind=selField("Kind","tk",KINDS_ADD,d?d.kind:"task");
  title.lastChild.value=d?d.title:"";
  const st=selField("Status","ts",ST_ITEM,d?d.status:"proposed"), pr=selField("Priority","tp",["",...PRIS],d&&d.priority||"");
  const body=ta("Description","tb",4,d&&d.body), goal=ta("Goal","tg",2,sp.goal);
  const ac=ta("Acceptance (one per line)","ta",4,(sp.acceptance||[]).map(a=>typeof a==="string"?a:JSON.stringify(a)).join("\n"));
  const ver=field("Verify command","tv",{autocomplete:"off"});ver.lastChild.value=sp.verify||"";
  const touch=ta("Scope: may touch (one per line)","tto",2,(sc.touch||[]).join("\n")), forb=ta("Scope: must not touch (one per line)","tf",2,(sc.forbid||[]).join("\n"));
  const deps=field("Needs (task ids, comma separated)","tdp",{autocomplete:"off",placeholder:"e.g. 12, 15"});deps.lastChild.value=need0.join(", ");
  const row=(...f)=>{const r=el("div","prow");r.append(...f);return r};
  const spec=()=>{const o={...sp,goal:val(goal).trim(),acceptance:splitLines(val(ac)),verify:val(ver).trim(),scope:{...sc,touch:splitLines(val(touch)),forbid:splitLines(val(forb))}};return o};
  const hasSpec=()=>val(goal).trim()||val(ac).trim()||val(ver).trim()||val(touch).trim()||val(forb).trim();
  return dialog(d?"Edit #"+d.id:"Add task",[title,row(...(d?[]:[kind]),st,pr),body,goal,ac,ver,row(touch,forb),deps],(dlg,fail)=>{
    dlg.classList.add("pwide");
    const ok=el("button","primary",d?"Save":"Add");ok.type="submit";
    dlg.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
      try{
        const ids=val(deps).split(/[\s,]+/).filter(Boolean);
        if(ids.some(x=>!/^\d+$/.test(x)))throw new Error("Needs: use task numbers like 12, 15");
        const want=ids.map(Number);let id;
        if(d){
          const b={op:"edit",id:d.id,title:val(title),body:val(body),priority:val(pr),spec:spec()};
          if(val(st)!==d.status)b.status=val(st);
          if(!b.priority)delete b.priority; // shortcut: an existing priority cannot be cleared from the form
          await api("/api/item?project="+enc(p),b);id=d.id;
        }else{
          const k=val(kind), b={op:"add",kind:k==="issue"?"issue":k,title:val(title),body:val(body),status:val(st)};
          if(val(pr))b.priority=val(pr);if(hasSpec())b.spec=spec();
          id=(await api("/api/item?project="+enc(p),b)).id;
        }
        for(const n of want)if(!need0.includes(n))await api("/api/item?project="+enc(p),{op:"dep_add",id,depends_on:n});
        for(const n of need0)if(!want.includes(n))await api("/api/item?project="+enc(p),{op:"dep_rm",id,depends_on:n});
        dlg.close();if(!d)location.hash=hashFor(p,"task",id);await render(true);
      }catch(x){fail(x.message);ok.disabled=false}};
    return [ok]});
}
function deleteTask(p,d){
  const info=el("p","pinfo","Permanently deletes #"+d.id+" “"+d.title+"” and its dependency links. This cannot be undone.");
  return dialog("Delete #"+d.id,[info],(dlg,fail)=>{
    const ok=el("button","danger","Delete task");ok.type="submit";
    dlg.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
      try{await api("/api/item?project="+enc(p),{op:"delete",id:d.id});dlg.close();location.hash=hashFor(p,"task");await render()}
      catch(x){fail(x.message);ok.disabled=false}};
    return [ok]});
}
function dlink(x,p,qs){const a=link("#"+x.id+" "+x.title,boardHref(p,x.id,qs),"dep");a.append(" ",pill(x.status));return a}
function section(c,title,node){if(!node)return;const s=el("div","dsec");s.append(el("h4","",title),node);c.append(s)}
function detailPane(c,d,p,qs){
  const sp=d.spec||{}, ac=sp.acceptance||[];
  const acts=el("div","dact"),eb=el("button","","Edit"),db=el("button","danger","Delete");eb.type=db.type="button";eb.onclick=()=>taskForm(p,d);db.onclick=()=>deleteTask(p,d);acts.append(eb,db);
  const top=el("div");top.append(acts,el("span","mono","#"+d.id+" "+d.kind+" · "+d.status+(d.owner?" · owner "+d.owner:"")+(d.claimed_at?" · claim "+ago(d.claimed_at).slice(5):"")),el("h2","",d.title));
  const pr=el("div","props");pr.append(pill(d.status));
  if(d.priority){const s=el("span");s.append(priIcon(d.priority)," "+d.priority);s.style.display="inline-flex";s.style.gap="4px";pr.append(s)}
  if(d.label)pr.append(tag(d.label,"lbl-"+d.label));
  pr.append(el("span","",ago(d.updated_at||d.created_at)));top.append(pr);c.append(top);
  section(c,"Goal",sp.goal?el("p","dtxt",sp.goal):null);
  if(ac.length){const ul=el("ul","acl");ac.forEach(a=>{const li=el("li");li.append(el("span","cb","☐"),el("span","",typeof a==="string"?a:JSON.stringify(a)));ul.append(li)});section(c,"Criteria · "+ac.length,ul)}
  if(sp.verify){const pre=el("pre");pre.append(el("code","",sp.verify));section(c,"Verify",pre)}
  const sc=sp.scope||{};
  if((sc.touch||[]).length||(sc.forbid||[]).length){
    const w=el("div","scope");
    [["touch",sc.touch],["forbid",sc.forbid]].forEach(([k,v])=>{if(v&&v.length){const r=el("div","srow");r.append(el("b","",k));const l=el("span","mono",v.join("  "));r.append(l);w.append(r)}});
    section(c,"Scope",w)}
  if((sp.open_questions||[]).length){const ul=el("ul");sp.open_questions.forEach(q=>ul.append(el("li","",String(q))));section(c,"Open questions",ul)}
  const dp=d.deps||{needs:[],blocks:[]};
  if(dp.needs.length||dp.blocks.length){
    const w=el("div","deps");
    [["Needs",dp.needs],["Blocks",dp.blocks]].forEach(([k,v])=>{if(v.length){const r=el("div","srow");r.append(el("b","",k));const l=el("span","dlist");v.forEach(x=>l.append(dlink(x,p,qs)));r.append(l);w.append(r)}});
    section(c,"Dependencies",w)}
  const lk=d.links||{c4:[]};
  if(lk.c4.length){
    const w=el("div","deps");
    if(lk.c4.length){const r=el("div","srow");r.append(el("b","","C4"));const l=el("span","dlist");lk.c4.forEach(o=>l.append(link(o,"#/p/"+enc(p)+"/c4/"+enc(o),"dep")));r.append(l);w.append(r)}
    section(c,"Links",w)}
  if(d.history&&d.history.length){
    const tl=el("div","tl");
    d.history.forEach(h=>{const r=el("div");r.append(el("span","mono",ago(h.time).slice(5)),el("span","",h.actor||""),
      el("span","",h.to?(h.from?h.from+" → ":"")+h.to+(h.note?" · "+h.note:""):h.tool.replace("item.","")+(h.note?" · "+h.note:"")));tl.append(r)});
    section(c,"History",tl)}
  if(d.body){const b=el("div","dbody");b.append(md(d.body));section(c,"Description",b)}
}

const LBL={done:"done",doing:"in progress",todo:"upcoming"};

/* ---------- command palette ---------- */
const SRC={item:["Task","task"],doc:["Docs","docs"]};
let hits=[], sel=0, qtok=0, timer=null, mouseMoved=false;
function openPal(){closeKeys();$("pal").hidden=false;$("q").value="";hits=navHits();sel=0;drawHits();$("q").focus()}
function closePal(){$("pal").hidden=true}
function navHits(){
  const out=[];
  if(CUR.p)TABS.forEach(([k,l,g])=>out.push({grp:"Navigation",title:l,sub:byId[CUR.p].name,ic:k,kbd:"G "+g.toUpperCase(),run:()=>{location.hash=hashFor(CUR.p,k)}}));
  PROJ.filter(p=>p.id!==CUR.p).forEach(p=>out.push({grp:"Projects",title:p.name,sub:p.id,ic:"proj",run:()=>{location.hash=hashFor(p.id,"task")}}));
  out.push({grp:"Commands",title:"Add project…",ic:"plus",run:addProject});
  out.push({grp:"Commands",title:"Toggle light / dark",ic:"sun",run:toggleTheme},{grp:"Commands",title:"Keyboard shortcuts",ic:"help",kbd:"?",run:openKeys});
  return out;
}
function searchHits(r){
  const by={};r.forEach(h=>{const t=h.src;(by[t]=by[t]||[]).push(h)});
  return Object.keys(SRC).filter(t=>by[t]).flatMap(t=>by[t].slice(0,8).map(h=>({grp:SRC[t][0],title:h.title||"(untitled)",ic:SRC[t][1],
    sub:(byId[h.project]?byId[h.project].name:h.project)+(h.snippet?" · "+h.snippet.replace(/\s+/g," "):""),
    run:()=>{location.hash=hashFor(h.project,SRC[t][1],h.src==="page"||h.src==="doc"?h.key:h.ref)}})));
}
function drawHits(){
  const out=[];let g="";
  if(!hits.length)out.push(el("li","none","No results"));
  hits.forEach((h,i)=>{
    if(h.grp!==g){g=h.grp;const x=el("li","gh",g);x.setAttribute("role","presentation");out.push(x)}
    const li=el("li","h"+(i===sel?" on":""));li.id="hit"+i;li.setAttribute("role","option");li.setAttribute("aria-selected",i===sel);
    const tx=el("span","tx");tx.append(el("span","t",h.title));if(h.sub)tx.append(el("span","s",h.sub));
    li.append(icon(h.ic),tx);if(h.kbd)li.append(el("kbd","",h.kbd));
    li.onmousedown=e=>{e.preventDefault();go(h)};
    li.onmousemove=()=>{if(mouseMoved&&sel!==i){sel=i;mark()}};out.push(li)});
  $("hits").replaceChildren(...out);mark();
}
function mark(){
  $("hits").querySelectorAll(".h").forEach(li=>{const on=li.id==="hit"+sel;li.classList.toggle("on",on);li.setAttribute("aria-selected",on)});
  $("q").setAttribute("aria-activedescendant",hits.length?"hit"+sel:"");
  const on=$("hit"+sel);if(on&&on.scrollIntoView)on.scrollIntoView({block:"nearest"});
}
function go(h){closePal();h.run()}
$("hits").addEventListener("mousemove",()=>{mouseMoved=true});
$("q").addEventListener("input",()=>{
  clearTimeout(timer);mouseMoved=false;const v=$("q").value.trim();
  if(!v){hits=navHits();sel=0;return drawHits()}
  timer=setTimeout(()=>{const my=++qtok;
    get("/api/search?q="+enc(v)).then(r=>{if(my===qtok){hits=searchHits(r);sel=0;drawHits()}}).catch(()=>{if(my===qtok){hits=[];drawHits()}})},120);
});
$("q").addEventListener("keydown",e=>{
  if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();mouseMoved=false;if(hits.length){sel=(sel+(e.key==="ArrowDown"?1:hits.length-1))%hits.length;mark()}}
  else if(e.key==="Enter"&&hits[sel])go(hits[sel]);
});
$("pal").addEventListener("mousedown",e=>{if(e.target===$("pal"))closePal()});

/* ---------- shortcuts, theme, drawer ---------- */
function openKeys(){$("keys").hidden=false}
function closeKeys(){$("keys").hidden=true}
$("keys").addEventListener("mousedown",e=>{if(e.target===$("keys"))closeKeys()});
function toggleTheme(){
  const d=document.documentElement.dataset, dark=(d.theme||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"))==="dark";
  d.theme=dark?"light":"dark";store.set("strata-theme",d.theme);themeIcon();
}
function themeIcon(){const d=document.documentElement.dataset.theme||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");$("theme").replaceChildren(d==="dark"?icon("sun"):svg(O.moon))}
function moveSel(k){
  const rows=[...$("content").querySelectorAll("a.row")];if(!rows.length)return;
  let i=rows.findIndex(r=>r.classList.contains("sel"));rows.forEach(r=>r.classList.remove("sel"));
  i=Math.max(0,Math.min(rows.length-1,i<0?0:i+k));rows[i].classList.add("sel");rows[i].scrollIntoView({block:"nearest"});
}
let chord=0;
document.addEventListener("keydown",e=>{
  const pal=!$("pal").hidden, typing=/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)||e.target.isContentEditable;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();return pal?closePal():openPal()}
  if(e.key==="Escape"){
    if(pal)return closePal();if(!$("keys").hidden)return closeKeys();
    if(document.body.classList.contains("menu"))return document.body.classList.remove("menu");
    if(CUR.tab==="task"&&CUR.id&&!document.querySelector("dialog[open]")){e.preventDefault();return closeTaskPopup()}
    if(typing)return e.target.blur();
    if(document.body.classList.contains("chat-open"))return chatOpen(false);
    return $("content").querySelectorAll(".row.sel").forEach(r=>r.classList.remove("sel"));
  }
  if(pal||typing||e.ctrlKey||e.metaKey)return;
  if(e.altKey){if(e.key==="ArrowLeft"||e.key==="ArrowRight"){const b=$("content").querySelector('[data-nav="'+(e.key==="ArrowLeft"?-1:1)+'"]');if(b&&!b.disabled){e.preventDefault();b.click()}}return}
  const k=e.key.toLowerCase();
  if(chord&&Date.now()-chord<800){chord=0;$("chord").hidden=true;const t=TABS.find(x=>x[2]===k);if(t&&CUR.p){e.preventDefault();location.hash=hashFor(CUR.p,t[0])}return}
  chord=0;$("chord").hidden=true;
  if(k==="g"){chord=Date.now();$("chord").hidden=false;setTimeout(()=>{if(Date.now()-chord>=790)$("chord").hidden=true},820)}
  else if(k==="/"){e.preventDefault();openPal()}
  else if(e.key==="?"){openKeys()}
  else if(k==="j"||e.key==="ArrowDown"&&$("content").querySelector("a.row.sel")){e.preventDefault();moveSel(1)}
  else if(k==="k"||e.key==="ArrowUp"&&$("content").querySelector("a.row.sel")){e.preventDefault();moveSel(-1)}
  else if(e.key==="Enter"){const r=$("content").querySelector("a.row.sel");if(r&&document.activeElement!==r){e.preventDefault();location.hash=r.hash}}
  else if(k==="f"){const b=$("content").querySelector(".fbar button,.fbar input");if(b){e.preventDefault();b.focus()}}
  else if(e.key==="["){const c=document.body.classList.toggle("collapsed");store.set("strata-side",c?"1":"")}
});
const popupClickHashes=new WeakMap();
document.addEventListener("click",e=>{
  const popup=document.querySelector(".tdetail");
  if(popup&&CUR.id&&!popup.contains(e.target)&&!e.target.closest(".tcard")&&!e.composedPath().some(n=>n.tagName==="DIALOG"))popupClickHashes.set(e,location.hash);
},true);
document.addEventListener("click",e=>{
  const popup=document.querySelector(".tdetail");
  const before=popupClickHashes.get(e);
  if(before===undefined||!popup||!CUR.id||popup.contains(e.target)||e.target.closest(".tcard")||e.composedPath().some(n=>n.tagName==="DIALOG"))return;
  const project=CUR.p;
  setTimeout(()=>{const r=route();if(r.p===project&&r.tab==="task"&&r.id)closeTaskPopup(location.hash!==before)},0);
});
if(store.get("strata-side"))document.body.classList.add("collapsed");
const shell=$("shell"), resize=$("side-resize");
const savedWidth=Number(store.get("strata-side-width"));
if(Number.isFinite(savedWidth)&&savedWidth>=180&&savedWidth<=420)shell.style.setProperty("--side-width",savedWidth+"px");
let resizeStart=null;
function setSideWidth(width){
  const value=Math.max(180,Math.min(420,Math.round(width)));
  shell.style.setProperty("--side-width",value+"px");store.set("strata-side-width",String(value));
}
resize.addEventListener("pointerdown",e=>{
  if(e.button!==0||matchMedia("(max-width: 767px)").matches)return;
  e.preventDefault();resizeStart={x:e.clientX,width:$("side").getBoundingClientRect().width};
  document.body.classList.add("resizing");resize.setPointerCapture(e.pointerId);
});
resize.addEventListener("pointermove",e=>{if(resizeStart)setSideWidth(resizeStart.width+e.clientX-resizeStart.x)});
const stopResize=()=>{resizeStart=null;document.body.classList.remove("resizing")};
resize.addEventListener("pointerup",stopResize);resize.addEventListener("pointercancel",stopResize);
resize.addEventListener("keydown",e=>{
  if(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")return;
  e.preventDefault();const width=shell.querySelector("#side").getBoundingClientRect().width;
  setSideWidth(width+(e.key==="ArrowRight"?16:-16));
});

/* ---------- authenticated coding-agent panel ---------- */
const CHAT_STORE="strata-chat-sessions-v1", CHAT_MAX_SESSIONS=4, CHAT_MAX_TIMELINE=150, CHAT_MAX_BLOCK=16000, CHAT_MAX_TIMELINE_CHARS=1000000;
const chatProjectPattern=/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/;
const chatSessionPattern=/^[A-Za-z0-9_-]{1,128}$/;
const chatState={sessions:[],selected:null,polling:false,lastDiffAt:0};
function readChatSessions(){
  try{
    const raw=sessionStorage.getItem(CHAT_STORE), value=raw?JSON.parse(raw):[];
    if(!Array.isArray(value))return [];
    return value.filter(s=>s&&typeof s.project==="string"&&chatProjectPattern.test(s.project)&&typeof s.session_id==="string"&&chatSessionPattern.test(s.session_id)&&
      ["codex","openrouter","omniroute"].includes(s.provider)&&typeof s.closed==="boolean")
      .map(s=>({...s,timeline:[],lastSeq:0,pendingApproval:null,activeTurn:false,restorePending:true,replayIncomplete:false}));
  }catch{return []}
}
function saveChatSessions(){
  try{sessionStorage.setItem(CHAT_STORE,JSON.stringify(chatState.sessions.map(s=>({
    project:s.project,session_id:s.session_id,provider:s.provider,model:s.model||null,
    thread_id:s.thread_id||null,closed:!!s.closed
  }))))}catch{}
}
function pruneClosedChatRefs(needed=0){
  while(chatState.sessions.length+needed>CHAT_MAX_SESSIONS){
    const index=chatState.sessions.findIndex(s=>s.closed);
    if(index<0)return false;
    const [removed]=chatState.sessions.splice(index,1);
    if(chatState.selected===removed.session_id)chatState.selected=null;
  }
  return true;
}
chatState.sessions=readChatSessions();
function chatSession(id=chatState.selected){return chatState.sessions.find(s=>s.session_id===id)||null}
function chatShowError(message){
  let node=$("chat-error");
  if(!node){node=el("div","chat-error");node.id="chat-error";node.setAttribute("role","alert");$("chat-panel").insertBefore(node,$("chat-conversation"))}
  node.textContent=String(message||"Chat request could not be completed");node.hidden=false;
}
function chatClearError(){const node=$("chat-error");if(node){node.hidden=true;node.textContent=""}}
async function chatGet(url){
  for(let attempt=0;attempt<2;attempt++){
    if(!TOK)TOK=(await get("/api/session")).token;
    const response=await fetch(url,{headers:{"X-Strata-Token":TOK}});
    if(response.status===403&&attempt===0){TOK=null;continue}
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const error=new Error(data.error||("HTTP "+response.status));error.status=response.status;throw error}
    return data;
  }
  throw new Error("Strata session token could not be refreshed");
}
function renderChatCards(){
  const box=$("agent-session-cards"), cards=[];
  for(const s of chatState.sessions){
    const b=el("button","agent-session-card"+(s.session_id===chatState.selected?" selected":""));
    b.type="button";b.setAttribute("aria-current",s.session_id===chatState.selected?"true":"false");
    b.append(el("span","agent-session-card-title",s.provider+" · "+(s.model||"default model")),
      el("span","agent-session-card-status",s.closed?"Review available":s.activeTurn?"Working":"Active"),
      el("span","agent-session-card-project",s.project+" · "+s.session_id.slice(0,8)));
    b.title="Open "+s.project+" agent session";
    b.onclick=()=>chatSelectSession(s.session_id);
    cards.push(b);
  }
  box.replaceChildren(...cards);
  box.hidden=!cards.length||!document.body.classList.contains("agent-expanded");
  $("agent-session-count").textContent=String(chatState.sessions.filter(s=>!s.closed).length);
  $("agent-bar-empty").hidden=chatState.sessions.some(s=>!s.closed);
}
function trimChatTimeline(s){
  let total=0, kept=[];
  for(let i=s.timeline.length-1;i>=0&&kept.length<CHAT_MAX_TIMELINE;i--){
    const item=s.timeline[i];let size=0;
    try{size=JSON.stringify(item).length}catch{size=CHAT_MAX_BLOCK}
    if(total+size>CHAT_MAX_TIMELINE_CHARS)break;
    kept.push(item);total+=size;
  }
  s.timeline=kept.reverse();
}
function chatSelectSession(id){
  const s=chatSession(id);if(!s)return;
  chatState.selected=id;
  if(CUR.p!==s.project)location.hash=hashFor(s.project,CUR.tab||"task");
  renderChatCards();renderChatPanel();chatOpen(true);chatRefreshDiff(true);
}
function renderChatPanel(){
  const s=chatSession();
  const events=$("chat-events"), nearBottom=events.scrollHeight-events.scrollTop-events.clientHeight<80;
  if(!s){
    events.replaceChildren(el("p","",CUR.p?"Start a session to work with an AI coding agent.":"Choose a project to start an agent session."));
    $("chat-approval").hidden=true;
    $("chat-message").disabled=true;$("chat-send").disabled=true;
    $("chat-cancel").disabled=true;$("chat-close-session").disabled=true;
    return;
  }
  const timeline=s.timeline.slice(-CHAT_MAX_TIMELINE), nodes=[];
  for(const item of timeline){
    if(item.kind==="user_message"){
      nodes.push(el("article","chat-message chat-message-user",item.text));continue;
    }
    const {type,data={}}=item;
    if(type==="text_delta"){
      nodes.push(el("article","chat-message chat-message-agent",String(data.text||"")));
    }else if(["item_started","tool_completed","tool_output"].includes(type)){
      const label=type==="item_started"?"Agent activity":"Tool activity";
      let content="";try{content=JSON.stringify(data.item||data,null,2)}catch{content="Tool event"}
      if(content.length>12000)content=content.slice(0,12000)+"\n[display truncated]";
      const card=el("article","chat-tool-card");card.append(el("strong","",label),el("pre","",content));nodes.push(card);
    }else if(type==="turn_completed"){
      const status=data.turn&&data.turn.status||"finished";
      nodes.push(el("div","chat-event","Turn "+String(status)));
    }else if(type==="approval_required"){
      nodes.push(el("div","chat-event","Agent approval is required."));
    }else if(type==="error"||type==="protocol_error"||type==="approval_unsupported"||type==="approval_expired"){
      nodes.push(el("div","chat-event",String(data.message||data.reason||type.replaceAll("_"," "))));
    }else if(type==="turn_started"||type==="turn_cancelled"){
      nodes.push(el("div","chat-event",type==="turn_started"?"Agent turn started":"Agent turn cancelled"));
    }
  }
  if(!nodes.length)nodes.push(el("p","","No messages yet. Send a task to begin."));
  events.replaceChildren(...nodes);
  if(nearBottom)events.scrollTop=events.scrollHeight;
  const pending=s.pendingApproval;
  $("chat-approval").hidden=!pending;
  if(pending){
    const request=pending.data.request||{};
    let detail="";try{detail=JSON.stringify(request,null,2)}catch{detail="Approval details unavailable"}
    $("chat-approval-details").textContent=detail.slice(0,48000);
    $("chat-approval-allow").disabled=false;$("chat-approval-deny").disabled=false;
  }
  $("chat-message").disabled=!!s.closed||!!s.restorePending||s.replayIncomplete;
  $("chat-send").disabled=!!s.closed||!!s.restorePending||s.replayIncomplete||s.activeTurn;
  $("chat-cancel").disabled=!!s.closed||!!s.restorePending||!s.activeTurn;
  $("chat-close-session").disabled=!!s.closed;
  if(s.closed){$("chat-message").placeholder="Session closed; worktree remains available for review."}
  else $("chat-message").placeholder="Describe a coding task…";
}
function rememberChatEvent(s,event){
  const d=event&&event.data&&typeof event.data==="object"?event.data:{};
  const type=event&&event.type;
  if(type==="event_truncated")s.replayIncomplete=true;
  if(type==="approval_required")s.pendingApproval=event;
  if(["approval_decided","approval_expired"].includes(type)&&s.pendingApproval&&d.approval_id===s.pendingApproval.data.approval_id)s.pendingApproval=null;
  if(type==="turn_started")s.activeTurn=true;
  if(type==="turn_completed"||type==="turn_cancelled")s.activeTurn=false;
  if(type==="text_delta"&&typeof d.text==="string"){
    d.text=d.text.slice(0,CHAT_MAX_BLOCK);
    const last=s.timeline[s.timeline.length-1];
    if(last&&last.type==="text_delta"){
      const existing=String(last.data.text||"");
      const room=Math.max(0,CHAT_MAX_BLOCK-existing.length);
      if(room)last.data.text=existing+d.text.slice(0,room);
      if(d.text.length>room&&!last.truncated){last.truncated=true;last.data.text=String(last.data.text).slice(0,CHAT_MAX_BLOCK-24)+"\n[display truncated]"}
      return;
    }
  }
  s.timeline.push({seq:event.seq,type,data:d});
  trimChatTimeline(s);
}
function removeChatSession(s){
  chatState.sessions=chatState.sessions.filter(x=>x!==s);
  if(chatState.selected===s.session_id)chatState.selected=null;
  saveChatSessions();renderChatCards();renderChatPanel();
}
async function chatPoll(){
  if(chatState.polling||document.hidden)return;
  chatState.polling=true;
  try{
    for(const s of [...chatState.sessions]){
      if(s.closed)continue;
      const wasRestoring=s.restorePending;
      try{
        const result=await chatGet("/api/chat/events?project="+enc(s.project)+"&session_id="+enc(s.session_id)+"&after="+s.lastSeq);
        for(const event of Array.isArray(result.events)?result.events:[]){
          if(!event||!Number.isSafeInteger(event.seq)||event.seq<=s.lastSeq)continue;
          if(event.seq!==s.lastSeq+1)s.replayIncomplete=true;
          s.lastSeq=event.seq;rememberChatEvent(s,event);
        }
        s.restorePending=false;
        if(s.session_id===chatState.selected){
          if(s.replayIncomplete)chatShowError("Some earlier agent events are no longer available. Start a new session to continue safely.");
          else chatClearError();
          renderChatPanel();
        }
      }catch(error){
        if(!wasRestoring)s.restorePending=false;
        if(error.status===409){removeChatSession(s);continue}
        if(s.session_id===chatState.selected){chatShowError("Could not load agent events. "+error.message);renderChatPanel()}
      }
    }
    await chatRefreshDiff(false);
  }finally{chatState.polling=false}
}
async function chatRefreshDiff(force){
  const s=chatSession();if(!s)return;
  const now=Date.now();if(!force&&now-chatState.lastDiffAt<3000)return;
  chatState.lastDiffAt=now;
  try{
    const result=await chatGet("/api/chat/diff?project="+enc(s.project)+"&session_id="+enc(s.session_id));
    if(chatSession()!==s)return;
    $("chat-diff-status").textContent=result.status||"";
    $("chat-diff").textContent=result.diff||"";
    chatClearError();
  }catch(error){if(error.status===409)removeChatSession(s);else if(s.session_id===chatState.selected)chatShowError("Could not load worktree review. "+error.message)}
}
function safeCodexLoginUrl(value){
  try{const u=new URL(value);return u.protocol==="https:"&&u.hostname==="auth.openai.com"&&["","443"].includes(u.port)&&!u.username&&!u.password&&!u.hash?u.href:null}catch{return null}
}
async function chatCheckAuth(){
  const provider=$("chat-provider").value;
  try{
    const state=await chatGet("/api/chat/auth?provider="+enc(provider));
    if(provider!==$("chat-provider").value)return;
    chatClearError();
    const messages={account_present:"Codex account connected",provider_configured:"Provider configured · inference not yet verified",
      provider_ready:"Provider configured · inference not yet verified",login_required:"Codex sign-in required",
      configuration_required:"Provider configuration required",unavailable:"Authentication status unavailable"};
    $("chat-auth-state").textContent=messages[state.status]||"Authentication status: "+String(state.status||"unknown");
    $("chat-auth-state").dataset.state=String(state.status||"unavailable");
    const area=$("chat-login-area");area.replaceChildren();
    if(provider==="codex"&&state.status==="login_required"){
      const start=el("button","","Get sign-in link");start.type="button";start.disabled=!chatSession()||chatSession().closed;
      const help=el("p","chat-help",chatSession()?"A sign-in link will appear here for you to open.":"Start a Codex session first, then request a sign-in link.");
      const anchor=el("a","");anchor.id="chat-login-link";anchor.target="_blank";anchor.rel="noopener noreferrer";anchor.textContent="Open OpenAI sign-in";anchor.hidden=true;
      start.onclick=async()=>{
        const session=chatSession();if(!session)return;
        start.disabled=true;chatClearError();
        try{const result=await api("/api/chat",{op:"login",project:session.project,session_id:session.session_id});
          const url=safeCodexLoginUrl(result.url);if(!url)throw new Error("Codex returned an unsupported sign-in link");
          anchor.href=url;anchor.hidden=false;help.textContent="Open the link to finish signing in.";
        }catch(error){chatShowError(error.message)}finally{start.disabled=!chatSession()||chatSession().closed}
      };
      area.append(start,anchor,help);area.hidden=false;
    }else if(provider!=="codex"&&state.status==="configuration_required"){
      area.append(el("p","chat-help","Configure this provider's key and base URL in the Strata server environment."));area.hidden=false;
    }else{area.hidden=true}
  }catch(error){
    $("chat-auth-state").textContent="Authentication status unavailable";
    $("chat-auth-state").dataset.state="unavailable";
    if(error.status!==409)chatShowError("Could not check provider status. "+error.message);
  }
}
function chatOpen(open){
  const panel=$("chat-panel"),button=$("chat-toggle");
  panel.hidden=!open;panel.setAttribute("aria-hidden",String(!open));
  button.setAttribute("aria-expanded",String(open));document.body.classList.toggle("chat-open",open);
  if(open){chatCheckAuth();renderChatPanel();}
}
async function chatStartSession(){
  const project=CUR.p;if(!project){chatShowError("Choose a project before starting a session.");return}
  const button=$("chat-new-session"),provider=$("chat-provider").value,model=$("chat-model").value.trim();
  button.disabled=true;chatClearError();
  try{
    const liveCount=chatState.sessions.filter(s=>!s.closed).length;
    if(liveCount>=CHAT_MAX_SESSIONS)throw new Error("Close a live session before starting another.");
    if(!pruneClosedChatRefs(1))throw new Error("Close a live session before starting another.");
    const result=await api("/api/chat",{op:"start",project,provider,...(model?{model}:{})});
    const session={project,session_id:result.session_id,thread_id:result.thread_id||null,provider,model:model||null,
      closed:false,timeline:[],lastSeq:0,pendingApproval:null,activeTurn:false,restorePending:false,replayIncomplete:false};
    if(!chatSession(session.session_id))chatState.sessions.push(session);
    chatState.selected=session.session_id;
    saveChatSessions();renderChatCards();renderChatPanel();chatOpen(true);await chatPoll();
  }catch(error){chatShowError(error.message)}finally{button.disabled=false}
}
async function chatSend(e){
  e.preventDefault();const s=chatSession(),input=$("chat-message"),message=input.value.trim();
  if(!s||s.closed||s.activeTurn||!message)return;
  const userEntry={kind:"user_message",text:message};s.timeline.push(userEntry);trimChatTimeline(s);
  s.activeTurn=true;renderChatPanel();chatClearError();
  try{await api("/api/chat",{op:"turn",project:s.project,session_id:s.session_id,message});input.value="";}
  catch(error){s.activeTurn=false;s.timeline=s.timeline.filter(item=>item!==userEntry);input.value=message;chatShowError(error.message);renderChatPanel()}
}
async function chatCancelTurn(){
  const s=chatSession();if(!s||s.closed||!s.activeTurn)return;
  try{await api("/api/chat",{op:"cancel",project:s.project,session_id:s.session_id})}
  catch(error){chatShowError(error.message)}
}
async function chatCloseSession(){
  const s=chatSession();if(!s||s.closed)return;
    try{await api("/api/chat",{op:"close",project:s.project,session_id:s.session_id});s.closed=true;s.activeTurn=false;s.pendingApproval=null;saveChatSessions();renderChatCards();renderChatPanel();await chatRefreshDiff(true)}
  catch(error){chatShowError(error.message)}
}
async function chatDecide(allow){
  const s=chatSession(),pending=s&&s.pendingApproval;if(!s||!pending)return;
  $("chat-approval-allow").disabled=true;$("chat-approval-deny").disabled=true;
  try{const result=await api("/api/chat",{op:"decide",project:s.project,session_id:s.session_id,approval_id:pending.data.approval_id,allow});
    if(result.accepted!==true)throw new Error("Approval was no longer pending; refresh agent events.");
    s.pendingApproval=null;renderChatPanel()}
  catch(error){chatShowError(error.message);$("chat-approval-allow").disabled=false;$("chat-approval-deny").disabled=false}
}
function chatProjectChanged(){
  if(!CUR.p){chatState.selected=null}
  else if(!chatSession()||chatSession().project!==CUR.p){
    const match=[...chatState.sessions].reverse().find(s=>s.project===CUR.p);
    chatState.selected=match?match.session_id:null;
  }
  renderChatCards();renderChatPanel();if(document.body.classList.contains("chat-open"))chatCheckAuth();
  if(chatSession()&&!chatSession().closed)chatPoll();
}
$("chat-toggle").onclick=()=>chatOpen($("chat-panel").hidden);
$("chat-close").onclick=()=>chatOpen(false);
$("chat-new-session").onclick=chatStartSession;
$("chat-provider").addEventListener("change",chatCheckAuth);
$("chat-composer").addEventListener("submit",chatSend);
$("chat-cancel").onclick=chatCancelTurn;$("chat-close-session").onclick=chatCloseSession;
$("chat-approval-allow").onclick=()=>chatDecide(true);$("chat-approval-deny").onclick=()=>chatDecide(false);
$("agent-bar-toggle").onclick=()=>{
  const expanded=document.body.classList.toggle("agent-expanded");
  $("agent-bar-toggle").setAttribute("aria-expanded",String(expanded));
  $("agent-session-cards").hidden=!expanded||chatState.sessions.length===0;
};
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&document.body.classList.contains("chat-open"))chatCheckAuth()});
chatState.selected=chatState.sessions.at(-1)?.session_id||null;
renderChatCards();renderChatPanel();
setInterval(chatPoll,1200);
$("moon").append(svg(O.moon));
$("band").append(svg(contours(7,480,120,6)));
themeIcon();
$("padd").append(icon("plus"));$("padd").onclick=addProject;
$("theme").onclick=toggleTheme;
$("help").onclick=openKeys;
$("searchbtn").onclick=openPal;
$("menu").onclick=()=>{document.body.classList.toggle("menu");document.body.classList.remove("collapsed")};
$("scrim").onclick=()=>document.body.classList.remove("menu");
addEventListener("hashchange",()=>render());
render();
/* live: redraw the current tab when /api/version moves (CLI/MCP write, docs edit). C4 and doc readers poll on their own. */
{let ver=null;const live=async()=>{
  if(document.hidden)return;
  try{const v=(await get("/api/version")).version;if(ver!==null&&v!==ver){
    const a=document.activeElement,busy=a&&/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)||document.querySelector("dialog[open]");
    if(busy||CUR.tab==="c4"||(CUR.tab==="docs"&&CUR.id))return;  // retry next tick, ver stays old
    await render(true)}ver=v}catch{}};
 setInterval(live,2000);document.addEventListener("visibilitychange",live)}
