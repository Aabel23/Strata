"use strict";
// Files tab: project file tree on the left, tabbed code editor (vendored CodeMirror 5) in the middle.
// Reads GET /api/files and /api/file, writes POST /api/file; all token-guarded. Text only goes in through textContent or the editor.
// One state object per project lives for the whole page, so open tabs and unsaved text survive switching sections.
// el, enc come from page.js; api, dialog, icon, IC, hashFor, crumbs, store, CUR, TOK come from app.js.
Object.assign(IC,{
  files:'<path d="M5.5 4.5V2.5h5L13 5v6.5h-2.5"/><path d="M3 4.5h5L10.5 7v6.5H3z"/>',
  file:'<path d="M4 2.5h5.5L12 5v8.5H4z"/><path d="M9.5 2.5V5H12"/>',
  newfile:'<path d="M9 2.5H4v11h8V8"/><path d="M12 2v4M10 4h4"/>',
  newfolder:'<path d="M13.5 8.5v4h-11v-8h4L8 6h2"/><path d="M12.5 2v4M10.5 4h4"/>',
  collapse:'<path d="M5.5 2.5h8v8"/><rect x="2.5" y="5.5" width="8" height="8" rx="1"/><path d="M4.5 9.5h4"/>',
  panel:'<rect x="2.5" y="3" width="11" height="10" rx="1.5"/><path d="M6.5 3v10"/>',
});
const filesView=(()=>{
  const ST={};
  const base=p=>p.split("/").pop(), dirOf=p=>p.includes("/")?p.slice(0,p.lastIndexOf("/")):"";
  const join=(d,n)=>d?d+"/"+n:n;
  const under=(p,d)=>p===d||p.startsWith(d+"/");
  async function read(url){
    const send=async()=>{
      if(!TOK)TOK=(await fetch("/api/session").then(r=>r.json())).token;
      return fetch(url,{headers:{"X-Strata-Token":TOK}});
    };
    let r=await send();
    if(r.status===403){TOK=null;r=await send()}
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||("HTTP "+r.status));
    return d;
  }
  const btn=(ic,title,on)=>{const b=el("button","ib");b.type="button";b.append(icon(ic));b.title=title;b.setAttribute("aria-label",title);b.onclick=on;return b};
  // indentation of the file as it is: tabs, or the smallest run of leading spaces (2, 4 or 8)
  function indentOf(text){
    if(/^\t+\S/m.test(text))return {tabs:true,unit:4};
    let n=0;for(const m of text.slice(0,20000).matchAll(/^( +)\S/gm))n=n?Math.min(n,m[1].length):m[1].length;
    return {tabs:false,unit:n===2||n===8?n:4};
  }

  function build(p){
    const key="strata-fx-"+p;
    let saved={};try{saved=JSON.parse(store.get(key)||"{}")||{}}catch{}
    const s={p,dirs:{},open:new Set(saved.open||[]),tabs:[],active:null,sel:"",pending:null,err:"",cm:null};
    const root=el("div","reader fx"), sideEl=el("aside","fx-side"), split=el("div","fx-split"), main=el("section","fx-main");
    const tree=el("div","fx-tree"), tabsEl=el("div","fx-tabs"), pathEl=el("div","fx-path"), body=el("div","fx-body"), status=el("footer","fx-status");
    const host=el("div","fx-editor"), note=el("div","fx-note");
    tree.setAttribute("role","tree");tree.setAttribute("aria-label","Project files");tabsEl.setAttribute("role","tablist");
    split.setAttribute("role","separator");split.setAttribute("aria-orientation","vertical");split.setAttribute("aria-label","Resize file tree");split.tabIndex=0;
    const sh=el("header","fx-side-head"), nm=el("span","fx-proj",(byId[p]?byId[p].name:p));
    sh.append(nm,btn("newfile","New file",()=>begin("file")),btn("newfolder","New folder",()=>begin("folder")),
      btn("reload","Refresh",()=>refresh()),btn("collapse","Collapse folders",()=>{s.open.clear();persist();drawTree()}));
    sideEl.append(sh,tree);body.append(host,note);
    const stPos=el("span"), stInfo=el("span","fx-st-info"), stMsg=el("span","fx-st-msg");stMsg.setAttribute("role","status");
    status.append(btn("panel","Show or hide the file tree (Ctrl B)",()=>toggleSide()),stMsg,stPos,stInfo);
    main.append(tabsEl,pathEl,body,status);root.append(sideEl,split,main);

    const persist=()=>store.set(key,JSON.stringify({open:[...s.open],tabs:s.tabs.map(t=>t.path),active:s.active}));
    const tab=path=>s.tabs.find(t=>t.path===path);
    const dirty=t=>!!t.doc&&!t.doc.isClean(t.gen);
    const say=(m,bad)=>{stMsg.textContent=m||"";stMsg.classList.toggle("bad",!!bad)};
    const post=b=>api("/api/file",{project:p,...b});

    /* ---- sidebar width: drag the divider, arrow keys, Ctrl B hides ---- */
    const setW=w=>{w=Math.max(160,Math.min(640,Math.round(w)));root.style.setProperty("--fx-side",w+"px");store.set("strata-fx-width",String(w))};
    const w0=Number(store.get("strata-fx-width"));if(w0>=160&&w0<=640)root.style.setProperty("--fx-side",w0+"px");
    const toggleSide=()=>{root.classList.toggle("fx-noside");store.set("strata-fx-noside",root.classList.contains("fx-noside")?"1":"");if(s.cm)s.cm.refresh()};
    if(store.get("strata-fx-noside"))root.classList.add("fx-noside");
    let drag=null;
    split.addEventListener("pointerdown",e=>{if(e.button!==0)return;e.preventDefault();drag={x:e.clientX,w:sideEl.getBoundingClientRect().width};split.setPointerCapture(e.pointerId);document.body.classList.add("resizing")});
    split.addEventListener("pointermove",e=>{if(drag)setW(drag.w+e.clientX-drag.x)});
    const drop=()=>{drag=null;document.body.classList.remove("resizing");if(s.cm)s.cm.refresh()};
    split.addEventListener("pointerup",drop);split.addEventListener("pointercancel",drop);
    split.addEventListener("keydown",e=>{if(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")return;e.preventDefault();setW(sideEl.getBoundingClientRect().width+(e.key==="ArrowRight"?16:-16))});
    root.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&!e.shiftKey&&!e.altKey&&e.key.toLowerCase()==="b"){e.preventDefault();toggleSide()}});

    /* ---- tree ---- */
    async function load(dir){
      const r=await read("/api/files?project="+enc(p)+"&path="+enc(dir));
      s.dirs[dir]=r.entries;return r.entries;
    }
    async function refresh(){
      try{await load("");s.err=""}catch(e){s.err=e.message}
      await Promise.all([...s.open].filter(d=>s.dirs[d]).map(d=>load(d).catch(()=>{delete s.dirs[d];s.open.delete(d)})));
      if(!s.pending)drawTree();
    }
    async function toggle(dir,want){
      const on=want==null?!s.open.has(dir):want;
      if(on){s.open.add(dir);if(!s.dirs[dir]){try{await load(dir)}catch(e){s.open.delete(dir);say(e.message,true)}}}
      else s.open.delete(dir);
      persist();drawTree();
    }
    async function reveal(path){
      const segs=path.split("/");let d="";
      for(let i=0;i<segs.length-1;i++){d=join(d,segs[i]);s.open.add(d);if(!s.dirs[d]){try{await load(d)}catch{s.open.delete(d);break}}}
      s.sel=path;persist();drawTree();
      const r=tree.querySelector(".fx-row.on");if(r)r.scrollIntoView({block:"nearest"});
    }
    function inputRow(depth,isDir,value,done){
      const r=el("div","fx-row fx-edit");r.style.setProperty("--d",depth);
      const i=el("input");i.value=value||"";i.setAttribute("aria-label",isDir?"Folder name":"File name");i.spellcheck=false;
      r.append(el("span","fx-tw"),icon(isDir?"folder":"file"),i);
      let over=false;const end=ok=>{if(over)return;over=true;const v=i.value.trim();s.pending=null;if(ok&&v)done(v);else drawTree()};
      i.onkeydown=e=>{e.stopPropagation();if(e.key==="Enter"){e.preventDefault();end(true)}else if(e.key==="Escape"){e.preventDefault();end(false)}};
      i.onblur=()=>end(false);
      setTimeout(()=>{i.focus();const dot=i.value.lastIndexOf(".");i.setSelectionRange(0,dot>0?dot:i.value.length)});
      return r;
    }
    function rows(dir,depth,out){
      const pd=s.pending;
      if(pd&&pd.kind!=="rename"&&pd.dir===dir)out.push(inputRow(depth,pd.kind==="folder","",v=>create(join(dir,v),pd.kind==="folder")));
      (s.dirs[dir]||[]).forEach(e=>{
        const path=join(dir,e.name);
        if(pd&&pd.kind==="rename"&&pd.path===path)return out.push(inputRow(depth,e.dir,e.name,v=>v===e.name?drawTree():rename(path,join(dir,v))));
        const open=e.dir&&s.open.has(path), r=el("button","fx-row"+(e.dir?" fx-dir":"")+(open?" open":"")+(s.sel===path?" on":""));
        r.type="button";r.style.setProperty("--d",depth);r.dataset.path=path;if(e.dir)r.dataset.dir="1";
        r.setAttribute("role","treeitem");if(e.dir)r.setAttribute("aria-expanded",open);r.tabIndex=s.sel===path?0:-1;
        const tw=el("span","fx-tw");if(e.dir)tw.append(icon("chev"));
        const t=tab(path);
        r.append(tw,icon(e.dir?"folder":"file"),el("span","fx-nm"+(e.name.startsWith(".")?" dot":""),e.name));
        if(t&&dirty(t))r.append(el("span","fx-mod","●"));
        r.title=path;out.push(r);
        if(open)rows(path,depth+1,out);
      });
      return out;
    }
    function drawTree(){
      const keep=document.activeElement&&tree.contains(document.activeElement)&&document.activeElement.dataset.path;
      if(s.err){const m=el("p","fx-treeerr",s.err);return tree.replaceChildren(m)}
      const out=rows("",0,[]);
      if(!out.length)out.push(el("p","fx-treeerr",s.dirs[""]?"This folder is empty.":"Loading…"));
      tree.replaceChildren(...out);
      if(!tree.querySelector('.fx-row[tabindex="0"]')){const f=tree.querySelector("button.fx-row");if(f)f.tabIndex=0}
      if(keep!=null){const r=[...tree.querySelectorAll("button.fx-row")].find(x=>x.dataset.path===keep);if(r)r.focus()}
    }
    const rowOf=e=>e.target.closest&&e.target.closest("button.fx-row");
    tree.addEventListener("click",e=>{const r=rowOf(e);if(!r)return;s.sel=r.dataset.path;r.dataset.dir?toggle(r.dataset.path):openFile(r.dataset.path)});
    tree.addEventListener("keydown",e=>{
      const r=rowOf(e);if(!r||e.ctrlKey||e.metaKey||e.altKey)return;
      const all=[...tree.querySelectorAll("button.fx-row")], i=all.indexOf(r), path=r.dataset.path, isDir=!!r.dataset.dir;
      const focus=x=>{if(!x)return;all.forEach(y=>y.tabIndex=-1);x.tabIndex=0;x.focus()};
      if(e.key==="ArrowDown"){e.preventDefault();focus(all[i+1])}
      else if(e.key==="ArrowUp"){e.preventDefault();focus(all[i-1])}
      else if(e.key==="ArrowRight"&&isDir){e.preventDefault();s.open.has(path)?focus(all[i+1]):toggle(path,true)}
      else if(e.key==="ArrowLeft"){e.preventDefault();if(isDir&&s.open.has(path))toggle(path,false);else focus(all.find(x=>x.dataset.path===dirOf(path)&&x.dataset.dir))}
      else if(e.key==="F2"){e.preventDefault();begin("rename",path)}
      else if(e.key==="Delete"){e.preventDefault();remove(path,isDir)}
    });
    /* context menu */
    let menu=null;
    const closeMenu=()=>{if(menu){menu.remove();menu=null}};
    tree.addEventListener("contextmenu",e=>{
      e.preventDefault();closeMenu();
      const r=rowOf(e), path=r?r.dataset.path:"", isDir=!r||!!r.dataset.dir, dir=isDir?path:dirOf(path);
      if(r){s.sel=path;tree.querySelectorAll(".fx-row.on").forEach(x=>x.classList.remove("on"));r.classList.add("on")}
      const items=[["New file…",()=>begin("file",dir)],["New folder…",()=>begin("folder",dir)]];
      if(r)items.push(null,["Rename…",()=>begin("rename",path)],["Delete",()=>remove(path,isDir)],null,
        ["Copy path",()=>navigator.clipboard&&navigator.clipboard.writeText(join(byId[p]&&byId[p].root||"",path)).catch(()=>{})],
        ["Copy relative path",()=>navigator.clipboard&&navigator.clipboard.writeText(path).catch(()=>{})]);
      menu=el("div","fx-menu");menu.setAttribute("role","menu");
      items.forEach(it=>{if(!it)return menu.append(el("hr"));const b=el("button","",it[0]);b.type="button";b.setAttribute("role","menuitem");b.onclick=()=>{closeMenu();it[1]()};menu.append(b)});
      document.body.append(menu);
      menu.style.left=Math.min(e.clientX,innerWidth-menu.offsetWidth-8)+"px";menu.style.top=Math.min(e.clientY,innerHeight-menu.offsetHeight-8)+"px";
    });
    document.addEventListener("pointerdown",e=>{if(menu&&!menu.contains(e.target))closeMenu()},true);
    document.addEventListener("keydown",e=>{if(menu&&e.key==="Escape")closeMenu()},true);
    addEventListener("blur",closeMenu);

    /* ---- file operations ---- */
    // kind: file | folder (new, inside `dir` or next to the selection) | rename (of `dir`, a path)
    async function begin(kind,dir){
      if(kind==="rename"){s.pending={kind,path:dir};return drawTree()}
      if(dir==null){const r=tree.querySelector(".fx-row.on");dir=r?(r.dataset.dir?r.dataset.path:dirOf(r.dataset.path)):""}
      if(dir&&!s.open.has(dir))await toggle(dir,true);
      s.pending={kind,dir};drawTree();
    }
    async function create(path,folder){
      try{await post({op:folder?"mkdir":"create",path});await load(dirOf(path));s.sel=path;
        if(folder){s.open.add(path);s.dirs[path]=[];persist();drawTree()}else{drawTree();openFile(path)}}
      catch(e){say(e.message,true);drawTree()}
    }
    function moved(from,to){
      const fix=x=>x===from?to:to+x.slice(from.length);
      s.tabs.forEach(t=>{if(under(t.path,from))t.path=fix(t.path)});
      if(s.active&&under(s.active,from))s.active=fix(s.active);
      [...s.open].forEach(d=>{if(under(d,from)){s.open.delete(d);s.open.add(fix(d))}});
      Object.keys(s.dirs).forEach(d=>{if(under(d,from)){s.dirs[fix(d)]=s.dirs[d];delete s.dirs[d]}});
    }
    async function rename(from,to){
      try{await post({op:"rename",path:from,to});moved(from,to);s.sel=to;
        await Promise.all([...new Set([dirOf(from),dirOf(to)])].map(load));persist();drawTree();drawTabs();
        if(s.active)setHash(s.active)}
      catch(e){say(e.message,true);drawTree()}
    }
    function remove(path,isDir){
      const hit=s.tabs.filter(t=>under(t.path,path)), lost=hit.filter(dirty).length;
      const info=el("p","pinfo",(isDir?"Deletes the folder “"+path+"” and everything in it.":"Deletes “"+path+"”.")+" This cannot be undone."+(lost?" "+lost+" open file"+(lost>1?"s have":" has")+" unsaved changes.":""));
      dialog("Delete "+base(path)+"?",[info],(d,fail)=>{
        const ok=el("button","danger","Delete");ok.type="submit";
        d.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");
          try{await post({op:"delete",path,recursive:isDir});d.close();
            hit.forEach(t=>drop_(t));delete s.dirs[path];s.open.delete(path);if(s.sel===path)s.sel="";
            await load(dirOf(path)).catch(()=>{});persist();drawTree();drawTabs();show()}
          catch(x){fail(x.message);ok.disabled=false}};
        return [ok]});
    }

    /* ---- tabs + editor ---- */
    function editor(){
      if(s.cm)return s.cm;
      const save=()=>{const t=tab(s.active);if(t)saveTab(t)};
      s.cm=CodeMirror(host,{lineNumbers:true,styleActiveLine:true,matchBrackets:true,autoCloseBrackets:true,lineWrapping:false,indentUnit:4,tabSize:4,
        extraKeys:{"Ctrl-S":save,"Cmd-S":save,"Ctrl-/":"toggleComment","Cmd-/":"toggleComment","Ctrl-G":"jumpToLine",
          Tab:cm=>cm.somethingSelected()?cm.indentSelection("add"):cm.getOption("indentWithTabs")?cm.replaceSelection("\t","end","+input"):cm.execCommand("insertSoftTab"),
          "Shift-Tab":cm=>cm.indentSelection("subtract")}});
      s.cm.on("cursorActivity",pos);
      s.cm.on("changes",()=>{const t=tab(s.active);if(t&&t.dirtyShown!==dirty(t)){t.dirtyShown=dirty(t);drawTabs();drawTree()}});
      return s.cm;
    }
    function pos(){
      const t=tab(s.active);if(!t||!t.doc){stPos.textContent="";stInfo.textContent="";return}
      const c=s.cm.getCursor(), n=s.cm.getSelection().length;
      stPos.textContent="Ln "+(c.line+1)+", Col "+(c.ch+1)+(n?" ("+n+" selected)":"");
      stInfo.textContent=(t.tabs?"Tabs":"Spaces: "+t.unit)+" · UTF-8 · "+(t.eol==="\r\n"?"CRLF":"LF")+" · "+t.lang;
    }
    function fill(t,r){
      t.skipped=r.skipped||"";t.mtime=r.mtime;t.stale=false;
      if(t.skipped){t.doc=null;return}
      const info=CodeMirror.findModeByFileName(base(t.path)), ind=indentOf(r.text);
      t.eol=r.text.includes("\r\n")?"\r\n":"\n";t.lang=info?info.name:"Plain text";t.tabs=ind.tabs;t.unit=ind.unit;
      if(t.doc){const c=t.doc.getCursor();t.doc.setValue(r.text);t.doc.setCursor(c)}
      else t.doc=CodeMirror.Doc(r.text,info&&CodeMirror.mimeModes[info.mime]||info&&CodeMirror.modes[info.mode]?info.mime:"text/plain");
      t.gen=t.doc.changeGeneration(true);t.dirtyShown=false;
    }
    async function openFile(path,quiet){
      let t=tab(path);
      if(!t){
        t={path,doc:null,loading:true};s.tabs.push(t);
        if(!quiet){s.active=path;drawTabs();show()}
        try{fill(t,await read("/api/file?project="+enc(p)+"&path="+enc(path)))}
        catch(e){t.skipped=e.message;t.gone=true}
        t.loading=false;
        if(t.gone&&quiet){drop_(t);return}
      }
      if(quiet)return;
      s.active=path;persist();drawTabs();show();setHash(path);reveal(path);
    }
    function setHash(path){
      const h=hashFor(p,"files",path||"");
      if(CUR.p!==p||CUR.tab!=="files")return;
      if(location.hash!==h)location.hash=h;
    }
    function show(){
      const t=tab(s.active);
      pathEl.replaceChildren();
      if(!t){host.hidden=true;note.hidden=false;stPos.textContent=stInfo.textContent="";
        const b=el("b","","No file open"), m=el("p","muted","Pick a file in the tree on the left. Ctrl S saves, Ctrl F finds, Ctrl / comments a line, Ctrl B hides the tree.");
        return note.replaceChildren(b,m)}
      t.path.split("/").forEach((x,i,a)=>{if(i)pathEl.append(el("span","sep","›"));pathEl.append(el(i===a.length-1?"b":"span","",x))});
      if(t.loading||t.skipped){host.hidden=true;note.hidden=false;stPos.textContent=stInfo.textContent="";
        return note.replaceChildren(el("p","muted",t.loading?"Loading…":t.skipped))}
      note.hidden=true;host.hidden=false;
      const cm=editor();
      if(cm.getDoc()!==t.doc){cm.swapDoc(t.doc);cm.setOption("indentWithTabs",t.tabs);cm.setOption("indentUnit",t.unit);cm.setOption("tabSize",t.tabs?4:t.unit)}
      cm.refresh();pos();say(t.stale?"Changed on disk. Saving will ask before overwriting.":"",t.stale);
      if(!document.querySelector("dialog[open]")&&!s.pending)cm.focus();
    }
    function drawTabs(){
      tabsEl.replaceChildren(...s.tabs.map(t=>{
        const b=el("div","fx-tab"+(t.path===s.active?" on":"")+(dirty(t)?" dirty":""));b.setAttribute("role","tab");b.setAttribute("aria-selected",t.path===s.active);b.tabIndex=0;b.title=t.path;
        const x=el("button","fx-x");x.type="button";x.setAttribute("aria-label","Close "+base(t.path));x.title="Close";
        x.onclick=e=>{e.stopPropagation();closeTab(t)};
        b.append(icon("file"),el("span","fx-tn",base(t.path)),x);
        b.onclick=()=>openFile(t.path);b.onauxclick=e=>{if(e.button===1){e.preventDefault();closeTab(t)}};
        b.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openFile(t.path)}};
        return b}));
      const on=tabsEl.querySelector(".fx-tab.on");if(on)on.scrollIntoView({block:"nearest",inline:"nearest"});
    }
    function drop_(t){
      const i=s.tabs.indexOf(t);if(i<0)return;
      s.tabs.splice(i,1);
      if(s.active===t.path){const n=s.tabs[i]||s.tabs[i-1];s.active=n?n.path:null}
    }
    function closeTab(t){
      const done=()=>{drop_(t);persist();drawTabs();drawTree();show();setHash(s.active);if(s.active)reveal(s.active)};
      if(!dirty(t))return done();
      const info=el("p","pinfo","Your changes to “"+t.path+"” are lost if you do not save them.");
      dialog("Save changes to "+base(t.path)+"?",[info],(d,fail)=>{
        const no=el("button","danger","Don't save"), ok=el("button","primary","Save");no.type="button";ok.type="submit";
        no.onclick=()=>{d.close();done()};
        d.firstChild.onsubmit=async e=>{e.preventDefault();ok.disabled=true;fail("");if(await saveTab(t)){d.close();done()}else{ok.disabled=false;fail("Could not save. See the status bar.")}};
        return [no,ok]});
    }
    async function saveTab(t,force){
      if(!t.doc)return false;
      try{const r=await post({op:"write",path:t.path,text:t.doc.getValue(t.eol),...(force?{}:{mtime:t.mtime})});
        t.mtime=r.mtime;t.stale=false;t.gen=t.doc.changeGeneration(true);t.dirtyShown=false;drawTabs();drawTree();say("Saved "+base(t.path));return true}
      catch(e){
        if(!/changed on disk/i.test(e.message)){say(e.message,true);return false}
        return new Promise(res=>{let answered=false;
          const info=el("p","pinfo","“"+t.path+"” changed on disk after you opened it (another editor or an agent). Overwrite it with your text, or load the version on disk and lose your changes?");
          const d=dialog("File changed on disk",[info],(d,fail)=>{
            const rl=el("button","","Load from disk"), ok=el("button","danger","Overwrite");rl.type="button";ok.type="submit";
            rl.onclick=async()=>{answered=true;d.close();await reload(t,true);res(false)};
            d.firstChild.onsubmit=async e=>{e.preventDefault();answered=true;d.close();res(await saveTab(t,true))};
            return [rl,ok]});
          d.addEventListener("close",()=>{if(!answered)res(false)})});
      }
    }
    // pick up changes made outside (agents, terminal): a clean tab reloads silently, a dirty one is only flagged
    async function reload(t,force){
      try{const r=await read("/api/file?project="+enc(p)+"&path="+enc(t.path));
        if(r.mtime===t.mtime&&!force)return;
        if(dirty(t)&&!force){t.stale=true;if(t.path===s.active)say("Changed on disk. Saving will ask before overwriting.",true);return}
        fill(t,r);drawTabs();drawTree();if(t.path===s.active)show()}
      catch{}
    }
    const watch=()=>{if(!root.isConnected||document.hidden)return;const t=tab(s.active);if(t&&!t.loading&&!t.gone)reload(t)};
    setInterval(watch,4000);
    addEventListener("focus",()=>{if(root.isConnected){watch();refresh()}});

    s.root=root;s.openFile=openFile;s.dirty=()=>s.tabs.some(dirty);
    s.shown=()=>{if(s.cm)s.cm.refresh();const t=tab(s.active);if(t&&t.doc&&s.cm&&!document.querySelector("dialog[open]"))s.cm.focus()};
    s.ready=(async()=>{
      await refresh();
      for(const d of [...s.open])if(!s.dirs[d]){try{await load(d)}catch{s.open.delete(d)}}
      for(const path of saved.tabs||[])await openFile(path,true);
      if(saved.active&&tab(saved.active))s.active=saved.active;else if(s.tabs.length)s.active=s.tabs[0].path;
      drawTree();drawTabs();show();
    })();
    return s;
  }

  addEventListener("beforeunload",e=>{if(Object.values(ST).some(s=>s.dirty())){e.preventDefault();e.returnValue=""}});
  return async function(box,p,id){
    const s=ST[p]||(ST[p]=build(p));
    if(s.root.isConnected)box.keep=s.root;else box.append(s.root);  // already on screen: render() leaves it in place, scroll and focus intact
    await s.ready;
    if(id)await s.openFile(id);
    else if(s.active){history.replaceState(null,"",hashFor(p,"files",s.active));CUR.id=s.active;crumbs(CUR)}
    requestAnimationFrame(s.shown);
  };
})();
