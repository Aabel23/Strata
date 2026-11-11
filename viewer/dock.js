/* Live agent cards and the shared PTY terminal in the AI chat panel. */
const DOCK={open:store.get("strata-dock-open")!=="0",height:Math.max(160,Math.min(+store.get("strata-dock-height")||320,900)),session:null};
const CHAT={open:store.get("strata-chat-terminal-open")==="1"};
const AG={data:null,pollBusy:false,logRun:null,logSeq:0,logBusy:false,popupCard:null,popupTerm:null};
const TM={list:[],active:null,ready:false,opening:false,loading:null};
const PANEL={mode:store.get("strata-chat-mode")==="term"?"term":"chat"};

async function dockSession(){return DOCK.session||(DOCK.session=await get("/api/session"))}
async function liveGet(url){
  for(let attempt=0;attempt<2;attempt++){
    if(!TOK)TOK=(await get("/api/session")).token;
    const response=await fetch(url,{headers:{"X-Strata-Token":TOK}});
    if(response.status===403&&attempt===0){TOK=null;DOCK.session=null;continue}
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const error=new Error(data.error||("HTTP "+response.status));error.status=response.status;throw error}
    return data;
  }
  throw new Error("Strata session token could not be refreshed");
}
function dockNote(message,bad=false){const n=$("dock-status");n.textContent=message||"";n.classList.toggle("bad",bad)}
function dockApply(){
  $("dock-body").hidden=!DOCK.open;$("dock").classList.toggle("open",DOCK.open);
  $("dock").style.setProperty("--dock-height",DOCK.height+"px");
  $("dock-toggle").setAttribute("aria-expanded",String(DOCK.open));
  $("dock-toggle").replaceChildren(svg(S("0 0 16 16",DOCK.open?'<path d="M4 6.5 8 10.5l4-4"/>':'<path d="M4 9.5 8 5.5l4 4"/>','stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"')));
  $("chat-panel").hidden=!CHAT.open;$("shell").classList.toggle("chat-open",CHAT.open);
  $("chat-toggle").setAttribute("aria-expanded",String(CHAT.open));
  if(CHAT.open){panelApply();termShow()}
}
function dockSet(open){DOCK.open=open;store.set("strata-dock-open",open?"1":"0");dockApply()}
function chatSet(open){CHAT.open=open;store.set("strata-chat-terminal-open",open?"1":"0");dockApply();if(open)termFit()}
$("dock-toggle").onclick=()=>dockSet(!DOCK.open);
$("chat-toggle").onclick=()=>chatSet(!CHAT.open);
$("chat-close").onclick=()=>chatSet(false);
$("agent-popup-close").onclick=()=>$("agent-popup").close();
$("agent-popup").addEventListener("close",()=>{
  const t=AG.popupTerm;AG.popupTerm=null;AG.popupCard=null;AG.logRun=null;AG.logSeq=0;
  if(t){$("term-host").append(t.box);for(const x of TM.list)x.box.hidden=x!==TM.active;termFit()}
});
{let start=null;const handle=$("dock-resize");
  const size=h=>{DOCK.height=Math.max(160,Math.min(h,innerHeight-140));$("dock").style.setProperty("--dock-height",DOCK.height+"px");termFit()};
  handle.addEventListener("pointerdown",e=>{if(!DOCK.open)return;start={y:e.clientY,h:DOCK.height};handle.setPointerCapture(e.pointerId);document.body.classList.add("dock-resizing")});
  handle.addEventListener("pointermove",e=>{if(start)size(start.h+start.y-e.clientY)});
  const end=()=>{if(!start)return;start=null;document.body.classList.remove("dock-resizing");store.set("strata-dock-height",String(DOCK.height))};
  handle.addEventListener("pointerup",end);handle.addEventListener("pointercancel",end);
  handle.addEventListener("keydown",e=>{if(!["ArrowUp","ArrowDown"].includes(e.key))return;e.preventDefault();size(DOCK.height+(e.key==="ArrowUp"?24:-24));store.set("strata-dock-height",String(DOCK.height))});
}
{let start=null;const handle=$("chat-resize");
  const size=w=>{CHAT.width=Math.max(260,Math.min(w,innerWidth-420));$("shell").style.setProperty("--chat-width",CHAT.width+"px");termFit()};
  size(+store.get("strata-chat-width")||340);
  handle.addEventListener("pointerdown",e=>{start={x:e.clientX,w:CHAT.width};handle.setPointerCapture(e.pointerId);document.body.classList.add("chat-resizing")});
  handle.addEventListener("pointermove",e=>{if(start)size(start.w+start.x-e.clientX)});
  const end=()=>{if(!start)return;start=null;document.body.classList.remove("chat-resizing");store.set("strata-chat-width",String(CHAT.width))};
  handle.addEventListener("pointerup",end);handle.addEventListener("pointercancel",end);
  handle.addEventListener("keydown",e=>{if(!["ArrowLeft","ArrowRight"].includes(e.key))return;e.preventDefault();size(CHAT.width+(e.key==="ArrowLeft"?24:-24));store.set("strata-chat-width",String(CHAT.width))});
}
document.addEventListener("keydown",e=>{if(e.ctrlKey&&!e.altKey&&!e.metaKey&&e.key==="`"){e.preventDefault();e.stopPropagation();chatSet(!CHAT.open)}},true);

