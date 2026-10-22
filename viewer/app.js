"use strict";
// App shell. Read-only. All text goes through textContent (el() from page.js); never assigns markup.
// el, get, enc and renderPage come from page.js (STRATA_SHELL makes it skip its own routing).
const $=id=>document.getElementById(id);
const TABS=[["overview","Overview","o"],["task","Task","t"],["roadmap","Roadmap","m"],["issue","Issue","i"],["pages","Discussion","p"],["docs","Docs","r"],["c4","Architecture","a"],["audit","Log","l"]];
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
const IC={overview:'<path d="M2.5 13.5h11M4 11V7M8 11V3.5M12 11V6"/>',task:'<circle cx="8" cy="8" r="5.5"/><path d="M5.6 8.1l1.6 1.6 3.2-3.4"/>',
  issue:'<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.5M8 10.8v.2"/>',
  pages:'<path d="M3 3.5h10v7H7l-3 2.5v-2.5H3z"/>',docs:'<path d="M4 2.5h5.5L12 5v8.5H4z"/><path d="M6 8h4M6 10.5h4"/>',
  c4:'<rect x="2.5" y="2.5" width="4" height="4" rx="1"/><rect x="9.5" y="9.5" width="4" height="4" rx="1"/><path d="M6.5 4.5h3a2 2 0 0 1 2 2v3"/>',
  roadmap:'<path d="M3.5 14V2.5M3.5 3h8.5l-1.7 2.8L12 8.5H3.5"/>',audit:'<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3l2 1.5"/>',folder:'<path d="M2.5 4.5h4l1.5 1.5h5.5v6.5h-11z"/>',proj:'<path d="M2 12.5l3.5-6 2.5 3.5 2-2.5 4 5z"/>',
  chev:'<path d="M6 4l4 4-4 4"/>',prev:'<path d="M10 4L6 8l4 4"/>',reload:'<path d="M13 8a5 5 0 1 1-1.5-3.5M13 3v2.5h-2.5"/>',
  ext:'<path d="M9 3h4v4M13 3L7.5 8.5M11 9.5V13H3V5h3.5"/>',copy:'<rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.5"/><path d="M10.5 5.5V3H3v7.5h2.5"/>',
  sun:'<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>'};
const icon=k=>svg(S("0 0 16 16",IC[k],'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"'));
const orn=(cls,s)=>{const d=el("div",cls);d.setAttribute("aria-hidden","true");d.append(svg(s));return d};
function empty(title,hint,code){
  const d=el("div","empty");d.append(orn("dragon",O.dragon),el("b","",title));
  if(hint){const p=el("p","muted",hint);if(code)p.append(" ",el("code","",code));d.append(p)}
  return d;
}

/* ---------- routing ---------- */
const hashFor=(p,tab,id)=>"#/p/"+enc(p)+"/"+(tab||"overview")+(id!=null&&id!==""?"/"+String(id).split("/").map(enc).join("/"):"");
function link(text,href,cls){const a=el("a",cls||"",text);a.href=href;return a}
const hq=()=>{const i=location.hash.indexOf("?");return new URLSearchParams(i<0?"":location.hash.slice(i+1))};
function route(){
  const i=location.hash.indexOf("?"), raw=i<0?location.hash:location.hash.slice(0,i);
  const h=raw.startsWith("#/")?raw.slice(2).split("/").map(decodeURIComponent):[];
  if(h[0]==="p"&&byId[h[1]]) return {p:h[1],tab:TAB_LABEL[h[2]]?h[2]:"overview",id:h.slice(3).join("/")};
  return {p:(PROJ.find(x=>!x.parent)||PROJ[0]||{}).id,tab:"overview",id:""};
}
const total=o=>Object.values(o||{}).reduce((a,b)=>a+b,0);
function counts(p){return {task:total(p.tasks),issue:p.issues_open,pages:p.pages,docs:p.docs}}
let CUR={};

/* ---------- sidebar + breadcrumb ---------- */
function side(r){
  // flat list of real projects; groups (anything that is some project's parent) stay reachable via breadcrumb/palette
  const leaf=PROJ.filter(p=>!PROJ.some(x=>x.parent===p.id));
  $("tree").replaceChildren(...leaf.map(p=>{
    const a=link("",hashFor(p.id,"overview"),"it"+(p.id===r.p?" on":""));
    if(p.id===r.p)a.setAttribute("aria-current","page");
    a.append(icon("proj"),el("span","l",p.name));return a}));
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
  chain.forEach((p,i)=>{if(i)parts.push(sep());parts.push(link(p.name,hashFor(p.id,"overview")))});
  if(r.p){parts.push(sep(),r.tab==="overview"&&!r.id?el("b","",TAB_LABEL.overview):link(TAB_LABEL[r.tab],hashFor(r.p,r.tab)));
    if(r.id)parts.push(sep(),el("b","",r.id.split("/").pop()))}
  $("crumbs").replaceChildren(...parts);
}

