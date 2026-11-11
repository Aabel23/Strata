/* Chat with Claude in the AI chat panel (the "Chat" tab).
   Strata runs one `claude -p` per chat in a git worktree of the open project (strata/chat_claude.py);
   this file sends messages through POST /api/chat and draws the reply from GET /api/chat/events.
   Claude asks before it runs a tool: those requests show up as cards with Allow / Deny. */
const CV={key:"strata-claude-chat-v1",sessions:{},cur:null,auth:null,authChecked:false,banner:null,stick:true};
const cvSleep=ms=>new Promise(r=>setTimeout(r,ms));
const CV_MAX_MESSAGE=100000, CV_MAX_TURNS=200;

function cvRecord(project,saved={}){
  return {project,sid:saved.sid||null,worktree:saved.worktree||"",turns:saved.turns&&typeof saved.turns==="object"?saved.turns:{},
    settings:saved.settings&&typeof saved.settings==="object"?saved.settings:null,
    seq:0,log:el("div","cv-thread"),busy:false,sending:false,polling:false,replayed:!saved.sid,
    assistant:null,tools:{},approvals:{},working:null,last:null};
}
function cvLoad(){
  try{const saved=JSON.parse(sessionStorage.getItem(CV.key)||"{}");
    for(const [p,v] of Object.entries(saved))if(v&&typeof v.sid==="string")CV.sessions[p]=cvRecord(p,v)}catch{}
}
function cvSave(){
  try{const out={};
    for(const [p,s] of Object.entries(CV.sessions))if(s.sid){
      const ids=Object.keys(s.turns);for(const id of ids.slice(0,Math.max(0,ids.length-CV_MAX_TURNS)))delete s.turns[id];
      out[p]={sid:s.sid,worktree:s.worktree,turns:s.turns,settings:s.settings};
    }
    sessionStorage.setItem(CV.key,JSON.stringify(out));
  }catch{}
}

