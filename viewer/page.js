"use strict";
// All page text goes through textContent / text nodes. The only innerHTML is mermaid's own sanitized SVG.
const $app=document.getElementById("app");
const enc=encodeURIComponent;
try{const t=localStorage.getItem("strata-theme");if(t)document.documentElement.dataset.theme=t}catch{}

function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
const get=url=>fetch(url).then(r=>r.ok?r.json():Promise.reject(new Error(url+" → "+r.status)));

/* minimal markdown: headings (#..###), paragraphs, lists, | tables |, ``` code, `code`, **bold**, [text](url) */
function inline(parent,s){
  const re=/`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g; let i=0,m;
  while((m=re.exec(s))){
    if(m.index>i) parent.append(s.slice(i,m.index));
    if(m[1]!=null) parent.append(el("code","",m[1]));
    else if(m[2]!=null) parent.append(el("strong","",m[2]));
    else if(/^(https?:\/\/|\/(?![\/\\])|#)/.test(m[4])){const a=el("a","",m[3]);a.href=m[4];a.rel="noopener";parent.append(a)}
    else parent.append(m[0]);
    i=re.lastIndex;
  }
  if(i<s.length) parent.append(s.slice(i));
}
const LI=/^([-*]|\d+\.) /, HEAD=/^(#{1,3}) (.*)/, TR=/^\s*\|.*\|\s*$/;
function md(text){
  const root=el("div","md"), lines=String(text).split("\n"); let i=0;
  while(i<lines.length){
    const l=lines[i];
    if(!l.trim()){i++;continue}
    if(l.startsWith("```")){const buf=[];i++;while(i<lines.length&&!lines[i].startsWith("```"))buf.push(lines[i++]);i++;
      const pre=el("pre");pre.append(el("code","",buf.join("\n")));root.append(pre);continue}
    if(TR.test(l)){const t=el("table"), cells=r=>r.trim().replace(/^\||\|$/g,"").split("|").map(x=>x.trim());
      const rows=[];while(i<lines.length&&TR.test(lines[i]))rows.push(lines[i++]);
      rows.filter(r=>!/^\s*\|[\s:|-]+\|\s*$/.test(r)).forEach((r,k)=>{const tr=el("tr");
        cells(r).forEach(c=>{const td=el(k?"td":"th");inline(td,c);tr.append(td)});t.append(tr)});
      root.append(t);continue}
    const h=l.match(HEAD);
    if(h){const e=el("h"+(h[1].length+1));inline(e,h[2]);root.append(e);i++;continue}
    if(LI.test(l)){const list=el(/^\d/.test(l)?"ol":"ul");
      while(i<lines.length&&LI.test(lines[i])){const li=el("li");inline(li,lines[i].replace(LI,""));list.append(li);i++}
      root.append(list);continue}
    const buf=[];
    while(i<lines.length&&lines[i].trim()&&!lines[i].startsWith("```")&&!HEAD.test(lines[i])&&!LI.test(lines[i])&&!TR.test(lines[i]))buf.push(lines[i++]);
    const p=el("p");inline(p,buf.join(" "));root.append(p);
  }
  return root;
}

/* ---- mermaid figures: diagram, statemachine and hand-written mermaid all render through here ----
   Look ported from project1's doc.js. Colours come from the --d-* tokens in page.css, so both themes work. */