/* ---------- cards ---------- */
/* Fill a <select> from [{id,label,group?}], grouping by `group` (model families). Shared with chat.js. */
function pickOptions(select,items,current){
  const key=JSON.stringify(items.map(i=>[i.id,i.label,i.group||"",i.hint||""]));
  if(select.dataset.key!==key){
    select.dataset.key=key;const groups=new Map(),out=[];
    for(const i of items){
      const o=new Option(i.label||i.id||"Default",i.id);if(i.hint)o.title=i.hint;
      if(!i.group){out.push(o);continue}
      if(!groups.has(i.group)){const g=document.createElement("optgroup");g.label=i.group;groups.set(i.group,g);out.push(g)}
      groups.get(i.group).append(o);
    }
    select.replaceChildren(...out);
  }
  if(document.activeElement!==select)select.value=current||"";
}
/* Only the effort levels the chosen model takes stay enabled; "" (default) always does. Returns a valid effort. */
function effortFit(select,models,model,effort){
  const m=models.find(x=>x.id===(model||""))||{efforts:[]};
  for(const o of select.options)o.disabled=!!o.value&&!m.efforts.includes(o.value);
  const ok=!effort||m.efforts.includes(effort)?effort||"":"";
  select.value=ok;select.title=m.efforts.length?"How hard Claude thinks":"This model has no effort setting";
  return ok;
}
function agentRender(){
  const d=AG.data;if(!d)return;
  const cards=d.sessions||[],p=CUR.p,auto=$("agent-auto");
  $("dock-agent-count").textContent=String(cards.length);$("dock-agent-count").classList.toggle("on",cards.length>0);
  auto.disabled=!p||!DOCK.session||!DOCK.session.edit;auto.checked=!!(p&&d.auto[p]);
  $("agent-auto-text").textContent=p?"Auto-run approved tasks in "+p:"Choose a project to switch on auto-run";
  pickOptions($("agent-model"),d.models,d.model);pickOptions($("agent-effort"),d.efforts,d.effort);
  if(document.activeElement!==$("agent-effort"))effortFit($("agent-effort"),d.models,$("agent-model").value,d.effort);
  if(!$("dock-status").classList.contains("bad"))dockNote(cards.length?cards.length+" active session"+(cards.length===1?"":"s"):"No active agents");
  const byId=new Map(cards.map(c=>[c.id,c]));
  const children=new Map(),roots=[];
  for(const c of cards){
    if(c.parent&&byId.has(c.parent)){const list=children.get(c.parent)||[];list.push(c);children.set(c.parent,list)}
    else roots.push(c);
  }
  const makeCard=c=>{
    const b=el("button","agent-card");b.type="button";
    const head=el("span","agent-card-title"),dot=el("i");head.append(dot,c.kind+" · "+(c.status==="running"?"working":c.status));
    const task=el("span","agent-card-task",c.task?"Task: #"+c.task.id+" "+c.task.title:"Task: —");
    const branch=el("span","agent-card-branch","Branch: "+(c.branch||"—"));
    b.append(head,task,branch);b.title=c.terminal?"Open live terminal":"Open agent details";
    b.onclick=()=>agentOpen(c);return b;
  };
  const seen=new Set();
  const makeNode=c=>{
    if(seen.has(c.id))return null;
    seen.add(c.id);
    const node=el("div","agent-node");node.append(makeCard(c));
    const descendants=(children.get(c.id)||[]).map(makeNode).filter(Boolean);
    if(descendants.length){const group=el("div","agent-children");group.append(...descendants);node.append(group)}
    return node;
  };
  const rows=roots.map(makeNode).filter(Boolean);
  for(const c of cards)if(!seen.has(c.id))rows.push(makeNode(c));
  $("agent-cards").replaceChildren(...(rows.length?rows:[el("p","agent-empty","No active agents. Start Claude or Codex in the AI chat terminal to see a card here.")]));
}
async function agentPoll(){
  if(AG.pollBusy||document.hidden)return;AG.pollBusy=true;
  try{await dockSession();AG.data=await liveGet("/api/agents");$("dock-status").classList.remove("bad");agentRender()}
  catch(error){dockNote("Agents unavailable: "+error.message,true)}
  finally{AG.pollBusy=false}
}
async function agentOpen(card){
  if($("agent-popup").open)$("agent-popup").close();
  AG.popupCard=card;
  $("agent-popup-title").textContent=card.kind+" · "+(card.status==="running"?"working":card.status);
  $("agent-popup-meta").textContent=(card.task?"Task #"+card.task.id+" · ":"")+"Branch: "+(card.branch||"—")+(card.source==="subagent"?" · shared parent terminal":"")+(card.cwd?" · "+card.cwd:"");
  $("agent-popup-terminal").hidden=!card.terminal;$("agent-popup-log").hidden=!!card.terminal;
  if(card.terminal){
    chatSet(true);await termShow();
    const t=TM.list.find(x=>x.id===card.terminal);
    if(t){AG.popupTerm=t;$("agent-popup-terminal").replaceChildren(t.box);t.box.hidden=false;$("agent-popup").showModal();termFit();t.x.focus();return}
  }
  const text=card.run?"Reading task agent output…":card.source==="external"||card.source==="subagent"?"This session is running in an external terminal. Its live terminal cannot be attached without a shared PTY or tmux.":"This run uses a headless process; its activity log is shown here.";
  $("agent-popup-log").textContent=text;$("agent-popup-terminal").hidden=true;$("agent-popup-log").hidden=false;
  $("agent-popup").showModal();if(card.run)agentLogPoll();
}
async function agentLogPoll(){
  const run=AG.popupCard?.run;if(!run||AG.logBusy||document.hidden)return;
  const box=$("agent-popup-log");if(AG.logRun!==run){AG.logRun=run;AG.logSeq=0;box.replaceChildren()}
  AG.logBusy=true;
  try{const data=await liveGet("/api/agent/log?run="+encodeURIComponent(run)+"&after="+AG.logSeq);
    if(AG.logRun!==run)return;
    for(const e of data.events){if(e.seq<=AG.logSeq)continue;AG.logSeq=e.seq;
      box.append(el("div","log-row",new Date(e.t*1000).toLocaleTimeString()+"  "+e.text))}
    box.scrollTop=box.scrollHeight;
  }catch(error){if(error.status!==404)dockNote("Agent log unavailable: "+error.message,true)}
  finally{AG.logBusy=false}
}
async function agentOp(body,button){
  if(button)button.disabled=true;
  try{const result=await api("/api/agent",body);$("dock-status").classList.remove("bad");await agentPoll();return result}
  catch(error){dockNote(error.message,true);return null}
  finally{if(button)button.disabled=false}
}
async function agentRun(item,button){const result=await agentOp({op:"run",item},button);dockSet(true);if(result)await agentPoll()}
$("agent-auto").onchange=()=>{if(CUR.p)agentOp({op:"auto",project:CUR.p,on:$("agent-auto").checked})};
$("agent-model").onchange=$("agent-effort").onchange=()=>{
  const models=(AG.data&&AG.data.models)||[],effort=effortFit($("agent-effort"),models,$("agent-model").value,$("agent-effort").value);
  agentOp({op:"settings",model:$("agent-model").value,effort});
};
function dockProjectChanged(){agentRender();if(CHAT.open&&PANEL.mode==="chat"&&typeof chatViewShow==="function")chatViewShow()}