/* ---------- drawing ---------- */
function cvAdd(s,node){
  if(s.working&&s.working.parentNode===s.log)s.log.insertBefore(node,s.working);else s.log.append(node);
  s.last=node;return node;
}
function cvScroll(s){
  if(CV.cur!==s||!CV.stick)return;
  const box=$("cv-log");box.scrollTop=box.scrollHeight;
}
function cvUser(s,text){return cvAdd(s,el("div","cv-msg cv-user",text))}
function cvNote(s,text,kind=""){cvScroll(s);return cvAdd(s,el("div","cv-note"+(kind?" "+kind:""),text))}
function cvWorking(s,on,label="Claude is working…"){
  if(on){
    if(!s.working){s.working=el("div","cv-working");s.working.append(el("i"),el("i"),el("i"),el("span"))}
    s.working.lastChild.textContent=label;s.log.append(s.working);
  }else if(s.working){s.working.remove();s.working=null}
}
function cvText(s,text,id){
  let a=s.assistant;
  if(!a||a.id!==id||s.last!==a.el){a=s.assistant={id,el:cvAdd(s,el("div","cv-msg cv-claude")),text:"",raf:0}}
  a.text+=text;
  if(!a.raf)a.raf=requestAnimationFrame(()=>{a.raf=0;a.el.replaceChildren(md(a.text));cvScroll(s)});
}
function cvArg(input){
  if(typeof input==="string")return input.split("\n")[0].slice(0,160);
  if(!input||typeof input!=="object")return "";
  const v=input.command??input.file_path??input.notebook_path??input.path??input.pattern??input.url??input.query??input.description??input.prompt??"";
  return String(v).split("\n")[0].slice(0,160);
}
const cvJson=v=>typeof v==="string"?v:JSON.stringify(v,null,2);
function cvTool(s,item){
  const card=el("details","cv-tool"),sum=el("summary");
  sum.append(el("b","",item.name||"tool"),el("span","cv-tool-arg",cvArg(item.input)),el("span","cv-tool-state","running"));
  card.append(sum,el("div","cv-label","Input"),el("pre","",cvJson(item.input)));
  if(item.id)s.tools[item.id]=card;
  cvAdd(s,card);
}
function cvToolDone(s,item){
  const card=s.tools[item.id];if(!card)return;delete s.tools[item.id];
  card.classList.add(item.error?"err":"ok");card.querySelector(".cv-tool-state").textContent=item.error?"error":"done";
  if(item.output)card.append(el("div","cv-label","Output"),el("pre","",String(item.output)));
}
function cvApproval(s,d,replay){
  const r=d.request||{},card=el("div","cv-approve");
  card.append(el("div","cv-approve-head","Claude wants to use "+(r.tool||"a tool")));
  if(r.what)card.append(el("p","",r.what));
  if(r.input!=null)card.append(el("pre","",cvJson(r.input)));
  const row=el("div","cv-approve-actions"),yes=el("button","cv-allow","Allow"),no=el("button","","Deny");
  yes.type=no.type="button";
  yes.onclick=()=>cvDecide(s,d.approval_id,true);no.onclick=()=>cvDecide(s,d.approval_id,false);
  row.append(yes,no);card.append(row);
  s.approvals[d.approval_id]=card;cvAdd(s,card);
  if(!replay&&CV.cur===s)yes.focus({preventScroll:true});
}
function cvApprovalEnd(s,id,label){
  const card=s.approvals[id];if(!card)return;delete s.approvals[id];
  card.classList.add("done");card.querySelector(".cv-approve-actions").replaceChildren(el("span","cv-approve-result",label));
}
async function cvDecide(s,id,allow){
  const card=s.approvals[id];if(!card)return;
  card.querySelectorAll("button").forEach(b=>b.disabled=true);
  try{const r=await api("/api/chat",{op:"decide",project:s.project,session_id:s.sid,approval_id:id,allow});
    cvApprovalEnd(s,id,r.accepted?(allow?"Allowed":"Denied"):"No longer waiting for an answer");
    $("cv-input").focus();
  }catch(error){card.querySelectorAll("button").forEach(b=>b.disabled=false);cvNote(s,"Could not send your answer: "+error.message,"bad")}
}
function cvTurnEnd(s,turn){
  const parts=[];
  if(turn.status&&turn.status!=="completed")parts.push(turn.status==="failed"?"Failed":turn.status);
  if(typeof turn.duration_ms==="number")parts.push((turn.duration_ms/1000).toFixed(1)+"s");
  if(typeof turn.steps==="number")parts.push(turn.steps+(turn.steps===1?" step":" steps"));
  if(typeof turn.cost_usd==="number")parts.push("$"+turn.cost_usd.toFixed(3));
  if(parts.length)cvAdd(s,el("div","cv-meta",parts.join(" · ")));
}
function cvEvent(s,ev,replay){
  const d=ev.data||{};
  switch(ev.type){
    case "turn_started":
      s.busy=true;s.assistant=null;
      if(d.turn_id&&s.turns[d.turn_id]&&!s.log.querySelector('[data-turn="'+CSS.escape(d.turn_id)+'"]'))cvUser(s,s.turns[d.turn_id]).dataset.turn=d.turn_id;
      cvWorking(s,true);break;
    case "text_delta":cvText(s,String(d.text||""),d.item_id);break;
    case "item_started":if(d.item&&d.item.type==="tool")cvTool(s,d.item);break;
    case "tool_completed":cvToolDone(s,d.item||{});break;
    case "approval_required":cvApproval(s,d,replay);break;
    case "approval_expired":cvApprovalEnd(s,d.approval_id,"Timed out: not allowed");break;
    case "approval_overflow":cvNote(s,"Too many permission requests at once; one was denied.","bad");break;
    case "error":case "protocol_error":cvNote(s,String(d.message||"Claude reported an error."),"bad");break;
    case "event_truncated":cvNote(s,"One update ("+(d.original_type||"event")+") was too large to show.");break;
    case "turn_cancelled":
      s.busy=false;s.assistant=null;cvWorking(s,false);
      for(const id of Object.keys(s.approvals))cvApprovalEnd(s,id,"Stopped");
      cvNote(s,"Stopped.");break;
    case "settings_changed":
      if(replay){s.settings={model:d.model||"",effort:d.effort||"",permission:d.permission||"auto"};cvNote(s,cvSettingsText(s.settings))}
      break;
    case "turn_completed":
      s.busy=false;s.assistant=null;cvWorking(s,false);
      for(const id of Object.keys(s.approvals))cvApprovalEnd(s,id,"Closed");
      cvTurnEnd(s,d.turn||{});break;
  }
  cvScroll(s);
}