let mmN=0;
const tok=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function classDefs(){
  const ink=tok("--fg"), d=(n,fill,stroke,x)=>`  classDef ${n} fill:${fill},stroke:${stroke},color:${ink},stroke-width:1.4px${x||""}`;
  return [d("ui",tok("--d-ui-soft"),tok("--d-ui")),d("proc",tok("--d-proc-soft"),tok("--d-proc")),
    d("store",tok("--d-store-soft"),tok("--d-store")),d("dec",tok("--d-amber-soft"),tok("--d-amber")),
    d("ok",tok("--d-ok-soft"),tok("--d-ok")),d("bad",tok("--d-red-soft"),tok("--d-red")),
    d("muted",tok("--bg"),tok("--faint"),",stroke-dasharray:4 3")].join("\n");
}
function mmConfig(){
  const v={fontFamily:tok("--body"),fontSize:"13px",background:tok("--card"),
    primaryColor:tok("--d-proc-soft"),primaryTextColor:tok("--fg"),primaryBorderColor:tok("--d-proc"),
    secondaryColor:tok("--bg"),tertiaryColor:tok("--bg"),lineColor:tok("--faint"),textColor:tok("--fg"),
    mainBkg:tok("--d-proc-soft"),nodeBorder:tok("--d-proc"),clusterBkg:tok("--card"),clusterBorder:tok("--line"),titleColor:tok("--muted"),
    edgeLabelBackground:tok("--card"),actorBkg:tok("--card"),actorBorder:tok("--line"),actorTextColor:tok("--fg"),actorLineColor:tok("--line"),
    signalColor:tok("--accent"),signalTextColor:tok("--fg"),labelBoxBkgColor:tok("--bg"),labelBoxBorderColor:tok("--line"),labelTextColor:tok("--fg"),
    noteBkgColor:tok("--d-amber-soft"),noteBorderColor:tok("--d-amber"),noteTextColor:tok("--fg"),sequenceNumberColor:"#FFFFFF",
    stateLabelColor:tok("--fg"),transitionColor:tok("--faint"),transitionLabelColor:tok("--muted"),stateBkg:tok("--d-proc-soft"),
    altBackground:tok("--bg"),compositeBackground:tok("--bg"),specialStateColor:tok("--muted")};
  return {startOnLoad:false,theme:"base",themeVariables:v,securityLevel:"loose",
    flowchart:{htmlLabels:true,curve:"basis",nodeSpacing:28,rankSpacing:40,padding:8,useMaxWidth:false},
    sequence:{useMaxWidth:false,mirrorActors:false,wrap:false,width:118,actorMargin:22,boxMargin:6,messageMargin:26,messageFontSize:13,noteFontSize:13,actorFontSize:13,showSequenceNumbers:true},
    state:{useMaxWidth:false}};
}
// shrink to the frame when only slightly wider (ratio >= 0.6), else natural size and the frame scrolls
function fit(canvas){
  const svg=canvas.querySelector("svg");if(!svg)return;
  const vb=svg.viewBox&&svg.viewBox.baseVal, nat=vb&&vb.width?vb.width:svg.getBoundingClientRect().width, room=canvas.clientWidth;
  svg.style.maxWidth="none";svg.style.width=(nat>room&&room/nat>=0.6?room:nat)+"px";
}
let zoomEl=null;
function closeZoom(){if(zoomEl){zoomEl.remove();zoomEl=null}}
function openZoom(svg){
  if(!svg)return;closeZoom();
  const copy=svg.cloneNode(true), vb=svg.viewBox&&svg.viewBox.baseVal;
  copy.removeAttribute("style");if(vb&&vb.width){copy.setAttribute("width",Math.round(vb.width));copy.removeAttribute("height")}
  const x=el("button","dg-zx","Đóng");x.type="button";x.onclick=closeZoom;
  const body=el("div","dg-zbody");body.append(copy);
  zoomEl=el("div","dg-zoom");zoomEl.setAttribute("role","dialog");zoomEl.setAttribute("aria-modal","true");
  zoomEl.append(x,body);zoomEl.onclick=e=>{if(e.target===zoomEl||e.target===body)closeZoom()};
  document.body.append(zoomEl);x.focus();
}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeZoom()});

const figs=new Set(); let queue=Promise.resolve();
function drawFig(f){
  const src=f.src+(f.defs?"\n"+classDefs():"");
  queue=queue.then(()=>{
    if(!f.canvas.isConnected)return;
    mermaid.initialize(mmConfig());
    return mermaid.render("mm"+(++mmN),src).then(r=>{f.canvas.innerHTML=r.svg;fit(f.canvas)})
      .catch(err=>{f.canvas.replaceChildren(el("p","err","Mermaid: "+(err&&err.message||err)),el("pre","",f.src))});
  });
}
/* details: {title, groups:[[heading, [[label,text],..]],..]} -> side table next to the figure */
function sidePanel(d){
  const side=el("aside","dg-side"), t=el("table"), h=el("tr"), th=el("th","",d.title);
  th.colSpan=2;h.append(th);t.append(h);
  d.groups.forEach(([head,rows])=>{
    const g=el("tr","grp"), c=el("td","",head);c.colSpan=2;g.append(c);t.append(g);
    rows.forEach(([k,v])=>{const tr=el("tr"), a=el("td","",k), b=el("td");inline(b,v);tr.append(a,b);t.append(tr)});
  });
  side.append(t);return side;
}
const detailsOf=(b,items)=>{
  const groups=items.map(n=>[(n.text||n.id).split("\n")[0],n.details]).filter(g=>g[1]&&g[1].length);
  return groups.length?{title:b.details_title||"Bên trong các khối",groups}:null;
};
function mmFigure(src,caption,defs,details){
  const fig=el("figure","dg"+(details?" dg-split":"")), canvas=el("div","dg-canvas"), bar=el("div","dg-tools");
  const zoom=el("button","","Phóng to"), code=el("button","","Mã nguồn");zoom.type=code.type="button";
  zoom.onclick=()=>openZoom(canvas.querySelector("svg"));
  const showSrc=()=>canvas.replaceChildren(el("pre","fallback",src));
  code.onclick=()=>{try{navigator.clipboard.writeText(src).then(()=>{code.textContent="Đã chép";setTimeout(()=>{code.textContent="Mã nguồn"},1600)},showSrc)}catch{showSrc()}};
  bar.append(zoom,code);
  if(details){const main=el("div","dg-main");main.append(canvas,bar);fig.append(main,sidePanel(details))}else fig.append(canvas,bar);
  if(caption)fig.append(el("figcaption","",caption));
  if(!window.mermaid){showSrc();return fig}
  const f={src,canvas,defs:defs||/\n\s*class /.test(src)};figs.add(f);drawFig(f);return fig;
}
const redrawAll=()=>{for(const f of figs){if(f.canvas.isConnected)drawFig(f);else figs.delete(f)}};
new MutationObserver(redrawAll).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
if(matchMedia){const mq=matchMedia("(prefers-color-scheme: dark)");mq.addEventListener&&mq.addEventListener("change",redrawAll)}
let rt;addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{for(const f of figs)fit(f.canvas)},150)});
function mermaidBlock(code){return mmFigure(code)}

