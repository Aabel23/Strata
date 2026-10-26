import pathlib
import shutil
import subprocess


def test_task_board_archive_rendering_and_reveal_rules():
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required for the task board runtime test")
    app = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.js"
    source = app.read_text()
    assert 'const COLS=["proposed","approved","doing","review"]' in source
    assert 'ARCHIVE=["open","done","rejected"]' in source
    script = r'''
const fs=require("fs"),vm=require("vm"),source=fs.readFileSync(process.argv[1],"utf8");
const begin=source.indexOf("function boardArchive(");
const end=source.indexOf("\nfunction chipRow",begin);
if(begin<0||end<0)throw Error("boardArchive function not found");
function el(tag,cls="",text=""){
  return {tag,cls,textContent:String(text),children:[],attrs:{},open:false,
    append(...items){this.children.push(...items);this.textContent+=items.map(x=>typeof x==="string"?x:(x.textContent||"")).join("")},
    setAttribute(k,v){this.attrs[k]=v}};
}
const context={ARCHIVE:["open","done","rejected"],ARCHIVE_LABEL:{open:"To do",done:"Done",rejected:"Rejected"},
  el,statusIcon:status=>el("i","status","")};
vm.createContext(context);vm.runInContext(source.slice(begin,end),context);
const items=[{id:1,status:"open",title:"Todo"},{id:2,status:"done",title:"Finished"},{id:3,status:"rejected",title:"Rejected"}];
const makeCard=item=>el("a","tcard",item.title);
let details=context.boardArchive(items,null,"",makeCard);
if(!details||details.tag!=="details"||details.open)throw Error("archive should exist and be collapsed by default");
if(details.children.length!==4)throw Error("archive should contain summary and three status groups");
if(details.children[0].textContent!=="More statuses · 3")throw Error("archive total count is wrong");
const labels=details.children.slice(1).map(group=>group.children[0].textContent);
if(labels.join("|")!=="To do · 1|Done · 1|Rejected · 1")throw Error("status groups or counts are wrong: "+labels);
if(context.boardArchive([],null,"",makeCard)!==null)throw Error("empty archive should stay hidden by default");
if(!context.boardArchive([],null,"open",makeCard).open)throw Error("open status filter should reveal archive");
if(!context.boardArchive([],"done","",makeCard).open)throw Error("deep-linked archived item should reveal archive");
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