/* ---------- talking to the server ---------- */
async function cvAlive(s){
  try{await liveGet(cvEventsUrl(s));return true}catch(error){return !(error.status===400||error.status===409)}
}
const cvEventsUrl=s=>"/api/chat/events?project="+encodeURIComponent(s.project)+"&session_id="+encodeURIComponent(s.sid)+"&after="+s.seq;
function cvForget(s,why){
  if(why)cvNote(s,why);
  s.sid=null;s.worktree="";s.seq=0;s.busy=false;s.assistant=null;cvWorking(s,false);
  for(const id of Object.keys(s.approvals))cvApprovalEnd(s,id,"Session ended");
  s.tools={};cvSave();cvWhere();
}
async function cvStart(s){
  cvWorking(s,true,"Starting Claude…");
  try{const want=cvPrefs();
    const r=await api("/api/chat",{op:"start",project:s.project,provider:"claude",...(want.model?{model:want.model}:{}),...(want.effort?{effort:want.effort}:{}),permission:want.permission});
    s.sid=r.session_id;s.worktree=r.worktree||"";s.seq=0;s.replayed=true;s.settings=r.settings||want;cvSave();cvWhere();
  }finally{if(!s.busy)cvWorking(s,false)}
}
async function cvPoll(s,replay=false){
  if(s.polling||!s.sid)return;s.polling=true;
  try{
    while(s.sid&&CV.sessions[s.project]===s){
      let data;
      try{data=await liveGet(cvEventsUrl(s))}
      catch(error){
        if(error.status===400||error.status===409){cvForget(s,"This chat ended (Strata restarted or the session closed). Your next message starts a new one.");break}
        await cvSleep(2000);continue;
      }
      for(const ev of data.events||[]){if(ev.seq>s.seq){s.seq=ev.seq;cvEvent(s,ev,replay)}}
      if(replay){replay=false;if(!s.busy)break}
      if(!s.busy&&!Object.keys(s.approvals).length)break;
      cvControls();
      await cvSleep(document.hidden?2000:450);
    }
  }finally{s.polling=false;cvControls()}
}
async function cvSend(){
  const s=CV.cur,input=$("cv-input"),text=input.value;
  if(!s||s.busy||s.sending||!text.trim())return;
  if(text.length>CV_MAX_MESSAGE){cvNote(s,"That message is too long (over 100,000 characters).","bad");return}
  s.sending=true;CV.stick=true;cvControls();
  const bubble=cvUser(s,text);input.value="";cvGrow();cvScroll(s);
  const turn=()=>api("/api/chat",{op:"turn",project:s.project,session_id:s.sid,message:text});
  try{
    if(!s.sid)await cvStart(s);
    let r;
    try{r=await turn()}
    catch(error){
      if(await cvAlive(s))throw error;
      cvForget(s,"The previous chat had ended, so this message starts a new one.");await cvStart(s);r=await turn();
    }
    bubble.dataset.turn=r.turn_id;s.turns[r.turn_id]=text;s.busy=true;cvSave();
    cvWorking(s,true);cvPoll(s);
  }catch(error){
    bubble.classList.add("failed");cvNote(s,"Message not sent: "+error.message,"bad");
    if(!input.value)input.value=text;cvGrow();
  }finally{s.sending=false;cvControls()}
}
async function cvStop(){
  const s=CV.cur;if(!s||!s.sid||!s.busy)return;
  $("cv-send").disabled=true;
  try{await api("/api/chat",{op:"cancel",project:s.project,session_id:s.sid});cvPoll(s)}
  catch(error){cvNote(s,"Could not stop: "+error.message,"bad")}
  finally{cvControls()}
}
async function cvNew(){
  const p=CUR.p;if(!p)return;
  const old=CV.sessions[p];
  if(old&&old.sid)api("/api/chat",{op:"close",project:p,session_id:old.sid}).catch(()=>{});
  CV.sessions[p]=cvRecord(p);cvSave();chatViewShow();$("cv-input").focus();
}