async function render(keep){
  const my=++token;
  document.body.classList.remove("menu");
  try{PROJ=await get("/api/projects");byId=Object.fromEntries(PROJ.map(p=>[p.id,p]))}catch(e){return $("content").replaceChildren(el("p","err",e.message))}
  if(my!==token)return;
  const r=route();CUR=r;side(r);crumbs(r);
  const box=el("div");
  try{
    if(!r.p) box.append(empty("No projects yet","Create with:","strata.py project add ID --name ..."));
    else await VIEW[r.tab](box,r.p,r.id);
  }catch(e){box.append(el("p","err",e.message))}
  if(my!==token)return;
  document.title=(r.p?byId[r.p].name+" · "+TAB_LABEL[r.tab]+" · ":"")+"Strata";
  const rd=box.querySelector(":scope>.reader");
  if(!rd&&!box.className)box.className="page"+(r.tab==="task"||r.tab==="roadmap"?" wide":"");
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

const PHASES=["Explore","Design","Build","Harden","Release"];
const PHASE_DESC=["Ideas and discussion; nothing committed yet.","Diagram and research.","Tasks being written and tested.","Tests, review, security, polish.","Shipped and in use."];

const VIEW={
  async overview(box,p){
    const [tasks,issues,pages,docs]=await Promise.all([get("/api/items?kind=task&project="+enc(p)),get("/api/items?kind=issue&project="+enc(p)),
      get("/api/pages?project="+enc(p)),get("/api/docs?project="+enc(p))]);
    const pr=byId[p], done=pr.tasks.done||0, doing=pr.tasks.doing||0, all=total(pr.tasks), pct=all?Math.round(100*done/all):0;
    const hero=el("div","hero");// full-bleed hero art behind the content column: traced mountains anchored right + fitted waves edge to edge
    const bg=el("div","herobg");bg.setAttribute("aria-hidden","true");const mt=el("div","mtn"), wv=el("div","waves");bg.append(wv,mt);box.append(bg);
    heroArt("mountains").then(x=>mt.append(x.cloneNode(true))).catch(()=>{});
    heroArt("mountains-waves").then(x=>wv.append(x.cloneNode(true))).catch(()=>{});
    hero.append(el("h1","foil",pr.name));
    if(pr.description)hero.append(el("p","",pr.description));
    const props=el("div","props");
    [["Status",pr.status||"—"],["Task",all],["Open issues",pr.issues_open],["Docs",pr.docs],["Updated",rel(pr.last_update)||"never"]]
      .forEach(([k,v])=>{const s=el("span","",k+" ");s.append(el("b","",v));props.append(s)});
    const prog=el("div","prog"), bar=el("div","bar"), a=el("i","b-done"), b=el("i","b-doing");
    a.style.width=(all?100*done/all:0)+"%";b.style.width=(all?100*doing/all:0)+"%";bar.append(a,b);
    prog.append(bar,el("span","pct",pct+"%"));
    const stats=el("div","props");[["Scope",all],["In progress",doing],["Done",done]].forEach(([k,v])=>{const s=el("span","",k+" ");s.append(el("b","",v));stats.append(s)});
    hero.append(props,prog,stats);box.append(hero);
    // pr.phase will come from `project set --phase` later; preview: #...?phase=N, default 3
    const hp=+new URLSearchParams(location.hash.split("?")[1]||"").get("phase");
    const cur=[pr.phase,hp].find(n=>Number.isInteger(n)&&n>=1&&n<=5)||3;
    const mp=ltMapBox(PHASES.map((label,i)=>({n:i+1,label,state:i+1<cur?"done":i+1===cur?"doing":"todo",gate:null,cur})),{},null,null,null);
    mp.classList.add("ov-map");box.append(mp);
    const subs=PROJ.filter(x=>x.parent===p);
    if(subs.length){const g=el("div","grid");subs.forEach(s=>{
      const c=link("",hashFor(s.id,"overview"),"card edge pcard");c.append(orn("topo",contours(hash(s.id))),el("b","",s.name),
        el("span","",total(s.tasks)+" task · "+s.issues_open+" open issues · "+s.docs+" docs"));g.append(c)});box.append(g)}
    const open=issues.filter(x=>x.status!=="done"&&x.status!=="rejected");
    const recent=[...pages.map(x=>[null,x.title,hashFor(p,"pages",x.slug),x.updated_at]),
      ...docs.filter(x=>x.status!=="missing").map(x=>[x.status,x.title,hashFor(p,"docs",x.path),x.updated_at])]
      .sort((a,b)=>(b[3]||"").localeCompare(a[3]||"")).slice(0,6);
    const tone=x=>["done","approved","accepted"].includes(x)?"done":["doing","review","open"].includes(x)?"doing":"todo";
    const st=x=>el("span","st "+tone(x),LBL[x]||x||"");
    const crit=(t,h,meta,s)=>{const r=el("div","crit");const w=el("span","what");w.append(link(t,h));r.append(w,el("span","who",meta||""),st(s));return r};
    const lt=el("div","lt"), det=el("div","detail"), L=el("section"), R=el("section");
    L.append(el("span","lab","Phase "+cur+" · "+PHASES[cur-1]),el("h3","",PHASES[cur-1]));
    const sr=el("div","state");sr.append(el("span","st doing","In progress"));
    L.append(sr,el("p","goal",PHASE_DESC[cur-1]),el("hr","rule"),el("span","lab","Tasks"));
    const act=["doing","review","approved"].flatMap(k=>tasks.filter(x=>x.status===k)).slice(0,8);
    if(act.length){const ul=el("ul","blocks");act.forEach(x=>{const li=el("li");li.append(link("#"+x.id+" "+x.title,hashFor(p,"task",x.id)),st(x.status));ul.append(li)});L.append(ul)}
    else L.append(el("p","empty","No active tasks"));
    const gd=el("div","gate");gd.append(el("span","lab","Open issues"),el("div","line",open.length?open.length+" open issues":"No open issues"));
    if(open.length){const ul=el("ul","gmiss");open.slice(0,8).forEach(x=>{const li=el("li"),sp=el("span");
      sp.append(link("#"+x.id+" "+x.title,hashFor(p,"issue",x.id))," ",el("span","who","· "+(x.priority||"")));li.append(sp);ul.append(li)});gd.append(ul)}
    R.append(gd);
    [["Recently updated",recent.map(x=>crit(x[1],x[2],rel(x[3]),x[0]||"open"))]].forEach(([k,rows])=>{
      if(!rows.length)return;const grp=el("div","grp");grp.append(el("span","lab",k),...rows);R.append(el("hr","rule"),grp)});
    det.append(L,R);lt.append(det);box.append(lt);
  },
  task:(box,p,id)=>boardView(box,p,id),
  roadmap:(box,p,id)=>roadmapView(box,p,id),
  issue:(box,p,id)=>itemView(box,p,id,"issue"),
  async pages(box,p,id){
    if(id){
      box.className="page narrow";
      const root=el("article");root.id="pg";box.append(root);
      renderPage(await get("/api/page/"+enc(p)+"/"+enc(id)),root);
      return;
    }
    const ps=(await get("/api/pages?project="+enc(p))).filter(x=>x.kind!=="plan"); // plan pages live under Roadmap
    box.append(head("Discussion",ps.length));
    if(!ps.length)return box.append(empty("No pages yet","Pages are written via the strata CLI or MCP."));
    ps.forEach(x=>{const a=link("",hashFor(p,"pages",x.slug),"row pg");a.append(icon("pages"),el("span","t",x.title),el("span","kind",x.kind),dateCell(x.updated_at));box.append(a)});
  },
  async docs(box,p,id){
    const docs=await get("/api/docs?project="+enc(p));
    docs.forEach(x=>{try{x.code=JSON.parse(x.code||"[]")||[]}catch{x.code=[]}});
    if(id)return docReader(box,p,id,docs);
    if(!docs.length){box.append(head("Contents",0));return box.append(empty("No docs yet","Write a YAML file into the project's docs_dir, e.g.","docs/strata/c4.yaml"))}
    toc(box,p,docs.filter(x=>x.status!=="missing"),docs.filter(x=>x.status==="missing").length);
  },
  async c4(box,p,id){
    const r=el("div","reader c4"), f=el("iframe","frame c4");
    f.src="/c4?project="+enc(p)+"&embed=1"+(id?"#"+enc(id):"");f.title="C4 architecture";r.append(f);box.append(r);
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
      try{s.append(b.type==="c4"?c4(b,p):b.type==="query"?query(b):b.type==="diagram"||b.type==="statemachine"||b.type==="roadmap"?({diagram,statemachine,roadmap})[b.type](b,linkFor):R[b.type]?R[b.type](b):el("p","err","Unknown block type: "+b.type))}
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

/* ---------- task board (read-only): status columns, detail pane. Filters live in the hash query. ---------- */
const COLS=["proposed","approved","doing","review"], FOLD=["done","open","rejected"];
const PRI_TAG={p0:"P0",p1:"P1",p2:"P2",p3:"P3"};
const BKIND=["task","issue","step"];
const DAY=864e5;
function tag(text,cls,title){const t=el("span","tag"+(cls?" "+cls:""),text);if(title)t.title=title;return t}
const acN=x=>((x.spec&&x.spec.acceptance)||[]).length;
function claimAge(x){return x.status==="doing"&&x.claimed_at?rel(x.claimed_at):""}
const stale=x=>x.status==="doing"&&x.claimed_at&&Date.now()-Date.parse(x.claimed_at)>DAY;
function boardHref(p,id,qs){const s=qs.toString();return hashFor(p,"task",id)+(s?"?"+s:"")}
function itemCard(x,p,qs,sel,blockedBy){
  const a=link("",boardHref(p,x.id,qs),"tcard"+(String(x.id)===sel?" sel":"")+(x.off_roadmap?" offrm":""));
  const m=el("span","mono","#"+x.id+(x.kind!=="task"?" "+x.kind:"")+(x.owner?" · "+x.owner:"")+(claimAge(x)?" · "+claimAge(x):""));
  const row=el("span","trow");
  if(x.priority)row.append(tag(PRI_TAG[String(x.priority).toLowerCase()]||x.priority,"pri-"+String(x.priority).toLowerCase()));
  if(x.phase!=null)row.append(tag("P"+x.phase,x.off_roadmap?"offrm":"phase",x.off_roadmap?"Phase "+x.phase+", outside the roadmap's current phase":"Phase "+x.phase+" of the roadmap"));
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
  const go=patch=>{const n=new URLSearchParams(qs);Object.entries(patch).forEach(([k,v])=>v?n.set(k,v):n.delete(k));location.hash=boardHref(p,id,n)};
  const all=await get("/api/items?project="+enc(p));
  const owners=[...new Set(all.map(x=>x.owner).filter(Boolean))].sort();
  const needle=f.q.toLowerCase();
  const vis=all.filter(x=>(!f.kind||x.kind===f.kind)&&(!f.status||x.status===f.status)&&(!f.owner||x.owner===f.owner)&&(!needle||(x.title+" #"+x.id).toLowerCase().includes(needle)));
  box.append(head("Board",vis.length));
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
    h.append(statusIcon(st),st+" · "+its.length);col.append(h);
    const c=el("div","cards");its.forEach(x=>c.append(mk(x)));if(!its.length)c.append(el("p","muted tnone","Empty"));col.append(c);board.append(col);
  });
  const folds=el("div","tfolds");
  FOLD.forEach(st=>{const its=vis.filter(x=>x.status===st);if(its.length)folds.append(fold(st,its,mk))});
  const left=el("div","tleft");left.append(board);if(folds.children.length)left.append(folds);
  const pane=el("aside","tdetail");
  main.append(left,pane);box.append(main);
  if(!all.length)box.prepend(empty("No work items yet","Add via CLI:","strata.py item add --project "+p+" --kind task --title ..."));
  if(!id)return pane.append(el("p","muted","Select an item to see details."));
  const d=(await get("/api/items?id="+enc(id)))[0];
  if(!d||d.project!==p)return pane.append(el("p","err","Not found #"+id));
  detailPane(pane,d,p,qs);
}
function dlink(x,p,qs){const a=link("#"+x.id+" "+x.title,boardHref(p,x.id,qs),"dep");a.append(" ",pill(x.status));return a}
function section(c,title,node){if(!node)return;const s=el("div","dsec");s.append(el("h4","",title),node);c.append(s)}
function detailPane(c,d,p,qs){
  const sp=d.spec||{}, ac=sp.acceptance||[];
  const top=el("div");top.append(el("span","mono","#"+d.id+" "+d.kind+" · "+d.status+(d.owner?" · owner "+d.owner:"")+(d.claimed_at?" · claim "+ago(d.claimed_at).slice(5):"")),el("h2","",d.title));
  const pr=el("div","props");pr.append(pill(d.status));
  if(d.priority){const s=el("span");s.append(priIcon(d.priority)," "+d.priority);s.style.display="inline-flex";s.style.gap="4px";pr.append(s)}
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

async function itemView(box,p,id,kind){
  const rows=await get("/api/items?kind="+kind+"&project="+enc(p));
  box.append(head(kind==="task"?"Task":"Issue",rows.length));
  if(id){
    const d=(await get("/api/items?id="+enc(id)))[0];
    if(d&&d.project===p){
      const c=el("div","detail");c.append(el("h2","","#"+d.id+" "+d.title));
      const pr=el("div","props");pr.append(pill(d.status));
      if(d.priority){const s=el("span");s.append(priIcon(d.priority));s.append(" "+d.priority);s.style.display="inline-flex";s.style.gap="4px";pr.append(s)}
      if(d.owner)pr.append(el("span","",d.owner));pr.append(el("span","",ago(d.updated_at||d.created_at)));
      c.append(pr,el("p","body",d.body||"(no description)"));box.append(c);
    }else box.append(el("p","err","Not found #"+id));
  }
  if(!rows.length)return box.append(empty("No "+kind+" yet","Add via CLI:","strata.py item add --project "+p+" --kind "+kind+" --title ..."));
  let cur="";
  const chips=el("div"), body=el("div"), draw=()=>{
    chips.replaceChildren(fbar([[ST_ITEM,cur,v=>{cur=v;draw()}]]));
    const vis=rows.filter(x=>!cur||x.status===cur);
    if(!vis.length){const e=empty("No "+kind+" with status "+cur);const c=el("button","","Clear filter");c.onclick=()=>{cur="";draw()};e.append(c);return body.replaceChildren(e)}
    body.replaceChildren(...grouped(vis,x=>x.status,["doing","open","approved","proposed","done","rejected"],(k,h)=>h.append(statusIcon(k),k),x=>{
      const a=link("",hashFor(p,kind,x.id),"row"+(String(x.id)===id?" sel":""));
      a.append(priIcon(x.priority),el("span","id",(kind==="task"?"T-":"I-")+x.id),statusIcon(x.status),el("span","t",x.title),el("span","x",x.owner||""),dateCell(x.updated_at||x.created_at));return a}));
  };
  draw();box.append(chips,body);
}

/* ---------- Roadmap (read-only): Astra mountain trail + detail from /api/roadmap. Data only reaches DOM through textContent. ---------- */
const LT_ST={approved:"Not started",doing:"In progress",review:"Awaiting check",done:"Passed",blocked:"Blocked"};
const LBL={done:"done",doing:"in progress",todo:"upcoming"};
const LT_WHO={machine:"machine",reviewer:"reviewer",user:"user"};
const ltPct=(n,m)=>m?Math.round(100*n/m):0;

function ltFormat(parent,text){
  const re=/\(([^)]*[-.\/][^)]*)\)|`([^`]+)`/g;let i=0,m;const s=String(text==null?"":text);
  while((m=re.exec(s))){
    if(m.index>i)parent.append(s.slice(i,m.index));
    if(m[1]!=null){parent.append("(");parent.append(el("code","",m[1]));parent.append(")")}
    else if(m[2]!=null){parent.append(el("code","",m[2]))}
    i=re.lastIndex;
  }
  if(i<s.length)parent.append(s.slice(i));
}

function ltCamps(d){
  const phs=[];
  if(d.phases&&d.phases.length){
    d.phases.forEach(ph=>phs.push({n:ph.n,title:ph.title,anchor:String(ph.n)}));
  }else if(d.plan&&d.plan.sections){
    d.plan.sections.forEach(s=>(s.phases||[]).forEach(ph=>phs.push({n:ph.n,title:ph.title,anchor:ph.anchor||String(ph.n)})));
  }
  const gs=(d.gates||[]).filter(g=>(g.phases||[]).length), passed=n=>gs.some(g=>g.phases.includes(n)&&g.status==="done");
  const cur=d.current_phase!=null?d.current_phase:(phs.find(ph=>!passed(ph.n))||{}).n;
  return phs.map(ph=>{
    const g=gs.find(g=>Math.max(...g.phases)===ph.n), gOpen=g&&g.phases.includes(cur);
    return {
      n:ph.n,anchor:ph.anchor||String(ph.n),label:String(ph.title||"Phase "+ph.n).replace(/^Phase\s*\d+\s*[·:.-]\s*/i,""),
      state:passed(ph.n)?"done":ph.n===cur?"doing":"todo",
      gate:g&&{key:g.key,state:g.status==="done"?"done":gOpen?"open":"todo"},
      cur
    };
  });
}

function ltMapBox(camps,d,root,sel,pick){
  const cur=camps[0].cur, box=el("div","lt-mapbox"), sc=el("div","lt-mapscroll");
  let curPct=0;
  if(d.progress&&d.progress.phases){
    const pp=d.progress.phases.find(x=>x.phase===cur);
    if(pp&&pp.total>0)curPct=ltPct(pp.done,pp.total);
  }
  if(!curPct){
    const curDef=(d.phases||[]).find(x=>x.n===cur);
    if(curDef&&curDef.blocks&&curDef.blocks.length){
      const tot=curDef.blocks.reduce((acc,b)=>acc+(b.total||0),0), dn=curDef.blocks.reduce((acc,b)=>acc+(b.done||0),0);
      if(tot>0)curPct=Math.round(100*dn/tot);
    }
  }
  if(!curPct&&d.steps){
    const curSteps=d.steps.filter(st=>st.phase===cur);
    if(curSteps.length>0)curPct=Math.round(100*curSteps.filter(st=>st.status==="done"||st.state==="done").length/curSteps.length);
  }
  const opt={cur,sel,pct:d.progress||d.phases||d.steps?curPct:null,summit:"Summit · release",label:"Roadmap map: each camp is a phase, click for details",onPick:pick};
  let w=0, raf=0;const ro=new ResizeObserver(()=>{if(!box.isConnected)return ro.disconnect();cancelAnimationFrame(raf);raf=requestAnimationFrame(()=>{
    const nw=box.clientWidth;if(!nw||nw===w)return;w=nw;const f=sc.contains(document.activeElement)&&document.activeElement.getAttribute("aria-label");
    sc.replaceChildren(astraMap(camps,{...opt,width:nw}));if(f){const c=[...sc.querySelectorAll(".camp")].find(x=>x.getAttribute("aria-label")===f);if(c)c.focus({preventScroll:true})}})});
  ro.observe(box);box.append(sc);return box;
}

function renderDetail(detail,off,s,d,p,camps){
  if(s==null&&camps.length)s=camps[0].n;
  const def=(d.phases||[]).find(x=>x.n===s);
  const planPh=d.plan&&d.plan.sections?d.plan.sections.flatMap(sec=>sec.phases||[]).find(x=>x.n===s):null;
  const camp=camps.find(c=>c.n===s)||{};
  const name=(def&&def.title)||(planPh&&planPh.title)||("Phase "+s);
  const state=camp.state||"todo";
  const goal=(def&&def.goal)||(planPh&&(planPh.intro||planPh.goal))||"";
  const stepKeys=planPh&&planPh.steps?planPh.steps:[];
  const phaseSteps=(d.steps||[]).filter(st=>st.phase===s);
  if(stepKeys.length){
    phaseSteps.sort((a,b)=>{
      const ia=stepKeys.indexOf(a.key), ib=stepKeys.indexOf(b.key);
      if(ia>=0&&ib>=0)return ia-ib;
      return (a.key||"").localeCompare(b.key||"");
    });
  }
  const blocks=(def&&def.blocks)?def.blocks:[];

  let pct=0;
  if(state==="done"){
    pct=100;
  }else if(d.progress&&d.progress.phases){
    const pp=d.progress.phases.find(x=>x.phase===s);
    if(pp&&pp.total>0)pct=ltPct(pp.done,pp.total);
  }
  if(!pct&&blocks.length){
    const tot=blocks.reduce((acc,b)=>acc+(b.total||0),0), dn=blocks.reduce((acc,b)=>acc+(b.done||0),0);
    if(tot>0)pct=Math.round(100*dn/tot);
  }
  if(!pct&&phaseSteps.length){
    const dn=phaseSteps.filter(st=>st.status==="done"||st.state==="done").length;
    pct=Math.round(100*dn/phaseSteps.length);
  }

  const left=el("section");
  left.append(el("span","lab","Camp "+s+" · phase "+s));
  left.append(el("h3","",name));

  const stateRow=el("div","state");
  stateRow.append(el("span","st "+state,LBL[state]||state));
  if(state==="doing")stateRow.append(el("span","pct",pct+"%"));
  left.append(stateRow);

  if(goal)left.append(el("p","goal",goal));

  if(blocks.length){
    left.append(el("hr","rule"));
    left.append(el("span","lab","Blocks to do"));
    const ul=el("ul","blocks");
    blocks.forEach(b=>{
      const li=el("li");
      const isDone=b.done!=null&&b.total!=null&&b.total>0&&b.done>=b.total;
      const bPct=isDone?100:(b.total>0?Math.round(100*b.done/b.total):0);
      const cntText=b.total>0?(isDone?"done":`${b.done}/${b.total}`):(b.done?"done":"no tasks");
      const objEl=b.object?link(b.object,hashFor(p,"c4",b.object)):el("span","",b.object||"");
      const cntEl=el("span","cnt",cntText);
      const thread=el("span","thread");thread.setAttribute("aria-hidden","true");
      const thI=el("i",isDone?"dn":bPct===0?"zero":"");thI.style.width=bPct+"%";thread.append(thI);
      li.append(objEl,cntEl,thread);
      if(b.note||b.pulled_from!=null){
        li.append(el("span","note",b.note||("Pulled from phase "+b.pulled_from)));
      }
      ul.append(li);
    });
    left.append(ul);
  }

  if(phaseSteps.length){
    left.append(el("hr","rule"));
    const det=el("details");det.open=true;
    det.append(el("summary","lab","Phase steps · "+phaseSteps.length));
    const ul=el("ul","steps");
    phaseSteps.forEach(st=>{
      const li=el("li");
      li.append(el("span","id",st.key||String(st.id)));
      li.append(link(st.title,hashFor(p,"task",st.id)));
      const stState=st.state||st.status;
      li.append(el("span","st "+stState,LBL[stState]||LT_ST[stState]||stState));
      ul.append(li);
    });
    det.append(ul);left.append(det);
  }

  const right=el("section");
  const gateKey=(camp.gate&&camp.gate.key)||(def&&def.gate&&def.gate.key)||("G"+s);
  const gateObj=(d.gates||[]).find(g=>g.key===gateKey);
  const gs=camp.gate?camp.gate.state:(gateObj&&gateObj.status==="done"?"done":state==="doing"?"open":"todo");
  const gTone=gs==="done"?"done":gs==="open"?"doing":"todo";
  const gTxt=gs==="done"?"passed":gs==="open"?"not passed":"upcoming";
  const gateNote=(planPh&&planPh.gate&&(planPh.gate.body||planPh.gate.label))||(gateObj&&gateObj.body)||(gs==="done"?"Passed.":"Not reached.");
  const gateMissing=(def&&def.gate&&def.gate.missing)||(gateObj&&(gateObj.missing||gateObj.blockers))||[];
  const hasCriteriaSystem=(d.phases||[]).some(ph=>ph.criteria&&ph.criteria.length);
  const allCrit=(def&&def.criteria)?def.criteria:[];
  const isOk=c=>c.result&&["pass","waived"].includes(c.result.result);
  const missCrit=allCrit.filter(c=>!isOk(c));

  if(gateKey){
    const gateDiv=el("div","gate");
    const stDiv=el("div","state");
    stDiv.append(el("span","lab","Gate "+gateKey),el("span","st "+gTone,gTxt));
    gateDiv.append(stDiv);

    if(gs==="open"&&allCrit.length>0){
      const line=el("div","line");
      line.append("",el("em","num",String(missCrit.length))," of ",el("span","num",String(allCrit.length))," criteria remaining");
      gateDiv.append(line);
      const gmiss=el("ul","gmiss");
      missCrit.forEach(c=>{
        const li=el("li");
        const sp=el("span");
        sp.append(c.text.replace(/\s*\(.*\)$/,""));
        sp.append(" ",el("span","who","· "+(LT_WHO[c.confirm_by]||c.confirm_by)));
        li.append(sp);
        gmiss.append(li);
      });
      gateDiv.append(gmiss,el("span","then","Then the user passes it."));
    }else if(gs==="open"&&gateMissing.length>0){
      const line=el("div","line");
      line.append("",el("em","num",String(gateMissing.length))," conditions not yet met");
      gateDiv.append(line);
      const gmiss=el("ul","gmiss");
      gateMissing.forEach(m=>{
        const li=el("li");li.append(el("span","",m));gmiss.append(li);
      });
      gateDiv.append(gmiss,el("span","then","Then the user passes it."));
    }else{
      gateDiv.append(el("div","line",gateNote));
    }
    right.append(gateDiv);
  }

  if(hasCriteriaSystem){
    right.append(el("hr","rule"));
    right.append(el("span","lab","Professional evaluation criteria"));
    if(allCrit.length>0){
      const cats=[...new Set(allCrit.map(c=>c.category||"chung"))];
      cats.forEach(cat=>{
        const grp=el("div","grp");
        grp.append(el("span","lab",cat));
        allCrit.filter(c=>(c.category||"chung")===cat).forEach(c=>{
          const ok=isOk(c);
          const row=el("div","crit"+(ok?"":" miss-row"));
          const what=el("span","what");
          ltFormat(what,c.text+(c.level==="optional"?" (optional)":""));
          const who=el("span","who",LT_WHO[c.confirm_by]||c.confirm_by||"");
          const stRes=ok?(c.result.result==="waived"?"waived":"passed"):(c.result&&c.result.value?c.result.value+" · not yet":"not yet");
          const st=el("span","st "+(ok?"done":"miss"),stRes);
          row.append(what,who,st);
          grp.append(row);
        });
        right.append(grp);
      });
    }else{
      right.append(el("p","empty","This phase's criteria are not set yet. They will be written when the previous phase passes its gate."));
    }
  }

  detail.replaceChildren(left,right);

  const offItems=d.off_roadmap||[];
  if(offItems.length>0){
    off.style.display="";
    const ul=el("ul");
    offItems.forEach(o=>{
      const li=el("li");
      li.append(el("span","id","#"+o.id)," ");
      li.append(link(o.title,hashFor(p,"task",o.id)));
      ul.append(li);
    });
    off.replaceChildren(el("span","lab","Off roadmap"),ul);
  }else{
    off.style.display="none";
    off.replaceChildren();
  }
}

function roadmapDoc(d,p,sel,pick){
  const root=el("div","lt wrap");
  const camps=ltCamps(d);
  const gates=d.gates||[];
  const cur=camps.length?camps[0].cur:null;
  const s=sel!=null&&camps.some(c=>c.n===sel)?sel:cur;

  const hd=el("header","lt-head");
  const leftHd=el("div");
  const eyebrow=(d.plan&&d.plan.header&&d.plan.header.eyebrow)||"Project roadmap";
  leftHd.append(el("div","cap",eyebrow));
  const h1=el("h1","foil",(d.plan&&d.plan.header&&d.plan.header.title)||d.title||"Roadmap");
  leftHd.append(h1);
  const metaText=camps.length+" phase · "+gates.length+" gates · the summit is the release";
  const meta=el("div","meta",metaText);
  hd.append(leftHd,meta);
  root.append(hd);

  if(camps.length){
    root.append(ltMapBox(camps,d,root,s,pick));
  }

  const detail=el("div","detail");
  const off=el("div","off");
  root.append(detail,off);
  renderDetail(detail,off,s,d,p,camps);

  return root;
}
async function roadmapView(box,p,id){
  box.className="page wide";
  const list=await get("/api/roadmap?project="+enc(p));
  if(!list.length){box.append(head("Roadmap",0),empty("No roadmap yet","Load with:","strata.py roadmap import PLAN.json --project "+p+" --roadmap ID"));return}
  // default: newest roadmap of the phase model (has phases), else newest; the list API carries no phases flag, so ask each
  let def=null;
  if(!list.some(x=>x.roadmap===id)&&list.length>1){
    const full=await Promise.all(list.map(x=>get("/api/roadmap?project="+enc(p)+"&roadmap="+enc(x.roadmap)).then(d=>({x,ph:(d.phases||[]).length>0}),()=>({x,ph:false}))));
    const newest=a=>a.sort((a,b)=>String(b.x.updated_at).localeCompare(String(a.x.updated_at)))[0];
    def=(newest(full.filter(f=>f.ph))||newest(full)).x}
  const cur=list.find(x=>x.roadmap===id)||def||list[0], url="/api/roadmap?project="+enc(p)+"&roadmap="+enc(cur.roadmap), host=el("div");
  if(list.length>1){const r=el("div","tchips");r.append(el("span","lbl","Roadmap"));list.forEach(x=>{const a=link(x.title,hashFor(p,"roadmap",x.roadmap),x===cur?"on":"");r.append(a)});box.append(r)}
  box.append(host);
  let ver=null, data=null, sel=+hq().get("ph")||null;
  if(hq().get("ph")==="0")sel=0;
  // camp pick: switch phase; hash remembers (?ph=N)
  const pick=n=>{sel=n;const q=hq();q.set("ph",n);history.replaceState(null,"",location.hash.split("?")[0]+"?"+q);draw();
    const cp=host.querySelector(".lt-map .camp.sel");if(cp)cp.focus({preventScroll:true})};
  const draw=()=>{const camps=ltCamps(data), s=sel!=null&&camps.some(c=>c.n===sel)?sel:camps.length?camps[0].cur:null;
    host.replaceChildren(roadmapDoc(data,p,s,pick))};
  const load=async()=>{const d=await get(url);if(d.version===ver)return;ver=d.version;data=d;const sc=$("content").scrollTop;draw();$("content").scrollTop=sc};
  await load();
  const tick=async()=>{
    if(!host.isConnected){clearInterval(t);document.removeEventListener("visibilitychange",tick);return}
    if(document.hidden)return;
    try{const v=await get(url+"&only=version");if(v.version!==ver)await load()}catch{}
  };
  const t=setInterval(tick,3000);document.addEventListener("visibilitychange",tick);
}

/* ---------- command palette ---------- */
const SRC={item:["Task","task"],issue:["Issue","issue"],page:["Discussion","pages"],doc:["Docs","docs"]};
let hits=[], sel=0, qtok=0, timer=null, mouseMoved=false;
function openPal(){closeKeys();$("pal").hidden=false;$("q").value="";hits=navHits();sel=0;drawHits();$("q").focus()}
function closePal(){$("pal").hidden=true}
function navHits(){
  const out=[];
  if(CUR.p)TABS.forEach(([k,l,g])=>out.push({grp:"Navigation",title:l,sub:byId[CUR.p].name,ic:k,kbd:"G "+g.toUpperCase(),run:()=>{location.hash=hashFor(CUR.p,k)}}));
  PROJ.filter(p=>p.id!==CUR.p).forEach(p=>out.push({grp:"Projects",title:p.name,sub:p.id,ic:"proj",run:()=>{location.hash=hashFor(p.id,"overview")}}));
  out.push({grp:"Commands",title:"Toggle light / dark",ic:"sun",run:toggleTheme},{grp:"Commands",title:"Keyboard shortcuts",ic:"overview",kbd:"?",run:openKeys});
  return out;
}
function searchHits(r){
  const by={};r.forEach(h=>{const t=h.src==="item"&&h.key==="issue"?"issue":h.src;(by[t]=by[t]||[]).push(h)});
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
    if(typing)return e.target.blur();
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
$("moon").append(svg(O.moon));
$("band").append(svg(contours(7,480,120,6)));
themeIcon();
$("theme").onclick=toggleTheme;
$("help").onclick=openKeys;
$("searchbtn").onclick=openPal;
$("menu").onclick=()=>{document.body.classList.toggle("menu");document.body.classList.remove("collapsed")};
$("scrim").onclick=()=>document.body.classList.remove("menu");
addEventListener("hashchange",()=>render());
render();
/* live: redraw the current tab when /api/version moves (CLI/MCP write, docs edit). C4, roadmap and doc readers poll on their own. */
{let ver=null;const live=async()=>{
  if(document.hidden)return;
  try{const v=(await get("/api/version")).version;if(ver!==null&&v!==ver){
    const a=document.activeElement,busy=a&&/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)||document.querySelector("dialog[open]");
    if(busy||CUR.tab==="c4"||CUR.tab==="roadmap"||(CUR.tab==="docs"&&CUR.id))return;  // retry next tick, ver stays old
    await render(true)}ver=v}catch{}};
 setInterval(live,2000);document.addEventListener("visibilitychange",live)}
