import pathlib
import shutil
import subprocess


def test_chat_client_uses_guarded_routes_bounded_text_rendering_and_safe_login():
    source = (pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js").read_text()
    for route in ("/api/chat/events", "/api/chat/diff", "/api/chat/auth", '"/api/chat"'):
        assert route in source
    for operation in ('op:"start"', 'op:"turn"', 'op:"decide"', 'op:"cancel"',
                      'op:"close"', 'op:"login"'):
        assert operation in source
    assert 'headers:{"X-Strata-Token":TOK}' in source
    assert 'response.status===403&&attempt===0' in source
    assert "event.seq<=s.lastSeq" in source
    assert "CHAT_MAX_TIMELINE=150" in source and "CHAT_MAX_BLOCK=16000" in source
    assert "sessionStorage.getItem(CHAT_STORE)" in source
    assert '["auth.openai.com","chatgpt.com"].includes(u.hostname)' in source
    assert 'anchor.target="_blank"' in source and 'anchor.rel="noopener noreferrer"' in source
    assert ".textContent=" in source and "innerHTML" not in source and "outerHTML" not in source
    assert "s.replayIncomplete" in source
    assert "Close a live session before starting another." in source
    assert "result.accepted!==true" in source


def test_empty_chat_panel_renders_without_dereferencing_removed_markup():
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required for the chat runtime regression test")
    app = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js"
    script = r'''
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const begin=source.indexOf("function renderChatPanel(){");
const end=source.indexOf("\nfunction rememberChatEvent",begin);
if(begin<0||end<0)throw Error("renderChatPanel function not found");
const elements=new Map();
function element(){return {hidden:false,disabled:false,scrollHeight:0,scrollTop:0,clientHeight:0,attrs:{},
  children:[],replaceChildren(...items){this.children=items},append(...items){this.children.push(...items)},
  setAttribute(name,value){this.attrs[name]=value},textContent:"",placeholder:""}}
for(const id of ["chat-events","chat-approval","chat-message","chat-send","chat-cancel","chat-close-session","chat-panel","chat-toggle"])
  elements.set(id,element());
const context={
  $:id=>elements.get(id)||null,
  el:(_tag,_class,text)=>Object.assign(element(),{textContent:text||""}),
  chatSession:()=>null,
  CUR:{p:"demo"},
  store:{value:null,writes:[],get(){return this.value},set(k,v){this.writes.push([k,v]);this.value=v}},
  document:{body:{classList:{toggle(){}}}},
  chatCheckAuth(){},
};
vm.createContext(context);
vm.runInContext(source.slice(begin,end),context);
context.renderChatPanel();
const events=elements.get("chat-events");
if(events.children.length!==1||events.children[0].textContent!=="Start a session to work with an AI coding agent.")
  throw Error("empty state was not rendered");
for(const id of ["chat-message","chat-send","chat-cancel","chat-close-session"])
  if(!elements.get(id).disabled)throw Error(id+" should be disabled without a session");
const openBegin=source.indexOf('const CHAT_OPEN_STORE="strata-chat-open-v1";');
const openEnd=source.indexOf("async function chatStartSession",openBegin);
if(openBegin<0||openEnd<0)throw Error("chat preference initialization not found");
vm.runInContext(source.slice(openBegin,openEnd),context);
context.chatInitOpenPreference();
if(elements.get("chat-panel").hidden)throw Error("fresh visit should open chat");
if(context.store.writes.length)throw Error("startup must not overwrite the saved preference");
if(elements.get("chat-toggle").textContent!=="Chat")throw Error("toggle must visibly say Chat");
if(elements.get("chat-toggle").attrs?.["aria-expanded"]!=="true")throw Error("open state must be exposed accessibly");
context.chatOpen(false);
if(context.store.value!=="0")throw Error("deliberate close should persist");
context.store.writes.length=0;
context.chatInitOpenPreference();
if(!elements.get("chat-panel").hidden||context.store.writes.length)throw Error("saved closed preference should restore without writes");
context.chatOpen(true);
if(context.store.value!=="1")throw Error("deliberate open should persist");
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_codex_login_url_allowlist_matches_server_edge_cases():
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required for the login URL regression test")
    app = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js"
    script = r'''
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const begin=source.indexOf("function safeCodexLoginUrl(value){");
const end=source.indexOf("\nasync function chatCheckAuth",begin);
if(begin<0||end<0)throw Error("safeCodexLoginUrl function not found");
const context={URL};vm.createContext(context);vm.runInContext(source.slice(begin,end),context);
const valid=[
  "https://auth.openai.com/authorize?x=1",
  "https://auth.openai.com:443/authorize",
  "https://chatgpt.com/backend-api/codex/oauth",
  "https://chatgpt.com:443/path",
];
const invalid=[
  "http://auth.openai.com/", "https://evil.example/", "https://chatgpt.com.evil/",
  "https://auth.openai.com:444/", "https://auth.openai.com:/", "https://chatgpt.com:/",
  "https://user@auth.openai.com/", "https://user:pass@auth.openai.com/",
  "https://auth.openai.com/#", "https://chatgpt.com/path#fragment",
  " https://auth.openai.com/", "https://auth.openai.com/\n", "https://chatgpt.com/\t",
];
for(const url of valid)if(!context.safeCodexLoginUrl(url))throw Error("expected allowed: "+JSON.stringify(url));
for(const url of invalid)if(context.safeCodexLoginUrl(url)!==null)throw Error("expected rejected: "+JSON.stringify(url));
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_login_link_click_creates_session_and_renders_link_after_auth_refresh():
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required for the chat runtime regression test")
    app = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js"
    script = r'''
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const failLogin=process.argv[2]==="fail";
const begin=source.indexOf("function safeCodexLoginUrl(value){");
const end=source.indexOf("async function chatSend",begin);
if(begin<0||end<0)throw Error("chat login flow was not found");
const elements=new Map();
function element(text=""){return {textContent:text,value:"",hidden:false,disabled:false,attrs:{},children:[],dataset:{},
  replaceChildren(...items){this.children=items},append(...items){this.children.push(...items)},
  setAttribute(k,v){this.attrs[k]=v}}}
for(const id of ["chat-provider","chat-model","chat-auth-state","chat-login-area","chat-new-session","chat-panel","chat-toggle"])
  elements.set(id,element(id==="chat-provider"?"codex":""));
elements.get("chat-provider").value="codex";
const body={classList:{toggle(){},contains(){return true}}};
const calls=[];
let visibleError="";
let context;
context={URL,console,Date,document:{body},CUR:{p:"demo",tab:"task"},enc:encodeURIComponent,
  $:id=>elements.get(id),el:(_tag,_class,text)=>element(text),
  chatState:{sessions:[],selected:null,polling:false,lastDiffAt:0,loginPending:false,loginUrl:null,authRevision:0},
  chatSession(id){return context.chatState.sessions.find(s=>s.session_id===(id||context.chatState.selected))||null},
  chatGet:async()=>({status:"login_required"}),
  api:async(_path,data)=>{calls.push(data.op);if(data.op==="start")return {session_id:"session-new",thread_id:null};
    if(data.op==="login"){if(failLogin)throw Error("login unavailable");return {url:"https://auth.openai.com/authorize?state=abc"}}throw Error("unexpected operation "+data.op)},
  chatClearError(){visibleError=""},chatShowError(message){visibleError=message},
  chatPoll:async()=>{},saveChatSessions(){},renderChatCards(){},renderChatPanel(){},
  pruneClosedChatRefs(){return true},store:{set(){}},hashFor:p=>"#/p/"+p,
};
vm.createContext(context);vm.runInContext("const CHAT_MAX_SESSIONS=4;"+source.slice(begin,end),context);
(async()=>{
  await context.chatCheckAuth();
  const firstArea=elements.get("chat-login-area"),button=firstArea.children.find(x=>x.textContent==="Get sign-in link");
  if(!button||button.disabled)throw Error("login link action should be enabled with a selected project and no session");
  await button.onclick();
  if(calls.join(",")!=="start,login")throw Error("one click should create a session and request login: "+calls.join(","));
  if(context.chatState.sessions.length!==1||context.chatState.sessions[0].thread_id!==null)
    throw Error("pre-auth session was not retained");
  const currentArea=elements.get("chat-login-area"),link=currentArea.children.find(x=>x.id==="chat-login-link");
  if(currentArea.children.includes(button))throw Error("auth refresh did not replace the original login controls");
  if(failLogin){
    if(!visibleError.includes("Could not get a sign-in link. login unavailable"))
      throw Error("login failure should remain visible after successful auth refresh: "+visibleError);
  }else if(!link||link.hidden||link.href!=="https://auth.openai.com/authorize?state=abc")
    throw Error("the refreshed login UI must show the validated sign-in URL");
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    failed = subprocess.run([node, "-e", script, str(app), "fail"], capture_output=True, text=True, timeout=10)
    assert failed.returncode == 0, failed.stderr