/* ---------- terminal ---------- */
function termTheme(){return {background:tok("--bg-0")||tok("--bg"),foreground:tok("--fg"),cursor:tok("--accent"),cursorAccent:tok("--bg"),selectionBackground:tok("--sel")}}
function termNote(message){$("term-note").textContent=message||"";panelApply()}
/* The panel body shows either the Claude chat (first tab) or the active terminal. */
function panelApply(){
  const chat=PANEL.mode==="chat",note=$("term-note").textContent;
  $("chat-view").hidden=!chat;$("term-note").hidden=chat||!note;$("term-host").hidden=chat||!!note;
  termTabs();if(chat){if(typeof chatViewShow==="function")chatViewShow()}else termFit();
}
function panelMode(mode){
  PANEL.mode=mode;store.set("strata-chat-mode",mode);panelApply();
  if(mode==="term"){if(TM.active)TM.active.x.focus();else if(TM.ready)termOpen();else termShow()}
}
function termTabs(){
  const chatTab=el("button","term-tab"+(PANEL.mode==="chat"?" sel":""),"Chat");chatTab.type="button";chatTab.title="Chat with Claude";chatTab.onclick=()=>panelMode("chat");
  const tabs=TM.list.map((t,i)=>{const b=el("button","term-tab"+(PANEL.mode==="term"&&t===TM.active?" sel":""),(t.title||"shell")+" "+(i+1)+(t.closed?" (exited)":""));b.type="button";b.onclick=()=>termActivate(t);return b});
  const add=el("button","ib","");add.type="button";add.title="New terminal";add.setAttribute("aria-label","New terminal");add.append(icon("plus"));add.onclick=()=>termOpen();
  const kill=el("button","ib","×");kill.type="button";kill.title="Close this terminal";kill.setAttribute("aria-label","Close this terminal");kill.disabled=PANEL.mode!=="term"||!TM.active;kill.onclick=()=>termClose(TM.active);
  add.onclick=()=>{PANEL.mode="term";store.set("strata-chat-mode","term");panelApply();termOpen()};
  $("term-tabs").replaceChildren(chatTab,...tabs,add,kill);
}
function termFit(){
  const t=AG.popupTerm||TM.active;if(!t||!t.box.clientWidth)return;
  try{t.fit.fit()}catch{return}
  if(t.cols!==t.x.cols||t.rows!==t.x.rows){t.cols=t.x.cols;t.rows=t.x.rows;if(!t.closed)api("/api/term",{op:"resize",id:t.id,cols:t.cols,rows:t.rows}).catch(()=>{})}
}
function termActivate(t){
  if($("agent-popup").open&&AG.popupTerm)$("agent-popup").close();
  TM.active=t;for(const x of TM.list)x.box.hidden=x!==t;
  if(!t){PANEL.mode="chat";store.set("strata-chat-mode","chat")}else if(PANEL.mode!=="term"){PANEL.mode="term";store.set("strata-chat-mode","term")}
  panelApply();if(t){termFit();t.x.focus()}
}
function termAttach(id,title){
  const box=el("div","term-box");$("term-host").append(box);
  const x=new Terminal({fontFamily:tok("--mono")||"monospace",fontSize:13,lineHeight:1.2,cursorBlink:true,scrollback:8000,theme:termTheme(),allowProposedApi:false});
  const fit=new FitAddon.FitAddon();x.loadAddon(fit);x.open(box);
  const t={id,title,x,fit,box,next:0,closed:false,pending:"",sending:false,cols:0,rows:0};
  const flush=async()=>{if(t.sending||!t.pending||t.closed)return;t.sending=true;
    const data=t.pending.slice(0,60000);t.pending=t.pending.slice(data.length);
    try{await api("/api/term",{op:"input",id:t.id,data})}catch(error){t.closed=true;x.write("\r\n\x1b[31m[terminal closed: "+error.message+"]\x1b[0m\r\n");termTabs()}
    t.sending=false;if(t.pending)flush()};
  x.onData(d=>{t.pending+=d;flush()});
  (async()=>{while(!t.gone){try{
      const r=await liveGet("/api/term/read?id="+encodeURIComponent(t.id)+"&after="+t.next);
      if(r.data)x.write(Uint8Array.from(atob(r.data),c=>c.charCodeAt(0)));
      t.next=r.next;if(r.closed){t.closed=true;x.write("\r\n\x1b[2m[shell exited]\x1b[0m\r\n");termTabs();return}
    }catch(error){if(error.status===404||error.status===403){t.closed=true;x.write("\r\n\x1b[2m[terminal is gone]\x1b[0m\r\n");termTabs();return}
      await new Promise(r=>setTimeout(r,1500))}}})();
  TM.list.push(t);return t;
}
async function termOpen(){if(TM.opening)return;TM.opening=true;
  try{const r=await api("/api/term",{op:"open",...(CUR.p?{project:CUR.p}:{}),cols:100,rows:28});termActivate(termAttach(r.id,CUR.p||"shell"))}
  catch(error){dockNote("Terminal: "+error.message,true);if(!TM.list.length)termNote("The terminal could not start: "+error.message)}
  finally{TM.opening=false}
}
async function termClose(t){if(!t)return;if(AG.popupTerm===t)$("agent-popup").close();t.gone=true;
  if(!t.closed)await api("/api/term",{op:"close",id:t.id}).catch(()=>{});
  t.x.dispose();t.box.remove();TM.list=TM.list.filter(x=>x!==t);termActivate(TM.list[TM.list.length-1]||null)}
