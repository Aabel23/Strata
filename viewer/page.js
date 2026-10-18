"use strict";
// All page text goes through textContent / text nodes. The only innerHTML is mermaid's own sanitized SVG.
const $app=document.getElementById("app");
const enc=encodeURIComponent;
try{const t=localStorage.getItem("strata-theme");if(t)document.documentElement.dataset.theme=t}catch{}

function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
const get=url=>fetch(url).then(r=>r.ok?r.json():Promise.reject(new Error(url+" → "+r.status)));

/* minimal markdown: headings (#..###), paragraphs, lists, ``` code, `code`, **bold**, [text](url) */
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
const LI=/^([-*]|\d+\.) /, HEAD=/^(#{1,3}) (.*)/;
function md(text){
  const root=el("div","md"), lines=String(text).split("\n"); let i=0;
  while(i<lines.length){
    const l=lines[i];
    if(!l.trim()){i++;continue}
    if(l.startsWith("```")){const buf=[];i++;while(i<lines.length&&!lines[i].startsWith("```"))buf.push(lines[i++]);i++;
      const pre=el("pre");pre.append(el("code","",buf.join("\n")));root.append(pre);continue}
    const h=l.match(HEAD);
    if(h){const e=el("h"+(h[1].length+1));inline(e,h[2]);root.append(e);i++;continue}
    if(LI.test(l)){const list=el(/^\d/.test(l)?"ol":"ul");
      while(i<lines.length&&LI.test(lines[i])){const li=el("li");inline(li,lines[i].replace(LI,""));list.append(li);i++}
      root.append(list);continue}
    const buf=[];
    while(i<lines.length&&lines[i].trim()&&!lines[i].startsWith("```")&&!HEAD.test(lines[i])&&!LI.test(lines[i]))buf.push(lines[i++]);
    const p=el("p");inline(p,buf.join(" "));root.append(p);
  }
  return root;
}

let mmN=0;
function mermaidBlock(code){
  const box=el("div","diagram"), fail=e=>{box.textContent="";box.append(el("p","err","Mermaid: "+(e&&e.message||e)),el("pre","",code))};
  if(!window.mermaid){fail("not loaded");return box}
  const dark=(document.documentElement.dataset.theme||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"))==="dark";
  mermaid.initialize({startOnLoad:false,securityLevel:"strict",theme:dark?"dark":"default"});
  mermaid.render("mm"+(++mmN),code).then(r=>{box.innerHTML=r.svg}).catch(fail);
  return box;
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
