import pathlib
import shutil
import subprocess


def test_outside_link_ends_show_real_object_and_group_over_cap():
    node = shutil.which("node")
    assert node, "Node.js is required for the viewer runtime test"
    page = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "index.html"
    script = r'''
const fs=require("fs"),vm=require("vm"),src=fs.readFileSync(process.argv[1],"utf8");
const begin=src.indexOf("// Map an endpoint to the object visible"), end=src.indexOf("// Parent path of an outside object",begin);
if(begin<0||end<0)throw Error("lift/outMap block not found");
const O=[{id:"S"},{id:"A",parent:"S"},{id:"a1",parent:"A"},{id:"a2",parent:"A"},{id:"T"},{id:"T1",parent:"T"},{id:"T2",parent:"T"},{id:"U"},{id:"u1",parent:"U"}],C=[];
for(let i=1;i<=6;i++){O.push({id:"x"+i,parent:"T1"});C.push({from:"a1",to:"x"+i})}
for(let i=1;i<=4;i++){O.push({id:"y"+i,parent:"T2"});C.push({from:"a2",to:"y"+i})}
const byId={};O.forEach(o=>byId[o.id]=o);
const ctx={M:{objects:O,connections:C},byId,chain:id=>{const r=[];for(let o=byId[id];o;o=byId[o.parent])r.unshift(o.id);return r}};
vm.createContext(ctx);vm.runInContext(src.slice(begin,end)+";this.lift=lift;this.outMap=outMap;this.reset=()=>{outC=new Map()}",ctx);
const eq=(a,b,m)=>{if(JSON.stringify(a)!==JSON.stringify(b))throw Error(m+": "+JSON.stringify(a)+" != "+JSON.stringify(b))};
// 10 outside ends > cap 8: the deepest ancestor that alone fits (T2, 4 ends) groups; T1's six stay real.
eq(ctx.lift("x3","A"),{id:"x3",ext:true,n:1,grp:false},"real ghost");
eq(ctx.lift("y2","A"),{id:"T2",ext:true,n:4,grp:true},"grouped");
eq(ctx.lift("a1","A"),{id:"a1",ext:false},"in scope");
eq(ctx.lift("A","A").id,"A","scope itself");
eq(ctx.lift("u1","A").id,"U","end not on a link of this level falls back to its top unit");
eq(ctx.outMap("A").n.size,7,"card count");
// Under the cap every end is the real object.
C.splice(8);ctx.reset();
eq(ctx.lift("x6","A").id,"x6","under cap");eq(ctx.lift("y2","A").id,"y2","under cap");
// Top level: everything is in scope.
eq(ctx.lift("y2",null),{id:"T",ext:false},"top level");
'''
    result = subprocess.run([node, "-e", script, str(page)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
