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
  "https://auth.openai.com/codex/device",
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

const validCodes=["ABCD-1234", "1234", "CODE 1234", "A".repeat(64)];
for(const code of validCodes)if(context.safeCodexUserCode(code)!==code)throw Error("expected code allowed: "+code);
const invalidCodes=["", null, undefined, "A".repeat(65), "ABCD\nEFGH", "ABCD\0EFGH", "ABCD<script>", "ABCDé"];
for(const code of invalidCodes)if(context.safeCodexUserCode(code)!==null)throw Error("expected code rejected: "+code);
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_login_link_click_requests_global_login_and_renders_device_code_and_link():
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required for the chat runtime regression test")
    app = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js"
    script = r'''
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const mode=process.argv[2]||"device";
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
let authStatus="login_required";
let context;
context={URL,console,Date,document:{body},CUR:{p:null,tab:"task"},enc:encodeURIComponent,
  $:id=>elements.get(id),el:(_tag,_class,text)=>element(text),
  chatState:{sessions:[],selected:null,polling:false,lastDiffAt:0,loginPending:false,loginUrl:null,authRevision:0},
  chatSession(id){return context.chatState.sessions.find(s=>s.session_id===(id||context.chatState.selected))||null},
  chatGet:async()=>({status:authStatus}),
  api:async(_path,data)=>{
    calls.push(data.op);
    if(data.op==="login"){
      if(mode==="fail")throw Error("login unavailable");
      if(mode==="invalid_device")return {mode:"device",verification_url:"https://evil.example/codex/device",user_code:"ABCD-1234"};
      if(mode==="invalid_code")return {mode:"device",verification_url:"https://auth.openai.com/codex/device",user_code:"bad\ncode"};
      if(mode==="browser")return {mode:"browser",url:"https://auth.openai.com/authorize?state=browser-flow"};
      return {mode:"device",verification_url:"https://auth.openai.com/codex/device",user_code:"ABCD-1234",login_id:"dev-1"};
    }
    throw Error("unexpected operation "+data.op);
  },
  chatClearError(){visibleError=""},chatShowError(message){visibleError=message},
  chatPoll:async()=>{},saveChatSessions(){},renderChatCards(){},renderChatPanel(){},
  pruneClosedChatRefs(){return true},store:{set(){}},hashFor:p=>"#/p/"+p,
};
vm.createContext(context);vm.runInContext("const CHAT_MAX_SESSIONS=4;"+source.slice(begin,end),context);
(async()=>{
  await context.chatCheckAuth();
  const firstArea=elements.get("chat-login-area"),button=firstArea.children.find(x=>x.textContent==="Get sign-in link");
  if(!button||button.disabled)throw Error("login link action should be enabled even without a selected project");
  await button.onclick();
  if(calls.join(",")!=="login")throw Error("Get sign-in link should call login directly without session start: "+calls.join(","));
  if(context.chatState.sessions.length!==0)throw Error("no session should be created for global login");

  const currentArea=elements.get("chat-login-area"),link=currentArea.children.find(x=>x.id==="chat-login-link");
  const codeEl=currentArea.children.find(x=>x.id==="chat-login-code");

  if(mode==="fail"){
    if(!visibleError.includes("Could not get a sign-in link. login unavailable"))
      throw Error("login failure should be reported: "+visibleError);
    return;
  }
  if(mode==="invalid_device"||mode==="invalid_code"){
    if(!visibleError.includes("Could not get a sign-in link."))
      throw Error("invalid device response should be reported: "+visibleError);
    return;
  }
  if(mode==="browser"){
    if(!link||link.hidden||link.href!=="https://auth.openai.com/authorize?state=browser-flow")
      throw Error("browser fallback link was not rendered: "+(link?.href));
    if(codeEl)throw Error("browser mode must not render a device code element");
    await context.chatCheckAuth();
    const refreshedLink=elements.get("chat-login-area").children.find(x=>x.id==="chat-login-link");
    if(!refreshedLink||refreshedLink.href!=="https://auth.openai.com/authorize?state=browser-flow")
      throw Error("browser link must be preserved across auth refresh");
    return;
  }

  // Device mode
  if(!link||link.hidden||link.href!=="https://auth.openai.com/codex/device")
    throw Error("device verification URL was not rendered: "+(link?.href));
  if(!codeEl||!codeEl.textContent.includes("ABCD-1234"))
    throw Error("one-time device code was not rendered: "+(codeEl?.textContent));

  // Preserved across auth refresh
  await context.chatCheckAuth();
  const preservedArea=elements.get("chat-login-area");
  const preservedLink=preservedArea.children.find(x=>x.id==="chat-login-link");
  const preservedCode=preservedArea.children.find(x=>x.id==="chat-login-code");
  if(!preservedLink||preservedLink.href!=="https://auth.openai.com/codex/device"||!preservedCode||!preservedCode.textContent.includes("ABCD-1234"))
    throw Error("device code and link must be preserved across auth refresh");

  // Provider switching clears login
  elements.get("chat-provider").value="openrouter";
  await context.chatCheckAuth();
  if(elements.get("chat-login-area").children.find(x=>x.id==="chat-login-link"||x.id==="chat-login-code"))
    throw Error("provider switch must clear login link and code");

  // Switch back, request login again, then test completion refresh
  elements.get("chat-provider").value="codex";
  await context.chatCheckAuth();
  const newButton=elements.get("chat-login-area").children.find(x=>x.textContent==="Get sign-in link");
  await newButton.onclick();
  if(!elements.get("chat-login-area").children.find(x=>x.id==="chat-login-code"))
    throw Error("login re-request after provider switch failed");

  // Completion refresh: status becomes account_present
  authStatus="account_present";
  await context.chatCheckAuth();
  if(elements.get("chat-login-area").children.find(x=>x.id==="chat-login-link"||x.id==="chat-login-code"))
    throw Error("completion refresh must clear login link and code");
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    for arg in ("device", "browser", "fail", "invalid_device", "invalid_code"):
        result = subprocess.run([node, "-e", script, str(app), arg], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"Mode {arg} failed: {result.stderr}"
