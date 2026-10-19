/* swimlane block, ported from project1_app/documentation/assets/swimlane.js.
   The doc only says WHAT happens (lanes, phases, steps); numbering, colours, lane width,
   rows and edge routing are all decided here.
     swimlane:
       lanes: {Zone: [Lane, Lane], Zone2: [Lane]}   # or a plain list [Lane, Lane]
       phases: [Tạo lời mời, Chấp nhận]             # optional; colour comes from the order
       steps:
         - {lane: Lane, text: "…"}                   # text may be a list -> bullets
         - {lane: Lane, text: "…", phase: 2, after: [1], data: [1], label: "…"}
       caption: "…"
   phase: number (1-based) or name; omitted = same as previous step.
   after: steps this one waits for; omitted = previous step, [] = starts a new chain.
   data: dashed "needs data from" links. label: text on the incoming arrow. */
const swimlane=(()=>{
  const NS="http://www.w3.org/2000/svg", BOX_PAD=11, LINE_H=14, ROW_GAP=38, CHAR_W=5.7, HEAD_ZONE=30, HEAD_NAME=42;
  let uid=0;
  const sv=(p,tag,a,text)=>{const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);if(text!=null)e.textContent=text;p.appendChild(e);return e};
  const wrap=(text,max)=>{const out=[];String(text).split(" ").forEach(w=>{const l=out[out.length-1];if(l!=null&&(l+" "+w).length<=max)out[out.length-1]=l+" "+w;else out.push(w)});return out};
  const stepLines=(s,max)=>{const items=Array.isArray(s.text)?s.text:[s.text], b=items.length>1, out=[];
    items.forEach(it=>wrap(it,max-(b?2:0)).forEach((l,i)=>out.push((b?(i?"  ":"• "):"")+l)));return out};

  // YAML shape -> {zones, lanes, phases, steps, edges}
  function norm(b){
    let zones=null, lanes;
    if(Array.isArray(b.lanes))lanes=b.lanes.map(String);
    else{zones=Object.entries(b.lanes).map(([name,ls])=>({name,lanes:(Array.isArray(ls)?ls:[ls]).map(String)}));lanes=zones.flatMap(z=>z.lanes)}
    const phases=(b.phases||[]).map(String), edges=[];
    let ph=0;
    const steps=b.steps.map((s,i)=>{
      if(s.phase!=null)ph=typeof s.phase==="number"?s.phase-1:Math.max(0,phases.indexOf(String(s.phase)));
      const n=i+1, after=s.after==null?(i?[i]:[]):[].concat(s.after);
      after.forEach(f=>edges.push({from:f,to:n,label:s.label}));
      [].concat(s.data||[]).forEach(f=>edges.push({from:f,to:n,kind:"data"}));
      return {n,lane:String(s.lane),text:s.text,phase:ph};
    });
    // lane width from the longest line of text: aim for at most ~2 lines per box
    // and wide enough that the longest single word (MACHINE_SHARE_CREATE) never overflows
    const texts=steps.flatMap(s=>[].concat(s.text).map(String));
    const L=Math.max(...texts.map(t=>t.length)), Wd=Math.max(...texts.flatMap(t=>t.split(" ").map(w=>w.length+(w===w.toUpperCase()&&/[A-Z]/.test(w)?w.length*.25:0))));
    const laneW=Math.round(Math.max(150,Math.min(240,Math.ceil(L/2)*CHAR_W+2*BOX_PAD+30),(Wd+5)*CHAR_W+2*BOX_PAD+22));
    return {zones,lanes,phases,steps,edges,laneW};
  }

  // row = dependency depth; two steps in the same (lane,row) push the later one down
  function depthOf(steps,edges){
    const min={}, depth={};steps.forEach(s=>min[s.n]=0);
    for(let round=0;round<50;round++){
      steps.forEach(s=>depth[s.n]=min[s.n]);
      for(let p=0;p<steps.length;p++)edges.forEach(e=>{depth[e.to]=Math.max(depth[e.to],depth[e.from]+1)});
      let moved=false;
      steps.slice(1).forEach(s=>{if(edges.some(e=>e.to===s.n))return;
        const next=edges.filter(e=>e.from===s.n&&e.kind!=="data").map(e=>depth[e.to]);
        if(next.length&&Math.min(...next)-1>depth[s.n]){min[s.n]=Math.min(...next)-1;moved=true}});
      if(moved)continue;
      const seen={};
      [...steps].sort((a,b)=>depth[a.n]-depth[b.n]||a.n-b.n).forEach(s=>{const k=s.lane+"|"+depth[s.n];if(seen[k]){min[s.n]=depth[s.n]+1;moved=true}seen[k]=true});
      if(!moved)break;
    }
    return depth;
  }

  const phColor=i=>`var(--ph${i%5+1})`;

  function draw(d){
    const {lanes,laneW,steps,edges}=d, ix=Object.fromEntries(lanes.map((l,i)=>[l,i]));
    const colorOf=s=>phColor(s.phase), depth=depthOf(steps,edges), by=n=>steps.find(s=>s.n===n);
    const boxW=laneW-22, maxChars=Math.floor((boxW-2*BOX_PAD)/CHAR_W), lines={}, boxH={};
    steps.forEach(s=>{lines[s.n]=stepLines(s,maxChars);boxH[s.n]=lines[s.n].length*LINE_H+2*BOX_PAD});
    const rowH=Array(Math.max(...Object.values(depth))+1).fill(0);
    steps.forEach(s=>rowH[depth[s.n]]=Math.max(rowH[depth[s.n]],boxH[s.n]));
    const top=(d.zones?HEAD_ZONE:0)+HEAD_NAME+16, rowY=[];let y=top;
    rowH.forEach((h,r)=>{rowY[r]=y+h/2;y+=h+ROW_GAP});
    const W=lanes.length*laneW, H=y;
    const svg=document.createElementNS(NS,"svg");
    svg.setAttribute("viewBox",`0 0 ${W} ${H}`);svg.setAttribute("width",W);svg.setAttribute("class","swim");
    const id="sw"+(++uid), defs=sv(svg,"defs",{}), mk={};
    const marker=c=>{if(mk[c])return mk[c];const m=sv(defs,"marker",{id:id+"m"+Object.keys(mk).length,viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:7,markerHeight:7,orient:"auto-start-reverse"});
      sv(m,"path",{d:"M0,0L10,5L0,10z",fill:c});return mk[c]=`url(#${m.id})`};
    lanes.forEach((l,i)=>sv(svg,"rect",{x:i*laneW,y:0,width:laneW,height:H,class:i%2?"sw-lane alt":"sw-lane"}));
    if(d.zones)d.zones.forEach(z=>{const xs=z.lanes.map(l=>ix[l]), a=Math.min(...xs), b=Math.max(...xs);
      sv(svg,"rect",{x:a*laneW+3,y:4,width:(b-a+1)*laneW-6,height:22,rx:5,class:"sw-zone"});
      sv(svg,"text",{x:(a+b+1)/2*laneW,y:19,"text-anchor":"middle",class:"sw-zt"},z.name.toUpperCase())});
    const nameY=(d.zones?HEAD_ZONE:0)+HEAD_NAME/2;
    lanes.forEach((l,i)=>{const ls=wrap(l,Math.floor((laneW-12)/6.6));
      ls.forEach((t,j)=>sv(svg,"text",{x:i*laneW+laneW/2,y:nameY+4+(j-(ls.length-1)/2)*14,"text-anchor":"middle",class:"sw-ln"},t))});
    sv(svg,"line",{x1:0,x2:W,y1:top-8,y2:top-8,class:"sw-rule"});
    const pos=s=>({x:ix[s.lane]*laneW+laneW/2,y:rowY[depth[s.n]]});
    const busy=lanes.map(()=>new Set());steps.forEach(s=>busy[ix[s.lane]].add(depth[s.n]));
    const free=(li,r0,r1)=>{for(let r=r0+1;r<r1;r++)if(busy[li].has(r))return false;return true};
    const gapA=r=>rowY[r]-rowH[r]/2-ROW_GAP/2, gapB=r=>rowY[r]+rowH[r]/2+ROW_GAP/2;
    const route=pts=>{let s=`M${pts[0][0]},${pts[0][1]}`;
      for(let i=1;i<pts.length-1;i++){const [px,py]=pts[i-1],[x,y]=pts[i],[nx,ny]=pts[i+1];
        const l1=Math.hypot(x-px,y-py), l2=Math.hypot(nx-x,ny-y), r=Math.min(8,l1/2,l2/2);
        s+=`L${x-(x-px)/l1*r},${y-(y-py)/l1*r}Q${x},${y} ${x+(nx-x)/l2*r},${y+(ny-y)/l2*r}`}
      const [lx,ly]=pts[pts.length-1];return s+`L${lx},${ly}`};
    edges.forEach(e=>{const a=by(e.from), b=by(e.to);if(!a||!b)return;
      const pa=pos(a), pb=pos(b), ya=pa.y+boxH[a.n]/2, yb=pb.y-boxH[b.n]/2, ra=depth[a.n], rb=depth[b.n], la=ix[a.lane], lb=ix[b.lane];
      const data=e.kind==="data", c=data?"var(--faint)":colorOf(b);let pts;
      if(la===lb)pts=[[pa.x,ya],[pb.x,yb]];
      else if(free(lb,ra-1,rb)){const h=gapB(ra);pts=[[pa.x,ya],[pa.x,h],[pb.x,h],[pb.x,yb]]}
      else if(free(la,ra,rb+1)){const h=gapA(rb);pts=[[pa.x,ya],[pa.x,h],[pb.x,h],[pb.x,yb]]}
      else{const side=pb.x>pa.x?-1:1, xs=pb.x+side*(laneW/2-4), h1=gapB(ra), h2=gapA(rb);pts=[[pa.x,ya],[pa.x,h1],[xs,h1],[xs,h2],[pb.x,h2],[pb.x,yb]]}
      sv(svg,"path",{d:route(pts),fill:"none",stroke:c,"stroke-width":1.7,"stroke-dasharray":data?"4 4":"","stroke-linejoin":"round","marker-end":marker(c)});
      if(e.label){const ly=yb-13, w=e.label.length*6+10;
        sv(svg,"rect",{x:pb.x-w/2,y:ly-9,width:w,height:18,rx:4,class:"sw-lb"});
        sv(svg,"text",{x:pb.x,y:ly+4,"text-anchor":"middle",class:"sw-lt"},e.label)}});
    steps.forEach(s=>{const {x,y}=pos(s), h=boxH[s.n], c=colorOf(s), ls=lines[s.n], multi=Array.isArray(s.text)&&s.text.length>1;
      sv(svg,"rect",{x:x-boxW/2,y:y-h/2,width:boxW,height:h,rx:8,class:"sw-box",stroke:c});
      ls.forEach((t,j)=>sv(svg,"text",{x:multi?x-boxW/2+BOX_PAD+(t.startsWith("  ")?9:0):x,y:y+4+(j-(ls.length-1)/2)*LINE_H,"text-anchor":multi?"start":"middle",class:"sw-t"},t.trim()));
      sv(svg,"circle",{cx:x-boxW/2,cy:y-h/2,r:9,fill:c});
      sv(svg,"text",{x:x-boxW/2,y:y-h/2+4,"text-anchor":"middle",class:"sw-n"},s.n)});
    return svg;
  }

  // legend: each phase with its step range, plus the dashed data link when used
  function legend(d){
    const box=document.createElement("div");box.className="sw-legend";
    const add=(cls,style,label)=>{const s=document.createElement("span"), i=document.createElement("i");i.className=cls;if(style)i.style.background=style;s.append(i,label);box.append(s)};
    d.phases.forEach((p,k)=>{const ns=d.steps.filter(s=>s.phase===k).map(s=>s.n);
      add("",phColor(k),ns.length?`${p} (${ns[0]}${ns.length>1?"–"+ns[ns.length-1]:""})`:p)});
    if(d.edges.some(e=>e.kind==="data"))add("data","","Phụ thuộc dữ liệu");
    return box;
  }

  return b=>{const d=norm(b), f=document.createElement("figure");f.className="swimfig";
    if(d.phases.length||d.edges.some(e=>e.kind==="data"))f.append(legend(d));
    const c=document.createElement("div");c.className="sw-canvas";c.append(draw(d));f.append(c);
    if(b.caption){const fc=document.createElement("figcaption");fc.textContent=b.caption;f.append(fc)}
    return f};
})();
