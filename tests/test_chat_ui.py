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
    assert 'u.hostname==="auth.openai.com"' in source
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
function element(){return {hidden:false,disabled:false,scrollHeight:0,scrollTop:0,clientHeight:0,
  children:[],replaceChildren(...items){this.children=items},append(...items){this.children.push(...items)},
  setAttribute(){},textContent:"",placeholder:""}}
for(const id of ["chat-events","chat-approval","chat-message","chat-send","chat-cancel","chat-close-session"])
  elements.set(id,element());
const context={
  $:id=>elements.get(id)||null,
  el:(_tag,_class,text)=>Object.assign(element(),{textContent:text||""}),
  chatSession:()=>null,
  CUR:{p:"demo"}
};
vm.createContext(context);
vm.runInContext(source.slice(begin,end),context);
context.renderChatPanel();
const events=elements.get("chat-events");
if(events.children.length!==1||events.children[0].textContent!=="Start a session to work with an AI coding agent.")
  throw Error("empty state was not rendered");
for(const id of ["chat-message","chat-send","chat-cancel","chat-close-session"])
  if(!elements.get(id).disabled)throw Error(id+" should be disabled without a session");
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
