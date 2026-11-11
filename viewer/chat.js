/* Chat with Claude in the AI chat panel (the "Chat" tab).
   Strata runs one `claude -p` per chat in a git worktree of the open project (strata/chat_claude.py);
   this file sends messages through POST /api/chat and draws the reply from GET /api/chat/events.
   Claude asks before it runs a tool: those requests show up as cards with Allow / Deny.
   Every chat is saved by the server as a note in the user's vault (strata/chat_history.py); "History" lists
   them (GET /api/chat/history) and reopening one continues it. Images pasted into the message box go with the turn. */
const CV={key:"strata-claude-chat-v1",sessions:{},cur:null,auth:null,authChecked:false,banner:null,stick:true,hist:null};
const cvSleep=ms=>new Promise(r=>setTimeout(r,ms));
const CV_MAX_MESSAGE=100000, CV_MAX_TURNS=200;
const CV_IMG_TYPES=["image/png","image/jpeg","image/gif","image/webp"], CV_MAX_IMAGES=4, CV_MAX_IMAGE=3.5*1024*1024;

// hid: id of this chat's note in the history (set by the server on start, or picked from History to continue it).
// images: pasted images waiting to go with the next message, [{media_type,data(base64),url(data URL)}].
function cvRecord(project,saved={}){
  return {project,sid:saved.sid||null,hid:saved.hid||null,images:[],worktree:saved.worktree||"",turns:saved.turns&&typeof saved.turns==="object"?saved.turns:{},
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
      out[p]={sid:s.sid,hid:s.hid,worktree:s.worktree,turns:s.turns,settings:s.settings};
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
function cvThumb(box,src){
  const img=el("img","cv-img");img.alt="Attached image";if(src)img.src=src;
  img.title="Click to enlarge";img.onclick=()=>img.classList.toggle("big");
  box.append(img);return img;
}
function cvUser(s,text,images){
  const bubble=el("div","cv-msg cv-user",text);
  for(const src of images||[])cvThumb(bubble,src);
  return cvAdd(s,bubble);
}
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
    const start=resume=>api("/api/chat",{op:"start",project:s.project,provider:"claude",...(want.model?{model:want.model}:{}),...(want.effort?{effort:want.effort}:{}),permission:want.permission,...(resume?{resume}:{})});
    let r;
    try{r=await start(s.hid)}
    catch(error){  // the saved chat cannot be continued (its note is gone, or it is open in another tab)
      if(!s.hid)throw error;
      s.hid=null;r=await start(null);cvNote(s,"The earlier chat could not be reopened, so this continues as a new one.");
    }
    if(r.resumed===false)cvNote(s,"The worktree of the earlier chat is no longer on disk. Claude continues in a new one and does not remember the earlier messages.");
    s.sid=r.session_id;s.hid=r.history||null;s.worktree=r.worktree||"";s.seq=0;s.replayed=true;s.settings=r.settings||want;cvSave();cvWhere();
  }finally{if(!s.busy)cvWorking(s,false)}
}
async function cvPoll(s,replay=false){
  if(s.polling||!s.sid)return;s.polling=true;
  try{
    while(s.sid&&CV.sessions[s.project]===s){
      let data;
      try{data=await liveGet(cvEventsUrl(s))}
      catch(error){
        if(error.status===400||error.status===409){cvForget(s,"This chat's session ended (Strata restarted or it was closed). Your next message "+(s.hid?"reopens it.":"starts a new one."));break}
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
  const s=CV.cur,input=$("cv-input"),text=input.value,images=s?s.images:[];
  if(!s||s.busy||s.sending||(!text.trim()&&!images.length))return;
  if(text.length>CV_MAX_MESSAGE){cvNote(s,"That message is too long (over 100,000 characters).","bad");return}
  s.sending=true;CV.stick=true;
  if(CV.hist){CV.hist=null;cvRender()}
  const bubble=cvUser(s,text,images.map(i=>i.url));input.value="";s.images=[];cvAttachDraw();cvControls();cvGrow();cvScroll(s);
  const turn=()=>api("/api/chat",{op:"turn",project:s.project,session_id:s.sid,message:text,...(images.length?{images:images.map(i=>({media_type:i.media_type,data:i.data}))}:{})});
  try{
    if(!s.sid)await cvStart(s);
    let r;
    try{r=await turn()}
    catch(error){
      if(await cvAlive(s))throw error;
      cvForget(s,s.hid?"The chat's session had ended, so it was reopened for this message.":"The previous chat had ended, so this message starts a new one.");await cvStart(s);r=await turn();
    }
    // kept for redrawing after a page reload; the images themselves stay out of sessionStorage (they are in the history note)
    const count=images.length?"["+images.length+(images.length>1?" images]":" image]"):"";
    bubble.dataset.turn=r.turn_id;s.turns[r.turn_id]=text+(text&&count?"\n":"")+count;s.busy=true;cvSave();
    cvWorking(s,true);cvPoll(s);
  }catch(error){
    bubble.classList.add("failed");cvNote(s,"Message not sent: "+error.message,"bad");
    if(!input.value)input.value=text;
    if(!s.images.length){s.images=images;if(CV.cur===s)cvAttachDraw()}
    cvGrow();
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
  CV.sessions[p]=cvRecord(p);CV.hist=null;cvSave();chatViewShow();$("cv-input").focus();
}

/* ---------- pasted images ---------- */
const cvDataUrl=blob=>new Promise((ok,bad)=>{const r=new FileReader();r.onload=()=>ok(r.result);r.onerror=()=>bad(r.error);r.readAsDataURL(blob)});
// Re-encode what cannot go as it is (another format, or too large): at most 2000px on the long side, JPEG on white.
async function cvShrink(blob){
  const bmp=await createImageBitmap(blob),k=Math.min(1,2000/Math.max(bmp.width,bmp.height));
  const c=document.createElement("canvas"),g=c.getContext("2d");
  c.width=Math.max(1,Math.round(bmp.width*k));c.height=Math.max(1,Math.round(bmp.height*k));
  g.fillStyle="#fff";g.fillRect(0,0,c.width,c.height);g.drawImage(bmp,0,0,c.width,c.height);
  return new Promise(ok=>c.toBlob(ok,"image/jpeg",.9));
}
async function cvAttach(s,file){
  if(s.images.length>=CV_MAX_IMAGES){cvNote(s,"A message takes at most "+CV_MAX_IMAGES+" images.","bad");return}
  try{
    let blob=file;
    if(!CV_IMG_TYPES.includes(blob.type)||blob.size>CV_MAX_IMAGE)blob=await cvShrink(blob);
    if(!blob||blob.size>CV_MAX_IMAGE)throw new Error("it is too large");
    const url=await cvDataUrl(blob);
    if(s.images.length>=CV_MAX_IMAGES)return;
    s.images.push({media_type:blob.type,data:url.slice(url.indexOf(",")+1),url});
  }catch(error){cvNote(s,"Could not attach that image: "+(error&&error.message||"it could not be read"),"bad")}
  if(CV.cur===s)cvAttachDraw();
}
function cvAttachDraw(){
  const s=CV.cur,box=$("cv-attach"),list=s?s.images:[];
  box.hidden=!list.length;
  box.replaceChildren(...list.map((image,i)=>{
    const chip=el("span","cv-chip"),pic=el("img"),x=el("button","","×");
    pic.src=image.url;pic.alt="Image "+(i+1)+" to send";
    x.type="button";x.title="Remove this image";x.setAttribute("aria-label","Remove image "+(i+1));
    x.onclick=()=>{const at=s.images.indexOf(image);if(at>=0)s.images.splice(at,1);cvAttachDraw();$("cv-input").focus()};
    chip.append(pic,x);return chip;
  }));
}

/* ---------- history: earlier chats, saved as notes in the vault ---------- */
const cvWhen=t=>new Date(t*1000).toLocaleString([],{dateStyle:"medium",timeStyle:"short"});
const cvHistUrl=(p,id,image)=>"/api/chat/history?project="+encodeURIComponent(p)+(id?"&id="+encodeURIComponent(id):"")+(image?"&image="+encodeURIComponent(image):"");
async function cvHistory(){
  const p=CUR.p;if(!p)return;
  if(CV.hist){CV.hist=null;cvRender();cvControls();return}
  const box=CV.hist=el("div","cv-hist");box.append(el("p","cv-note","Loading…"));cvRender();cvControls();
  try{
    const r=await liveGet(cvHistUrl(p));
    if(CV.hist!==box)return;
    if(!r.enabled){box.replaceChildren(el("p","cv-hist-info","Chat history is off: Strata found no vault folder on the server (~/.secondbrain, or the folder named by STRATA_CHAT_VAULT)."));return}
    const where=el("p","cv-hist-info","Chats are saved as notes in "+r.folder);
    if(!r.chats.length){box.replaceChildren(where,el("p","cv-hist-info","No saved chats for this project yet. A chat is saved from its first message."));return}
    box.replaceChildren(where,...r.chats.map(c=>{
      const row=el("button","cv-hist-row");row.type="button";
      row.append(el("span","cv-hist-title",c.title),el("span","cv-hist-when",(c.live?"open now · ":"")+cvWhen(c.updated)));
      row.onclick=()=>cvOpen(p,c.id,box);return row;
    }));
  }catch(error){if(CV.hist===box)box.replaceChildren(el("p","cv-note bad","Could not load the history: "+error.message))}
}
function cvPaint(s,chat){
  let bubble=null;
  for(const b of chat.blocks||[]){
    if(b.kind==="user")bubble=cvUser(s,b.text||"");
    else if(b.kind==="image"){
      const img=cvThumb(bubble||(bubble=cvUser(s,"")),"");
      liveGet(cvHistUrl(s.project,chat.id,b.image)).then(r=>{img.src="data:"+r.media_type+";base64,"+r.data}).catch(()=>{img.alt="Image not available"});
    }
    else if(b.kind==="claude"){cvAdd(s,el("div","cv-msg cv-claude")).append(md(b.text||""));bubble=null}
    else if(b.kind==="tool")cvAdd(s,el("div","cv-hist-tool",String(b.text||"").replace(/`/g,"")));
    else cvNote(s,b.text||"");
  }
}
async function cvOpen(p,hid,box){
  const old=CV.sessions[p],say=text=>box.prepend(el("p","cv-note bad",text));
  if(old&&old.hid===hid&&(old.sid||old.log.childElementCount)){CV.hist=null;chatViewShow();return}
  if(old&&(old.busy||old.sending)){say("Claude is still working in the open chat. Stop it or wait, then pick a chat.");return}
  let chat;
  try{chat=await liveGet(cvHistUrl(p,hid))}catch(error){say("Could not open that chat: "+error.message);return}
  if(CUR.p!==p||CV.hist!==box)return;
  if(old&&old.sid)api("/api/chat",{op:"close",project:p,session_id:old.sid}).catch(()=>{});
  const s=CV.sessions[p]=cvRecord(p,{hid});
  cvPaint(s,chat);cvNote(s,"Saved chat from "+(chat.started||"earlier").replace("T"," ")+". Your next message continues it.");
  CV.hist=null;cvSave();chatViewShow();$("cv-input").focus();
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
// Fill a <select> from [{id,label,group?,hint?}], grouping by `group` (model families).
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
  if(document.activeElement!==select){select.value=current||"";if(select.selectedIndex<0)select.value=""}
}
// Only the effort levels the chosen model takes stay enabled; "" (default) always does. Returns a valid effort.
function effortFit(select,models,model,effort){
  const m=models.find(x=>x.id===(model||""))||{efforts:["low","medium","high","xhigh","max"]};
  for(const o of select.options)o.disabled=!!o.value&&!m.efforts.includes(o.value);
  const ok=!effort||m.efforts.includes(effort)?effort||"":"";
  select.value=ok;return ok;
}
// For a new chat: the last choice (localStorage). For a live chat: what that session runs with.
function cvPrefs(){
  let p={};try{p=JSON.parse(store.get("strata-chat-settings")||"{}")||{}}catch{}
  if(p.model===undefined)p.model=store.get("strata-chat-model")||"";  // the older model-only preference
  p.model={fable:"claude-fable-5-2",opus:"claude-opus-5-5",sonnet:"claude-sonnet-5-5",haiku:"claude-haiku-5-5"}[p.model]||p.model;  // old alias choices show as their version
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
  $("cv-log").replaceChildren(...(CV.hist?[CV.hist]:[CV.banner,CV.cur&&CV.cur.log,cvIntro()]).filter(Boolean));
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
  const hist=$("cv-history");hist.disabled=!s;hist.textContent=CV.hist?"Back to chat":"History";hist.setAttribute("aria-pressed",String(!!CV.hist));
  cvPicks();
}
function chatViewShow(){
  const p=CUR.p,s=p?(CV.sessions[p]||(CV.sessions[p]=cvRecord(p))):null;
  if(CV.cur!==s){CV.cur=s;CV.stick=true;CV.hist=null}
  cvRender();cvWhere();cvControls();cvAttachDraw();
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
// An image on the clipboard (a screenshot, "Copy image") is attached; a paste that also carries text stays a text paste.
$("cv-input").addEventListener("paste",e=>{
  const s=CV.cur,data=e.clipboardData,files=data?[...data.files].filter(f=>f.type.startsWith("image/")):[];
  if(!s||!files.length||data.getData("text/plain"))return;
  e.preventDefault();for(const f of files)cvAttach(s,f);
});
$("cv-new").onclick=cvNew;
$("cv-history").onclick=cvHistory;
$("cv-model").onchange=$("cv-effort").onchange=$("cv-perm").onchange=cvApplyPicks;
$("cv-log").addEventListener("scroll",()=>{const b=$("cv-log");CV.stick=b.scrollHeight-b.scrollTop-b.clientHeight<60});
cvLoad();
if(CHAT.open&&PANEL.mode==="chat")chatViewShow();