async function termShow(){
  if(TM.ready){termFit();return}
  if(TM.loading)return TM.loading;
  TM.loading=(async()=>{try{const session=await dockSession();
      if(!session.terminal)return termNote("Terminal is disabled on this address.");
      if(typeof Terminal!=="function"||typeof FitAddon!=="object")return termNote("Terminal library did not load. Reload the page.");
      termNote("");const r=await api("/api/term",{op:"list"});
      for(const t of r.terminals)termAttach(t.id,t.title||"shell");
      if(PANEL.mode==="chat"){TM.active=TM.list[0]||null;for(const x of TM.list)x.box.hidden=x!==TM.active;panelApply()}
      else if(TM.list.length)termActivate(TM.list[0]);else await termOpen();
      TM.ready=true;
    }catch(error){TM.ready=false;termNote("Terminal unavailable: "+error.message)}
    finally{TM.loading=null}})();
  return TM.loading;
}
new ResizeObserver(()=>termFit()).observe($("term-host"));
new ResizeObserver(()=>termFit()).observe($("agent-popup-terminal"));
new MutationObserver(()=>{for(const t of TM.list)t.x.options.theme=termTheme()}).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});

dockApply();dockSession().then(()=>agentPoll(),()=>{});
setInterval(agentPoll,2500);setInterval(agentLogPoll,1200);
document.addEventListener("visibilitychange",()=>{if(!document.hidden){agentPoll();agentLogPoll()}});