/* ---------- sign-in ---------- */
async function cvCheckAuth(){
  CV.authChecked=true;
  try{CV.auth=await liveGet("/api/chat/auth?provider=claude")}catch(error){CV.auth={status:"unavailable",message:error.message}}
  cvBanner();
}
function cvBanner(){
  const a=CV.auth;let b=null;
  if(a&&a.status==="login_required"){
    b=el("div","cv-banner");b.append(el("p","","Claude Code is not signed in on this machine."));
    const go=el("button","cv-allow","Sign in to Claude");go.type="button";go.onclick=()=>cvLogin(b);b.append(go);
  }else if(a&&a.status==="unavailable"){
    b=el("div","cv-banner bad",a.message||"Claude Code is not available here. Install it and run `claude` once in a terminal.");
  }
  CV.banner=b;cvRender();cvPicks();
}
async function cvLogin(box){
  box.replaceChildren(el("p","","Starting sign-in…"));
  try{const r=await api("/api/chat",{op:"login",provider:"claude"});
    const link=el("a","","Open the Claude sign-in page");link.href=r.url;link.target="_blank";link.rel="noopener noreferrer";
    const form=el("form","cv-code"),code=el("input"),ok=el("button","cv-allow","Finish");
    code.placeholder="Paste the code shown after you sign in";code.required=true;code.autocomplete="off";ok.type="submit";
    form.append(code,ok);
    form.onsubmit=async e=>{e.preventDefault();ok.disabled=true;
      try{const d=await api("/api/chat",{op:"login",provider:"claude",code:code.value.trim()});
        if(d.signed_in){CV.authChecked=false;await cvCheckAuth()}
        else box.replaceChildren(el("p","","Sign-in did not finish. Start again and paste the newest code."),cvRetry(box));
      }catch(error){box.replaceChildren(el("p","","Sign-in failed: "+error.message),cvRetry(box))}};
    box.replaceChildren(el("p","","Sign in on the page below, then paste the code it shows."),link,form);code.focus();
  }catch(error){box.replaceChildren(el("p","","Could not start sign-in: "+error.message),cvRetry(box))}
}
function cvRetry(box){const b=el("button","","Try again");b.type="button";b.onclick=()=>cvLogin(box);return b}

/* ---------- model, effort, permission mode ---------- */
// For a new chat: the last choice (localStorage). For a live chat: what that session runs with.
function cvPrefs(){
  let p={};try{p=JSON.parse(store.get("strata-chat-settings")||"{}")||{}}catch{}
  if(p.model===undefined)p.model=store.get("strata-chat-model")||"";  // the older model-only preference
  return {model:typeof p.model==="string"?p.model:"",effort:typeof p.effort==="string"?p.effort:"",permission:typeof p.permission==="string"&&p.permission?p.permission:"auto"};
}
const cvLabel=(list,id)=>((list||[]).find(x=>x.id===id)||{}).label||id;
function cvSettingsText(v){
  const a=CV.auth||{},model=v.model?cvLabel(a.models,v.model):"the default model";
  return "Now using "+model+" · "+cvLabel(a.efforts,v.effort||"").toLowerCase()+" · "+cvLabel(a.permissions,v.permission)+" mode. Applies from your next message.";
}
function cvPicks(){
  const a=CV.auth||{},s=CV.cur,ready=!!(a.models&&a.efforts&&a.permissions),v=s&&s.sid&&s.settings?s.settings:cvPrefs();
  const perm=$("cv-perm"),model=$("cv-model"),effort=$("cv-effort");
  if(ready){pickOptions(perm,a.permissions,v.permission);pickOptions(model,a.models,v.model);pickOptions(effort,a.efforts,v.effort);
    if(document.activeElement!==effort)effortFit(effort,a.models,model.value,v.effort)}
  perm.className="cv-pick mode-"+perm.value;
  for(const x of [perm,model,effort]){const o=x.options[x.selectedIndex];x.dataset.hint=o&&o.title||""}
  const off=!ready||!s||!!(s.busy||s.sending);
  for(const x of [perm,model,effort])x.disabled=off;
  const wait=s&&s.busy?"Wait for Claude to finish to change this. ":"";
  perm.title=wait+"Permission mode: "+(perm.dataset.hint||"")+" (Shift+Tab in the message box cycles it)";
  model.title=wait+"Model: "+(model.dataset.hint||"");
  effort.title=wait+"Effort: "+(effort.dataset.hint||"");
}
async function cvApplyPicks(){
  const a=CV.auth||{},s=CV.cur;
  const want={model:$("cv-model").value,permission:$("cv-perm").value||"auto"};
  want.effort=effortFit($("cv-effort"),a.models||[],want.model,$("cv-effort").value);
  $("cv-perm").className="cv-pick mode-"+want.permission;
  store.set("strata-chat-settings",JSON.stringify(want));
  if(!s||!s.sid)return;
  if(s.busy){cvPicks();return}
  try{const r=await api("/api/chat",{op:"settings",project:s.project,session_id:s.sid,...want});
    s.settings=r.settings||want;cvSave();cvNote(s,cvSettingsText(s.settings));
  }catch(error){cvNote(s,"Could not change the settings: "+error.message,"bad")}
  cvPicks();
}
function cvCycleMode(){
  const sel=$("cv-perm");if(sel.disabled||!sel.options.length)return;
  sel.selectedIndex=(sel.selectedIndex+1)%sel.options.length;cvApplyPicks();
}