/* diagram / statemachine -> mermaid source. User text only ever lands inside quotes or after a colon, escaped by esc();
   ids are generated (n0, n1..), so no user text becomes mermaid syntax. */
const esc=s=>String(s).replace(/#/g,"#35;").replace(/"/g,"#quot;").replace(/</g,"#lt;").replace(/>/g,"#gt;").replace(/&/g,"#amp;").replace(/;/g,"#59;").replace(/`/g,"#96;");
const lines=l=>[].concat(l==null?[]:l).flatMap(x=>String(x).split("\n")).map(esc).join("<br/>");
const safeHref=h=>typeof h==="string"&&/^(https?:\/\/|#\/)/.test(h)&&!/[\s"]/.test(h)?h:null;  // only what linkFor resolved; no javascript:
const toneCls={ui:"ui",proc:"proc",store:"store",ok:"ok",bad:"bad",muted:"muted",warn:"dec"};
function clicks(items,linkFor,out){
  items.forEach((n,i)=>{const h=n.link&&linkFor?safeHref(linkFor(n.link)):null;if(h)out.push(`  click n${i} href "${h}" ${h[0]==="#"?"_self":"_blank"}`)});
}
function diagram(b,linkFor){
  const ix=new Map(b.nodes.map((n,i)=>[n.id,"n"+i])), out=["flowchart "+(b.dir||"TB")];
  b.nodes.forEach((n,i)=>{
    const t=lines(n.text||n.id)+(n.note?"<br/><small>"+lines(n.note)+"</small>":""), q=`"${t}"`;
    out.push("  n"+i+({decision:`{${q}}`,store:`[(${q})]`}[n.shape]||`[${q}]`));
    out.push(`  class n${i} ${toneCls[n.tone]||(n.shape==="store"?"store":"proc")}`);
  });
  (b.edges||[]).forEach(x=>{const [f,t,l]=Array.isArray(x)?x:[x.from,x.to,x.label];
    out.push(`  ${ix.get(f)} -->${l?`|"${lines(l)}"|`:""} ${ix.get(t)}`)});
  clicks(b.nodes,linkFor,out);
  return mmFigure(out.join("\n"),b.caption,true,detailsOf(b,b.nodes));
}
function statemachine(b,linkFor){
  const ss=b.states.map(s=>typeof s==="string"?{id:s}:s), ix=new Map(ss.map((s,i)=>[s.id,"n"+i])), fin=[].concat(b.final||[]);
  const out=["stateDiagram-v2","  direction "+(b.dir||"TB")];
  ss.forEach((s,i)=>out.push(`  state "${lines(s.text||s.id)+(s.note?"<br/>"+lines(s.note):"")}" as n${i}`));
  const il=b.initial_label?" : "+lines(b.initial_label):"";
  out.push(`  [*] --> ${ix.get(b.initial||ss[0].id)}${il}`);
  (b.transitions||[]).forEach(x=>{const [f,t,l]=Array.isArray(x)?x:[x.from,x.to,x.label];
    out.push(`  ${ix.get(f)} --> ${ix.get(t)}${l?" : "+lines(l):""}`)});
  fin.forEach(f=>out.push(`  ${ix.get(f)} --> [*]`));
  ss.forEach((s,i)=>{if(toneCls[s.tone])out.push(`  class n${i} ${toneCls[s.tone]}`)});
  return mmFigure(out.join("\n"),b.caption,true,detailsOf(b,ss));
}

function table(b){
  const t=el("table"), h=el("tr");
  b.head.forEach(x=>h.append(el("th","",x)));t.append(h);
  b.rows.forEach(r=>{const tr=el("tr");r.forEach(x=>tr.append(el("td","",x)));t.append(tr)});
  return t;
}

function query(b){
  const box=el("div","query"), qs=new URLSearchParams({src:b.src,...(b.where||{})});
  if(b.limit) qs.set("limit",b.limit);
  box.append(el("code","",b.src+" "+JSON.stringify(b.where||{})));
  const ul=el("ul");box.append(ul);
  get("/api/query?"+qs).then(rows=>{
    if(!rows.length) ul.append(el("li","","(không có dòng nào)"));
    rows.forEach(r=>ul.append(el("li","","#"+r.id+" "+r.title+" ["+r.status+"]")));
  }).catch(e=>ul.append(el("li","err",e.message)));
  return box;
}

function c4(b,project){
  const box=el("div","c4"), p=b.project||project;
  b.ids.forEach(id=>{
    const q="/c4?project="+enc(p)+"&focus="+enc(id);
    const f=el("iframe","c4frame");f.src=q+"&embed=1";f.loading="lazy";f.title=id;
    const a=el("a","","Mở viewer đầy đủ: "+id);a.href=q;a.target="_blank";a.rel="noopener";
    const para=el("p");para.append(a);box.append(f,para);
  });
  return box;
}

const R={
  md:b=>md(b.text),
  layers:b=>{const band=el("div","band");
    b.rows.forEach(r=>{const l=el("div","layer"),bx=el("div","boxes");l.append(el("h3","",r.title),bx);
      r.cells.forEach(c=>{const x=el("div","box"+(c.status==="plan"?" plan":""));x.append(el("b","",c.name));if(c.note)x.append(el("span","",c.note));bx.append(x)});
      band.append(l)});
    return band},
  mermaid:b=>mermaidBlock(b.code),
  swimlane:b=>swimlane(b),
  diagram:b=>diagram(b,l=>/^https?:\/\//.test(l)?l:null),
  statemachine:b=>statemachine(b,l=>/^https?:\/\//.test(l)?l:null),
  roadmap:b=>roadmap(b,l=>/^https?:\/\//.test(l)?l:null),
  table,
  legend:b=>{const d=el("div","legend");b.items.forEach(i=>{const c=el("span","chip "+(i.status==="plan"?"plan":"done"));c.append(el("i"),i.label);d.append(c)});return d},
  question:b=>{const d=el("div","question");d.append(el("p","q",b.q));
    b.options.forEach(o=>{const x=el("div","opt"+(o.label===b.recommend?" rec":""));
      x.append(el("b","",o.label));if(o.note)x.append(el("span","",o.note));if(o.label===b.recommend)x.append(el("em","","Đề xuất"));d.append(x)});
    return d},
};

function renderPage(pg,root=$app){
  document.title=pg.title+" · Strata";
  const head=el("header");head.append(el("h1","",pg.title),el("div","meta",pg.project+" · "+pg.kind+" · "+pg.updated_at));
  root.replaceChildren(head);
  pg.blocks.forEach(b=>{
    const s=el("section");
    try{s.append(b.type==="c4"?c4(b,pg.project):b.type==="query"?query(b):R[b.type]?R[b.type](b):el("p","err","unknown block type"))}
    catch(e){s.append(el("p","err",e.message))}
    root.append(s);
  });
}

function renderList(){
  const project=new URLSearchParams(location.search).get("project");
  document.title="Pages · Strata";
  get("/api/pages"+(project?"?project="+enc(project):"")).then(ps=>{
    const t=el("table"), h=el("tr");["project","slug","kind","title","updated"].forEach(x=>h.append(el("th","",x)));t.append(h);
    ps.forEach(p=>{const tr=el("tr"),a=el("a","",p.slug);a.href="/page/"+enc(p.project)+"/"+enc(p.slug);
      const c=el("td");c.append(a);tr.append(el("td","",p.project),c,el("td","",p.kind),el("td","",p.title),el("td","",p.updated_at));t.append(tr)});
    $app.replaceChildren(el("h1","","Pages"+(project?" · "+project:"")),ps.length?t:el("p","","Chưa có page nào."));
  }).catch(e=>$app.replaceChildren(el("p","err",e.message)));
}

// the app shell (app.html) sets STRATA_SHELL and calls renderPage(pg, container) itself
const parts=location.pathname.split("/").map(decodeURIComponent);
if(typeof STRATA_SHELL!=="undefined"){}
else if(parts[1]==="page"&&parts.length===4){
  const base="/api/page/"+enc(parts[2])+"/"+enc(parts[3]);
  let ver=null;
  const load=()=>get(base).then(renderPage).catch(e=>$app.replaceChildren(el("p","err",e.message)));
  // poll: re-render only when updated_at or the DB data_version changed
  const poll=()=>get(base+"/version").then(v=>{if(v.version!==ver){const first=ver===null;ver=v.version;if(!first)load()}}).catch(()=>{});
  load().then(poll);
  setInterval(poll,2000);
}else renderList();
