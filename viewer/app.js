"use strict";
// App shell. Read-only. All text goes through textContent (el() from page.js); never assigns markup.
// el, get, enc and renderPage come from page.js (STRATA_SHELL makes it skip its own routing).
const $=id=>document.getElementById(id);
const TABS=[["overview","Tổng quan","o"],["task","Task","t"],["roadmap","Lộ trình","m"],["issue","Issue","i"],["decision","Decision","d"],["pages","Thảo luận","p"],["docs","Tài liệu","r"],["c4","Kiến trúc","a"],["audit","Nhật ký","l"]];
const TAB_LABEL=Object.fromEntries(TABS.map(t=>[t[0],t[1]]));
const ST_ITEM=["proposed","approved","open","doing","review","done","rejected"];
const ST_DEC=["proposed","accepted","superseded","rejected"];
const ST_DOC=["current","draft","outdated","missing"], KIND_DOC=["research","architect","review","plan","other"];
const store={get(k){try{return localStorage.getItem(k)}catch{return null}},set(k,v){try{localStorage.setItem(k,v)}catch{}}};
const NOGRP="Chưa phân nhóm";
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
const priIcon=p=>{const e=svg(S("0 0 16 16",PRI[p]||PRI.none,'class="pri"')), t=document.createElementNS("http://www.w3.org/2000/svg","title");t.textContent=p||"không ưu tiên";e.append(t);return e};
const IC={overview:'<path d="M2.5 13.5h11M4 11V7M8 11V3.5M12 11V6"/>',task:'<circle cx="8" cy="8" r="5.5"/><path d="M5.6 8.1l1.6 1.6 3.2-3.4"/>',
  issue:'<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.5M8 10.8v.2"/>',decision:'<path d="M8 2.5v11M3 5.5h10M3 5.5l-1.5 4h3zM13 5.5l-1.5 4h3z"/>',
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
function counts(p){return {task:total(p.tasks),issue:p.issues_open,decision:p.decisions,pages:p.pages,docs:p.docs}}
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

async function render(){
  const my=++token;
  document.body.classList.remove("menu");
  try{PROJ=await get("/api/projects");byId=Object.fromEntries(PROJ.map(p=>[p.id,p]))}catch(e){return $("content").replaceChildren(el("p","err",e.message))}
  if(my!==token)return;
  const r=route();CUR=r;side(r);crumbs(r);
  const box=el("div");
  try{
    if(!r.p) box.append(empty("Chưa có project nào","Tạo bằng:","strata.py project add ID --name ..."));
    else await VIEW[r.tab](box,r.p,r.id);
  }catch(e){box.append(el("p","err",e.message))}
  if(my!==token)return;
  document.title=(r.p?byId[r.p].name+" · "+TAB_LABEL[r.tab]+" · ":"")+"Strata";
  const rd=box.querySelector(":scope>.reader");
  if(!rd&&!box.className)box.className="page"+(r.tab==="task"||r.tab==="roadmap"?" wide":"");
  $("content").replaceChildren(rd||box);
  $("content").scrollTop=0;
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
  return m<1?"vừa xong":m<60?Math.round(m)+"p":m<1440?Math.round(m/60)+"h":m<43200?Math.round(m/1440)+"d":Math.round(m/43200)+"th";
}
function dateCell(s){const d=el("span","d",rel(s));d.title=ago(s);return d}
function pill(st){const p=el("span","pill s-"+st);p.append(el("i"),st);return p}
function head(title,n){const h=el("div","head");h.append(el("h1","foil",title));if(n!=null)h.append(el("span","n",n));return h}
function fbar(groups){
  const b=el("div","fbar");b.append(el("span","lbl","Lọc"));
  groups.forEach(([opts,cur,on,plain],i)=>{if(i)b.append(el("span","sp"));
    ["",...opts].forEach(o=>{const x=el("button",o===cur?"on":"");if(o&&!plain)x.append(statusIcon(o));x.append(o||"tất cả");
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
  const c=el("div","card edge"), h=el("h2","",title);if(n!=null)h.append(el("span","n",n));h.append(link("Xem tất cả →",hashFor(p,tab)));
  const ul=el("ul");
  if(!rows.length)ul.append(el("li","muted",emptyText||"Trống"));
  rows.forEach(([st,t,href,extra])=>{const li=el("li");if(st)li.append(statusIcon(st));li.append(link(t,href));if(extra)li.append(extra);ul.append(li)});
  c.append(h,ul);return c;
}

const VIEW={
  async overview(box,p){
    const [tasks,issues,decs,pages,docs]=await Promise.all([get("/api/items?kind=task&project="+enc(p)),get("/api/items?kind=issue&project="+enc(p)),
      get("/api/decisions?project="+enc(p)),get("/api/pages?project="+enc(p)),get("/api/docs?project="+enc(p))]);
    const pr=byId[p], done=pr.tasks.done||0, doing=pr.tasks.doing||0, all=total(pr.tasks), pct=all?Math.round(100*done/all):0;
    const hero=el("div","hero");// full-bleed hero art behind the content column: traced mountains anchored right + fitted waves edge to edge
    const bg=el("div","herobg");bg.setAttribute("aria-hidden","true");const mt=el("div","mtn"), wv=el("div","waves");bg.append(wv,mt);box.append(bg);
    heroArt("mountains").then(x=>mt.append(x.cloneNode(true))).catch(()=>{});
    heroArt("mountains-waves").then(x=>wv.append(x.cloneNode(true))).catch(()=>{});
    hero.append(el("h1","foil",pr.name));
    if(pr.description)hero.append(el("p","",pr.description));
    const props=el("div","props");
    [["Trạng thái",pr.status||"—"],["Task",all],["Issue mở",pr.issues_open],["Decision",pr.decisions],["Tài liệu",pr.docs],["Cập nhật",rel(pr.last_update)||"chưa có"]]
      .forEach(([k,v])=>{const s=el("span","",k+" ");s.append(el("b","",v));props.append(s)});
    const prog=el("div","prog"), bar=el("div","bar"), a=el("i","b-done"), b=el("i","b-doing");
    a.style.width=(all?100*done/all:0)+"%";b.style.width=(all?100*doing/all:0)+"%";bar.append(a,b);
    prog.append(bar,el("span","pct",pct+"%"));
    const stats=el("div","props");[["Scope",all],["Đang làm",doing],["Xong",done]].forEach(([k,v])=>{const s=el("span","",k+" ");s.append(el("b","",v));stats.append(s)});
    hero.append(props,prog,stats);box.append(hero);
    const subs=PROJ.filter(x=>x.parent===p);
    if(subs.length){const g=el("div","grid");subs.forEach(s=>{
      const c=link("",hashFor(s.id,"overview"),"card edge pcard");c.append(orn("topo",contours(hash(s.id))),el("b","",s.name),
        el("span","",total(s.tasks)+" task · "+s.issues_open+" issue mở · "+s.docs+" tài liệu"));g.append(c)});box.append(g)}
    const open=issues.filter(x=>x.status!=="done"&&x.status!=="rejected");
    const recent=[...pages.map(x=>[null,x.title,hashFor(p,"pages",x.slug),x.updated_at]),
      ...docs.filter(x=>x.status!=="missing").map(x=>[x.status,x.title,hashFor(p,"docs",x.path),x.updated_at])]
      .sort((a,b)=>(b[3]||"").localeCompare(a[3]||"")).slice(0,6);
    const g=el("div","grid");
    g.append(
      card("Task đang làm","task",p,tasks.filter(x=>x.status==="doing").slice(0,5).map(x=>["doing","#"+x.id+" "+x.title,hashFor(p,"task",x.id)]),"Không có task đang làm",doing),
      card("Issue đang mở","issue",p,open.slice(0,5).map(x=>[x.status,"#"+x.id+" "+x.title,hashFor(p,"issue",x.id),priIcon(x.priority)]),"Không có issue mở",open.length),
      card("Decision mới nhất","decision",p,decs.slice(0,5).map(x=>[x.status,"#"+x.id+" "+x.title,hashFor(p,"decision",x.id)]),"Chưa có decision",decs.length),
      card("Mới cập nhật","docs",p,recent.map(x=>[x[0]||"open",x[1],x[2],dateCell(x[3])]),"Chưa có tài liệu"));
    box.append(g);
  },
  task:(box,p,id)=>boardView(box,p,id),
  roadmap:(box,p,id)=>roadmapView(box,p,id),
  issue:(box,p,id)=>itemView(box,p,id,"issue"),
  async decision(box,p,id){
    const ds=await get("/api/decisions?project="+enc(p));
    box.append(head("Decision",ds.length));
    const d=ds.find(x=>String(x.id)===id);
    if(d){
      const c=el("div","detail");c.append(el("h2","","#"+d.id+" "+d.title));
      const pr=el("div","props");pr.append(pill(d.status),el("span","",ago(d.created_at)));c.append(pr);
      let rej;try{rej=JSON.parse(d.rejected_options)}catch{rej=[d.rejected_options]}
      const dl=el("dl");
      [["Bối cảnh",d.context],["Quyết định",d.decision],["Hệ quả",d.consequences],["Thay thế",d.supersedes?"#"+d.supersedes:null],
       ["Phương án bị loại",(Array.isArray(rej)?rej:[rej]).filter(x=>x!=null).map(x=>typeof x==="string"?x:JSON.stringify(x)).join("; ")]]
        .forEach(([k,v])=>{if(v)dl.append(el("dt","",k),el("dd","",v))});
      c.append(dl);box.append(c);
    }else if(id)box.append(el("p","err","Không tìm thấy #"+id));
    if(!ds.length)return box.append(empty("Chưa có decision","Ghi bằng:","strata.py decision add --project "+p));
    box.append(...grouped(ds,x=>x.status,ST_DEC,(k,h)=>h.append(statusIcon(k),k),x=>{
      const a=link("",hashFor(p,"decision",x.id),"row"+(String(x.id)===id?" sel":""));
      a.append(el("span"),el("span","id","D-"+x.id),statusIcon(x.status),el("span","t",x.title),el("span","x"),dateCell(x.created_at));return a}));
  },
  async pages(box,p,id){
    if(id){
      box.className="page narrow";
      const root=el("article");root.id="pg";box.append(root);
      renderPage(await get("/api/page/"+enc(p)+"/"+enc(id)),root);
      return;
    }
    const ps=(await get("/api/pages?project="+enc(p))).filter(x=>x.kind!=="plan"); // plan pages live under Lộ trình
    box.append(head("Thảo luận",ps.length));
    if(!ps.length)return box.append(empty("Chưa có page nào","Page được ghi bằng CLI hoặc MCP của strata."));
    ps.forEach(x=>{const a=link("",hashFor(p,"pages",x.slug),"row pg");a.append(icon("pages"),el("span","t",x.title),el("span","kind",x.kind),dateCell(x.updated_at));box.append(a)});
  },
  async docs(box,p,id){
    const docs=await get("/api/docs?project="+enc(p));
    docs.forEach(x=>{try{x.code=JSON.parse(x.code||"[]")||[]}catch{x.code=[]}});
    if(id)return docReader(box,p,id,docs);
    if(!docs.length){box.append(head("Mục lục",0));return box.append(empty("Chưa có tài liệu","Viết một file YAML vào docs_dir của project, ví dụ","docs/strata/c4.yaml"))}
    toc(box,p,docs.filter(x=>x.status!=="missing"),docs.filter(x=>x.status==="missing").length);
  },
  async c4(box,p,id){
    const r=el("div","reader c4"), f=el("iframe","frame c4");
    f.src="/c4?project="+enc(p)+"&embed=1"+(id?"#"+enc(id):"");f.title="Kiến trúc C4";r.append(f);box.append(r);
  },
  async audit(box,p){
    const rs=await get("/api/audit?limit=200&project="+enc(p));
    box.append(head("Nhật ký",rs.length));
    if(!rs.length)return box.append(empty("Chưa có bản ghi","Mọi thay đổi qua CLI/MCP được ghi ở đây."));
    const day=d=>d.toDateString(), today=new Date(), yest=new Date(Date.now()-864e5);
    let last="";
    rs.forEach(x=>{const d=new Date(x.ts);
      if(day(d)!==last){last=day(d);box.append(el("div","dayh",last===day(today)?"Hôm nay":last===day(yest)?"Hôm qua":d.toLocaleDateString("vi-VN",{day:"numeric",month:"short",year:"numeric"})))}
      const a=x.after||"", r=el("div","arow");
      r.append(el("span","tm",isNaN(d)?"":d.toTimeString().slice(0,5)),el("span","ac",x.actor_role||""),el("span","v",x.tool||""),el("span","",x.target||""),el("span","df",a.length>160?a.slice(0,160)+"…":a));
      r.title=ago(x.ts);box.append(r)});
  },
};

/* ---------- mục lục: chương = thư mục con của docs_dir, cây bên trái = cây thư mục ---------- */
const NOCODE="Chung", CHAP={architect:"Kỹ thuật",research:"Nghiên cứu",plan:"Kế hoạch",review:"Review"}, CHAP_ORDER=["architect","research","plan","review"];
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
  h.append(el("div","eyebrow","Tài liệu · "+(byId[p]?byId[p].name:p)),el("h1","foil","Mục lục"),
    el("p","muted",docs.length+" tài liệu trong "+new Set(docs.map(docGroup)).size+" chương"+(missing?" · "+missing+" file đã mất":"")));
  const f=el("input");f.type="search";f.id="tocq";f.placeholder="Tìm trong mục lục…";f.setAttribute("aria-label","Tìm tài liệu");
  f.oninput=()=>{q=f.value.toLowerCase();draw()};h.append(f);
  side.setAttribute("aria-label","Cây thư mục tài liệu");
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
    const all=el("button","tn root"+(sel==null?" on":""));all.append(el("span","nm","Toàn bộ"),el("span","n",docs.length));all.onclick=()=>pick(null);
    const kids=Object.values(tree.kids).sort((a,b)=>chapSort(a.name,b.name)).flatMap(k=>node(k,0));
    if(loose){const b=el("button","tn"+(sel===""?" on":""));b.append(el("span","tg","·"),el("span","nm",NOCODE),el("span","n",loose));b.onclick=()=>pick(sel===""?null:"");kids.push(b)}
    side.replaceChildren(el("div","slabel","Thư mục"),all,...kids);
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
    if(!rows.length){const e=empty("Không có tài liệu khớp");const c=el("button","","Bỏ lọc");c.onclick=()=>{q="";f.value="";pick(null)};e.append(c);return list.replaceChildren(e)}
    const g={};rows.forEach(x=>(g[docGroup(x)]=g[docGroup(x)]||[]).push(x));
    list.replaceChildren(...Object.keys(g).sort(chapSort).map(k=>{
      const sec=el("section","chap"), hh=el("h2");hh.append(el("span","cn",chapName(k)));if(k!==NOCODE)hh.append(el("code","",k+"/"));hh.append(el("span","n",g[k].length+" tài liệu"));sec.append(hh);
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
    if(d.errors.length){const e=el("div","docerr");e.append(el("b","","Tài liệu có lỗi cấu trúc"));const ul=el("ul");d.errors.forEach(x=>ul.append(el("li","",x)));e.append(ul);art.append(e)}
    d.blocks.forEach(b=>{const s=el("section");
      try{s.append(b.type==="c4"?c4(b,p):b.type==="query"?query(b):b.type==="diagram"||b.type==="statemachine"||b.type==="roadmap"?({diagram,statemachine,roadmap})[b.type](b,linkFor):R[b.type]?R[b.type](b):el("p","err","Block không rõ loại: "+b.type))}
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
  const r=el("div","reader"), t=el("div","tbar"), back=link("",hashFor(p,"docs"),"back");back.append(icon("prev"),"Tài liệu");
  t.append(back,el("span","ttl",d?d.title:id));
  if(d)t.append(el("span","kind",d.kind),pill(d.status));
  const nav=(k,ic,lbl)=>{const x=sib[i+k], b=toolBtn(ic,lbl+" (Alt "+(k<0?"←":"→")+")",null,()=>{if(x)location.hash=hashFor(p,"docs",x.path)});b.disabled=!x;b.dataset.nav=k;return b};
  const nx=nav(1,"chev","Tài liệu sau");
  t.append(nav(-1,"prev","Tài liệu trước"),nx);
  r.append(t);box.append(r);
  if(!d||d.status==="missing")return r.append(empty("File không còn trên đĩa hoặc chưa được quét","Chạy lại:","strata.py doc scan --project "+p));
  const isY=id.endsWith(".yaml"), isMd=id.endsWith(".md"), f=isY||isMd?el("div","frame mdoc"):el("iframe","frame");
  const load=isY?docView(f,p,id):()=>isMd?fetch(url).then(x=>x.text()).then(s=>f.replaceChildren(md(s))):(f.src=url);f.title=d.title;if(!isY)load();
  t.append(toolBtn("reload","Tải lại",null,load),toolBtn("ext","Mở tab mới",url),
    toolBtn("copy","Copy link",null,()=>{navigator.clipboard&&navigator.clipboard.writeText(location.href).catch(()=>{})}));
  r.append(f);
}

/* ---------- task board (read-only): ready strip, status columns, detail pane. Filters live in the hash query. ---------- */
const COLS=["proposed","approved","doing","review","done"], FOLD=["open","rejected"];
const PRI_TAG={p0:"P0",p1:"P1",p2:"P2",p3:"P3"};
const BKIND=["task","issue","step"];
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
  if(x.priority)row.append(tag(PRI_TAG[String(x.priority).toLowerCase()]||x.priority,"pri-"+String(x.priority).toLowerCase()));
  if(acN(x))row.append(tag("AC "+acN(x)));
  if(blockedBy&&blockedBy.length)row.append(tag("chặn bởi "+blockedBy.map(i=>"#"+i).join(" "),"block"));
  else if(x.spec&&x.spec.blocked)row.append(tag("bị chặn","block"));
  if(stale(x))row.append(tag("quá 24h","stale","Đã claim hơn 24 giờ"));
  a.append(m,el("span","t",x.title),row);return a;
}
function fold(label,items,mk){
  const d=el("details","tfold");d.append(el("summary","",label+" · "+items.length));
  const c=el("div","cards");items.forEach(x=>c.append(mk(x)));d.append(c);return d;
}
function chipRow(label,opts,cur,set){
  const r=el("div","tchips");r.append(el("span","lbl",label));
  ["",...opts].forEach(o=>{const b=el("button",o===cur?"on":"",o||"tất cả");b.setAttribute("aria-pressed",o===cur);b.onclick=()=>set(o);r.append(b)});
  return r;
}
async function boardView(box,p,id){
  const qs=hq(), f={kind:qs.get("kind")||"",status:qs.get("status")||"",owner:qs.get("owner")||"",q:qs.get("q")||""};
  const go=patch=>{const n=new URLSearchParams(qs);Object.entries(patch).forEach(([k,v])=>v?n.set(k,v):n.delete(k));location.hash=boardHref(p,id,n)};
  const [all,ready]=await Promise.all([get("/api/items?project="+enc(p)),get("/api/items?ready=1&project="+enc(p))]);
  const rd=new Set(ready.map(x=>x.id));
  const wait=all.filter(x=>x.status==="approved"&&["task","step"].includes(x.kind)&&!rd.has(x.id));
  const need={};
  await Promise.all(wait.map(x=>get("/api/items?id="+x.id).then(r=>{need[x.id]=(r[0]&&r[0].deps?r[0].deps.needs:[]).filter(d=>d.status!=="done").map(d=>d.id)}).catch(()=>{need[x.id]=[]})));
  const owners=[...new Set(all.map(x=>x.owner).filter(Boolean))].sort();
  const needle=f.q.toLowerCase();
  const vis=all.filter(x=>(!f.kind||x.kind===f.kind)&&(!f.status||x.status===f.status)&&(!f.owner||x.owner===f.owner)&&(!needle||(x.title+" #"+x.id).toLowerCase().includes(needle)));
  box.append(head("Bảng việc",vis.length));
  const bar=el("div","tbar2");
  const search=el("input");search.type="search";search.id="tq";search.placeholder="Tìm trong tiêu đề…";search.value=f.q;search.setAttribute("aria-label","Tìm trong tiêu đề");
  search.onchange=()=>go({q:search.value.trim()});
  bar.append(chipRow("Loại",BKIND,f.kind,v=>go({kind:v})),chipRow("Trạng thái",ST_ITEM,f.status,v=>go({status:v})));
  if(owners.length)bar.append(chipRow("Owner",owners,f.owner,v=>go({owner:v})));
  bar.append(search);box.append(bar);
  const act=[...Object.entries(f)].filter(([,v])=>v);
  if(act.length){const c=el("div","tactive");act.forEach(([k,v])=>{const b=el("button","chipx",k+": "+v+" ×");b.onclick=()=>go({[k]:""});c.append(b)});box.append(c)}
  // ready strip
  const rs=el("div","tready"), vs=new Set(vis.map(x=>x.id)), rv=ready.filter(x=>vs.has(x.id));
  rs.append(el("b","","Sẵn sàng · "+rv.length));
  rv.forEach(x=>{const a=link("#"+x.id+" "+x.title,boardHref(p,x.id,qs),"chip"+(String(x.id)===id?" on":""));rs.append(a)});
  const blocked=wait.filter(x=>need[x.id]&&need[x.id].length);
  if(blocked.length){const by=[...new Set(blocked.flatMap(x=>need[x.id]))];rs.append(el("span","mono",(rv.length?"· ":"")+blocked.length+" đã duyệt nhưng bị chặn bởi "+by.map(i=>"#"+i).join(" ")))}
  else if(!rv.length)rs.append(el("span","mono","Chưa có việc nào sẵn sàng"));
  box.append(rs);
  const main=el("div","tmain"), board=el("div","tboard"), mk=x=>itemCard(x,p,qs,id,need[x.id]);
  COLS.forEach(st=>{
    const its=vis.filter(x=>x.status===st), col=el("section","tcol"), h=el("h3");
    h.append(statusIcon(st),st+" · "+its.length);col.append(h);
    const c=el("div","cards");its.forEach(x=>c.append(mk(x)));if(!its.length)c.append(el("p","muted tnone","Trống"));col.append(c);board.append(col);
  });
  const folds=el("div","tfolds");
  FOLD.forEach(st=>{const its=vis.filter(x=>x.status===st);if(its.length)folds.append(fold(st,its,mk))});
  const left=el("div","tleft");left.append(board);if(folds.children.length)left.append(folds);
  const pane=el("aside","tdetail");
  main.append(left,pane);box.append(main);
  if(!all.length)box.prepend(empty("Chưa có việc nào","Thêm bằng CLI:","strata.py item add --project "+p+" --kind task --title ..."));
  if(!id)return pane.append(el("p","muted","Chọn một việc để xem chi tiết."));
  const d=(await get("/api/items?id="+enc(id)))[0];
  if(!d||d.project!==p)return pane.append(el("p","err","Không tìm thấy #"+id));
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
  section(c,"Mục tiêu",sp.goal?el("p","dtxt",sp.goal):null);
  if(ac.length){const ul=el("ul","acl");ac.forEach(a=>{const li=el("li");li.append(el("span","cb","☐"),el("span","",typeof a==="string"?a:JSON.stringify(a)));ul.append(li)});section(c,"Tiêu chí · "+ac.length,ul)}
  if(sp.verify){const pre=el("pre");pre.append(el("code","",sp.verify));section(c,"Kiểm",pre)}
  const sc=sp.scope||{};
  if((sc.touch||[]).length||(sc.forbid||[]).length){
    const w=el("div","scope");
    [["sửa",sc.touch],["cấm",sc.forbid]].forEach(([k,v])=>{if(v&&v.length){const r=el("div","srow");r.append(el("b","",k));const l=el("span","mono",v.join("  "));r.append(l);w.append(r)}});
    section(c,"Phạm vi",w)}
  if((sp.open_questions||[]).length){const ul=el("ul");sp.open_questions.forEach(q=>ul.append(el("li","",String(q))));section(c,"Câu hỏi mở",ul)}
  const dp=d.deps||{needs:[],blocks:[]};
  if(dp.needs.length||dp.blocks.length){
    const w=el("div","deps");
    [["Cần",dp.needs],["Chặn",dp.blocks]].forEach(([k,v])=>{if(v.length){const r=el("div","srow");r.append(el("b","",k));const l=el("span","dlist");v.forEach(x=>l.append(dlink(x,p,qs)));r.append(l);w.append(r)}});
    section(c,"Phụ thuộc",w)}
  const lk=d.links||{c4:[],decisions:[]};
  if(lk.c4.length||lk.decisions.length){
    const w=el("div","deps");
    if(lk.c4.length){const r=el("div","srow");r.append(el("b","","C4"));const l=el("span","dlist");lk.c4.forEach(o=>l.append(link(o,"#/p/"+enc(p)+"/c4/"+enc(o),"dep")));r.append(l);w.append(r)}
    if(lk.decisions.length){const r=el("div","srow");r.append(el("b","","Decision"));const l=el("span","dlist");lk.decisions.forEach(x=>l.append(link("#"+x.id+" "+x.title,hashFor(p,"decision",x.id),"dep")));r.append(l);w.append(r)}
    section(c,"Liên kết",w)}
  if(d.history&&d.history.length){
    const tl=el("div","tl");
    d.history.forEach(h=>{const r=el("div");r.append(el("span","mono",ago(h.time).slice(5)),el("span","",h.actor||""),
      el("span","",h.to?(h.from?h.from+" → ":"")+h.to+(h.note?" · "+h.note:""):h.tool.replace("item.","")+(h.note?" · "+h.note:"")));tl.append(r)});
    section(c,"Lịch sử",tl)}
  if(d.body){const b=el("div","dbody");b.append(md(d.body));section(c,"Mô tả",b)}
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
      c.append(pr,el("p","body",d.body||"(không có mô tả)"));box.append(c);
    }else box.append(el("p","err","Không tìm thấy #"+id));
  }
  if(!rows.length)return box.append(empty("Chưa có "+kind,"Thêm bằng CLI:","strata.py item add --project "+p+" --kind "+kind+" --title ..."));
  let cur="";
  const chips=el("div"), body=el("div"), draw=()=>{
    chips.replaceChildren(fbar([[ST_ITEM,cur,v=>{cur=v;draw()}]]));
    const vis=rows.filter(x=>!cur||x.status===cur);
    if(!vis.length){const e=empty("Không có "+kind+" ở trạng thái "+cur);const c=el("button","","Xoá lọc");c.onclick=()=>{cur="";draw()};e.append(c);return body.replaceChildren(e)}
    body.replaceChildren(...grouped(vis,x=>x.status,["doing","open","approved","proposed","done","rejected"],(k,h)=>h.append(statusIcon(k),k),x=>{
      const a=link("",hashFor(p,kind,x.id),"row"+(String(x.id)===id?" sel":""));
      a.append(priIcon(x.priority),el("span","id",(kind==="task"?"T-":"I-")+x.id),statusIcon(x.status),el("span","t",x.title),el("span","x",x.owner||""),dateCell(x.updated_at||x.created_at));return a}));
  };
  draw();box.append(chips,body);
}

/* ---------- Lộ trình (read-only): 6 sections of a roadmap from /api/roadmap. Data only reaches the DOM through textContent / inline(). ---------- */
const LT_ST={approved:"Chưa làm",doing:"Đang làm",review:"Chờ kiểm",done:"Đạt",blocked:"Bị chặn"};
const LT_FLAG={have:"done",missing:"block",decision:"doing",proposed:"todo"};
// markdown subset from html_to_md: **b**, `c`, [t](url), newline. Relative links cannot resolve here, so they show as plain text.
function ltMd(tag,cls,text){
  const e=el(tag,cls);String(text==null?"":text).split("\n").forEach((ln,i)=>{if(i)e.append(el("br"));inline(e,ln.replace(/\[([^\]]+)\]\((?!https?:|\/|#)[^)\s]*\)/g,"$1"))});
  return e;
}
const ltPct=(n,m)=>m?Math.round(100*n/m):0;
function ltGo(root,id){const t=root.querySelector("#lt-"+CSS.escape(id));if(t)t.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"})}
function ltStatus(s){const x=el("span","lt-st st-"+s.state);x.append(el("i"),LT_ST[s.state]||s.state);return x}
function ltStep(s,p){
  const li=el("li","st-"+s.state+(s.orphan?" orphan":"")), body=el("div","lt-sb"), top=el("div","lt-stop");
  li.append(el("code","",s.key));
  top.append(el("strong","",s.title),ltStatus(s));
  if(s.stale)top.append(tag("cần duyệt lại","stale","Tiêu chí đã đổi sau khi đạt"));
  if(s.orphan)top.append(tag("ngoài kế hoạch","block","Không còn trong plan mới"));
  top.append(link("#"+s.id,hashFor(p,"task",s.id),"lt-id"));
  body.append(top);
  if(s.body)body.append(ltMd("p","lt-body",s.body));
  if(s.proof){const pr=el("div","lt-proof");pr.append(el("b","","Bằng chứng"),s.proof);body.append(pr)}
  const rec=el("div","lt-rec");
  [["người làm",s.owner],["người kiểm",s.reviewer],["bằng chứng",s.evidence],["ghi chú",s.note||s.blocked],["cập nhật",s.updated]].forEach(([k,v])=>{if(v){const r=el("span");r.append(el("b","",k+" "),String(v));rec.append(r)}});
  if(rec.childNodes.length)body.append(rec);
  li.append(body);return li;
}
function ltPhase(ph,d,p,lastGate){
  const keys=ph.steps.filter(k=>d.steps.some(s=>s.key===k)), extra=d.steps.filter(s=>s.phase===ph.n&&!ph.steps.includes(s.key));
  const ss=[...keys.map(k=>d.steps.find(s=>s.key===k)),...extra], live=ss.filter(s=>!s.orphan), n=live.filter(s=>s.status==="done"&&!s.stale).length;
  const a=el("article","lt-phase");a.id="lt-"+ph.anchor;
  const h=el("div","lt-phead"), t=el("div");t.append(el("h3","",ph.title),ltMd("p","lt-intro",ph.intro),el("span","lt-mark",ph.mark));
  const ring=el("div","lt-ring");ring.style.setProperty("--pct",ltPct(n,live.length)+"%");ring.title=n+"/"+live.length+" bước đạt";ring.append(el("span","",n+"/"+live.length));
  h.append(t,ring);a.append(h);
  const ol=el("ol","lt-steps");ss.forEach(s=>ol.append(ltStep(s,p)));a.append(ol);
  const g=el("div","lt-gate"+(lastGate&&lastGate.status==="done"?" passed":""));
  g.append(el("b","",ph.gate.label),ltMd("span","",ph.gate.body));
  if(lastGate)g.append(ltGateTag(lastGate));
  a.append(g);return a;
}
function ltGateTag(g){
  const x=el("span","lt-gtag"+(g.status==="done"?" passed":g.ready?" ready":""));
  x.textContent=g.key+" · "+(g.status==="done"?"đã qua":g.ready?"đủ bước, chờ user duyệt":g.done+"/"+g.total+" bước");return x;
}
function ltSection(sec,d,p,root){
  const s=el("section","lt-sec");s.id="lt-"+sec.id;s.append(el("h2","",sec.title));
  if(sec.intro)s.append(ltMd("p","lt-intro",sec.intro));
  const gate=Object.fromEntries(d.gates.map(g=>[g.key,g]));
  if(sec.facts){const g=el("div","lt-facts");sec.facts.forEach(f=>{const a=el("article","lt-fact");a.append(el("span","lt-flag f-"+(LT_FLAG[f.flagClass]||"todo"),f.flag),el("h3","",f.title),ltMd("p","",f.body));g.append(a)});s.append(g)}
  if(sec.route){const g=el("div","lt-route");sec.route.forEach(r=>{
      const id=(/^G\d+/.exec(r.code)||[""])[0], gt=gate[id], b=el("button","lt-gate-card"+(gt&&gt.status==="done"?" passed":gt&&gt.ready?" ready":""));
      b.append(el("b","",r.code),el("strong","",r.title),el("small","",r.detail));if(gt)b.append(ltGateTag(gt));
      b.onclick=()=>ltGo(root,String(r.href||"").replace(/^#/,""));g.append(b)});s.append(g)}
  if(sec.table){const w=el("div","lt-table"), t=el("table"), hr=el("tr");
    [...sec.table.headers,"Tiến độ"].forEach(x=>hr.append(el("th","",x)));const th=el("thead");th.append(hr);t.append(th);const tb=el("tbody");
    sec.table.rows.forEach(r=>{const tr=el("tr");r.forEach(x=>tr.append(el("td","",x)));const pp=d.progress.phases.find(x=>String(x.phase)===r[0]);tr.append(el("td","",pp?pp.done+"/"+pp.total:"-"));tb.append(tr)});
    t.append(tb);w.append(t);s.append(w)}
  if(sec.callout)s.append(ltMd("div","lt-callout",sec.callout));
  if(sec.phases){const last={};d.gates.forEach(g=>last[Math.max(...g.phases)]=g);sec.phases.forEach(ph=>s.append(ltPhase(ph,d,p,last[ph.n])))}
  if(sec.workstreams){const g=el("div","lt-ws");sec.workstreams.forEach(w=>{const a=el("article","lt-card");a.append(el("h3","",w.title));const ul=el("ul");w.items.forEach(i=>ul.append(ltMd("li","",i)));a.append(ul);g.append(a)});s.append(g)}
  if(sec.decisions){const g=el("div","lt-dec");sec.decisions.forEach(x=>{const a=el("article");a.append(el("b","",x.label),ltMd("p","",x.body));g.append(a)});s.append(g)}
  if(sec.sources){const ol=el("ol","lt-src");sec.sources.forEach(x=>ol.append(ltMd("li","",x)));s.append(ol)}
  return s;
}
function roadmapDoc(d,p){
  const pl=d.plan, root=el("div","lt"), c={};d.steps.forEach(s=>{if(!s.orphan)c[s.state]=(c[s.state]||0)+(s.state==="done"&&s.stale?0:1)});
  const hd=el("header","lt-head");hd.append(el("div","eyebrow",pl.header.eyebrow),el("h1","foil",pl.header.title),ltMd("p","lt-lead",pl.header.lead));
  const meta=el("div","lt-meta");pl.header.meta.forEach(m=>{const s=el("span");s.append(el("b","",m.label+" "),m.value);meta.append(s)});hd.append(meta);
  root.append(hd);
  if(pl.banner)root.append(el("p","lt-banner",pl.banner));
  const top=el("div","lt-top");pl.summary.forEach(x=>{const a=el("article","lt-card");a.append(el("b","",x.label),ltMd("p","",x.body));top.append(a)});root.append(top);
  const pr=el("section","lt-prog"), ph=el("div","lt-ptop"), tx=el("div"), done=d.progress.done, tot=d.progress.total;
  tx.append(el("h2","",pl.progress.title),ltMd("p","lt-intro",pl.progress.intro));
  const cnt=el("div","lt-count",done+"/"+tot);cnt.append(el("small","","bước đạt"));ph.append(tx,cnt);
  const bar=el("div","bar lt-bar"), b1=el("i","b-done"), b2=el("i","b-doing");b1.style.width=ltPct(done,tot)+"%";b2.style.width=ltPct((c.doing||0)+(c.review||0),tot)+"%";bar.append(b1,b2);
  const st=el("div","lt-stats");["done","review","doing","approved","blocked"].forEach(k=>{if(c[k]){const x=ltStatus({state:k});x.append(" "+c[k]);st.append(x)}});
  const nst=d.steps.filter(s=>s.stale).length, nor=d.steps.filter(s=>s.orphan).length;
  if(nst)st.append(tag(nst+" cần duyệt lại","stale"));if(nor)st.append(tag(nor+" ngoài kế hoạch","block"));
  pr.append(ph,bar,st,ltMd("p","lt-guide",pl.progress.guide));root.append(pr);
  const nav=el("nav","lt-nav");nav.setAttribute("aria-label","Các phần của lộ trình");
  pl.sections.forEach(s=>{const b=el("button","",s.title);b.onclick=()=>ltGo(root,s.id);nav.append(b)});root.append(nav);
  pl.sections.forEach(s=>root.append(ltSection(s,d,p,root)));
  return root;
}
async function roadmapView(box,p,id){
  box.className="page wide";
  const list=await get("/api/roadmap?project="+enc(p));
  if(!list.length){box.append(head("Lộ trình",0),empty("Chưa có lộ trình","Nạp bằng:","strata.py roadmap import PLAN.json --project "+p+" --roadmap ID"));return}
  const cur=list.find(x=>x.roadmap===id)||list[0], url="/api/roadmap?project="+enc(p)+"&roadmap="+enc(cur.roadmap), host=el("div");
  if(list.length>1){const r=el("div","tchips");r.append(el("span","lbl","Lộ trình"));list.forEach(x=>{const a=link(x.title,hashFor(p,"roadmap",x.roadmap),x===cur?"on":"");r.append(a)});box.append(r)}
  box.append(host);
  let ver=null;
  const load=async()=>{const d=await get(url);if(d.version===ver)return;ver=d.version;const sc=$("content").scrollTop;host.replaceChildren(roadmapDoc(d,p));$("content").scrollTop=sc};
  await load();
  const tick=async()=>{
    if(!host.isConnected){clearInterval(t);document.removeEventListener("visibilitychange",tick);return}
    if(document.hidden)return;
    try{const v=await get(url+"&only=version");if(v.version!==ver)await load()}catch{}
  };
  const t=setInterval(tick,3000);document.addEventListener("visibilitychange",tick);
}

/* ---------- command palette ---------- */
const SRC={item:["Task","task"],issue:["Issue","issue"],decision:["Decision","decision"],page:["Thảo luận","pages"],doc:["Tài liệu","docs"]};
let hits=[], sel=0, qtok=0, timer=null, mouseMoved=false;
function openPal(){closeKeys();$("pal").hidden=false;$("q").value="";hits=navHits();sel=0;drawHits();$("q").focus()}
function closePal(){$("pal").hidden=true}
function navHits(){
  const out=[];
  if(CUR.p)TABS.forEach(([k,l,g])=>out.push({grp:"Điều hướng",title:l,sub:byId[CUR.p].name,ic:k,kbd:"G "+g.toUpperCase(),run:()=>{location.hash=hashFor(CUR.p,k)}}));
  PROJ.filter(p=>p.id!==CUR.p).forEach(p=>out.push({grp:"Dự án",title:p.name,sub:p.id,ic:"proj",run:()=>{location.hash=hashFor(p.id,"overview")}}));
  out.push({grp:"Lệnh",title:"Đổi sáng / tối",ic:"sun",run:toggleTheme},{grp:"Lệnh",title:"Phím tắt",ic:"overview",kbd:"?",run:openKeys});
  return out;
}
function searchHits(r){
  const by={};r.forEach(h=>{const t=h.src==="item"&&h.key==="issue"?"issue":h.src;(by[t]=by[t]||[]).push(h)});
  return Object.keys(SRC).filter(t=>by[t]).flatMap(t=>by[t].slice(0,8).map(h=>({grp:SRC[t][0],title:h.title||"(không tên)",ic:SRC[t][1],
    sub:(byId[h.project]?byId[h.project].name:h.project)+(h.snippet?" · "+h.snippet.replace(/\s+/g," "):""),
    run:()=>{location.hash=hashFor(h.project,SRC[t][1],h.src==="page"||h.src==="doc"?h.key:h.ref)}})));
}
function drawHits(){
  const out=[];let g="";
  if(!hits.length)out.push(el("li","none","Không có kết quả"));
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
addEventListener("hashchange",render);
render();