/* ---------- panel ---------- */
function cvIntro(){
  const p=CUR.p,box=el("div","cv-empty");
  if(!p){box.append(el("p","","Open a project to chat with Claude. Claude works inside that project's code."));return box}
  box.append(el("strong","","Chat with Claude in "+p),
    el("p","","Claude works in its own git worktree of this project, so your working copy stays untouched. The mode next to Send sets what Claude may do without asking; anything it asks about waits for your Allow or Deny."));
  return box;
}
function cvRender(){
  $("cv-log").replaceChildren(...[CV.banner,CV.cur&&CV.cur.log,cvIntro()].filter(Boolean));
  if(CV.cur)cvScroll(CV.cur);
}
function cvWhere(){
  const s=CV.cur,n=$("cv-where");
  n.textContent=s?s.project+(s.sid?" · live":""):"No project";
  n.title=s&&s.worktree?"Worktree: "+s.worktree:"";
}
function cvControls(){
  const s=CV.cur,send=$("cv-send"),input=$("cv-input"),ok=!!s;
  input.disabled=!ok;input.placeholder=ok?"Message Claude…":"Open a project to chat";
  if(s&&s.busy){send.textContent="Stop";send.classList.add("stop");send.disabled=false}
  else{send.textContent=s&&s.sending?"Sending…":"Send";send.classList.remove("stop");send.disabled=!ok||!!(s&&s.sending)}
  $("cv-new").disabled=!s||(!s.sid&&!s.log.childElementCount);
  cvPicks();
}
function chatViewShow(){
  const p=CUR.p,s=p?(CV.sessions[p]||(CV.sessions[p]=cvRecord(p))):null;
  if(CV.cur!==s){CV.cur=s;CV.stick=true}
  cvRender();cvWhere();cvControls();
  if(s&&s.sid&&!s.replayed){s.replayed=true;cvPoll(s,true)}
  if(!CV.authChecked)cvCheckAuth();
}
function cvGrow(){const t=$("cv-input");t.style.height="auto";t.style.height=Math.min(t.scrollHeight,220)+"px"}

$("cv-form").onsubmit=e=>{e.preventDefault();if(CV.cur&&CV.cur.busy)cvStop();else cvSend()};
$("cv-input").addEventListener("keydown",e=>{
  if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing&&!e.altKey&&!e.ctrlKey&&!e.metaKey){e.preventDefault();if(!(CV.cur&&CV.cur.busy))cvSend()}
  if(e.key==="Tab"&&e.shiftKey&&!e.altKey&&!e.ctrlKey&&!e.metaKey){e.preventDefault();cvCycleMode()}
});
$("cv-input").addEventListener("input",cvGrow);
$("cv-new").onclick=cvNew;
$("cv-model").onchange=$("cv-effort").onchange=$("cv-perm").onchange=cvApplyPicks;
$("cv-log").addEventListener("scroll",()=>{const b=$("cv-log");CV.stick=b.scrollHeight-b.scrollTop-b.clientHeight<60});
cvLoad();
if(CHAT.open&&PANEL.mode==="chat")chatViewShow();
