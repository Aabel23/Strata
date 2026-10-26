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
