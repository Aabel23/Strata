/* roadmap block: columns = periods, rows = lanes, bars = items. The doc only says WHAT and WHEN;
   column width, bar stacking, text wrapping and colours are decided here.
     roadmap:
       periods: [Q1/26, Q2/26]            # required, named columns in order
       lanes: [Core, Viewer]              # optional; none = one unnamed lane
       items: [{lane, text, from, to?, status? done|doing|plan|blocked, link?}]   # to omitted = one column
       milestones: [{at: Q2/26, text: v1}]
       caption: "…"
   Overlapping bars in one lane stack into extra rows. link: doc path (opens that doc) or https URL. */
const roadmap=(()=>{
  const NS="http://www.w3.org/2000/svg", LW=120, CW=128, HEAD=30, ROW=40, PAD=8, CHAR_W=6.3, MS=26;
  const STAT={done:"Xong",doing:"Đang làm",plan:"Kế hoạch",blocked:"Bị chặn"};
  const sv=(p,tag,a,text)=>{const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);if(text!=null)e.textContent=text;p.appendChild(e);return e};
  const wrap=(t,max)=>{const out=[];String(t).split(" ").forEach(w=>{const l=out[out.length-1];if(l!=null&&(l+" "+w).length<=max)out[out.length-1]=l+" "+w;else out.push(w)});return out};
  const fit=(t,max)=>{const ls=wrap(t,max);if(ls.length<=2&&ls.every(l=>l.length<=max))return ls;
    const a=ls.slice(0,2).map(l=>l.length>max?l.slice(0,max-1)+"…":l);if(ls.length>2||ls[1]==null)a[a.length-1]=a[a.length-1].replace(/…?$/,"…");return a};

  function draw(b,linkFor){
    const ps=b.periods.map(String), lanes=(b.lanes||[]).map(String), named=lanes.length>0, L=named?lanes:[""], x0=named?LW:0;
    const items=b.items.map(it=>{const f=ps.indexOf(String(it.from)), t=it.to==null?f:ps.indexOf(String(it.to));
      return {...it,f,t,lane:named?String(it.lane):"",status:STAT[it.status]?it.status:"plan"}});
    const ms=(b.milestones||[]).map(m=>({...m,i:ps.indexOf(String(m.at))}));
    // stack: first row of the lane whose last bar ended before this one starts
    let y=HEAD;const rows=[];
    L.forEach(l=>{const ends=[], its=items.filter(it=>it.lane===l).sort((a,c)=>a.f-c.f||a.t-c.t);
      its.forEach(it=>{let r=ends.findIndex(e=>e<it.f);if(r<0){r=ends.length;ends.push(0)}ends[r]=it.t;it.row=r});
      const n=Math.max(1,ends.length);rows.push({l,y,h:n*ROW+PAD});y+=n*ROW+PAD});
    const H=y+(ms.length?MS:0), Wd=x0+ps.length*CW;
    const svg=sv(document.createElement("div"),"svg",{class:"rm",viewBox:`0 0 ${Wd} ${H}`,width:Wd,height:H,role:"img","aria-label":"Lộ trình"});
    rows.forEach((r,k)=>{sv(svg,"rect",{x:0,y:r.y,width:Wd,height:r.h,class:"rm-lane"+(k%2?" alt":"")});
      if(named)sv(svg,"text",{x:10,y:r.y+r.h/2+4,class:"rm-ln"},r.l)});
    ps.forEach((p,i)=>{if(i)sv(svg,"line",{x1:x0+i*CW,x2:x0+i*CW,y1:0,y2:y,class:"rm-rule"});
      sv(svg,"text",{x:x0+i*CW+CW/2,y:HEAD/2+4,"text-anchor":"middle",class:"rm-pt"},p)});
    sv(svg,"line",{x1:0,x2:Wd,y1:HEAD,y2:HEAD,class:"rm-rule"});
    ms.forEach(m=>{const x=x0+m.i*CW+CW/2;
      sv(svg,"line",{x1:x,x2:x,y1:HEAD,y2:y+4,class:"rm-ms"});
      sv(svg,"path",{d:`M${x} ${y+6}l5 5l-5 5l-5 -5z`,class:"rm-msd"});
      sv(svg,"text",{x:x+9,y:y+16,class:"rm-mt"},m.text)});
    items.forEach(it=>{const r=rows[L.indexOf(it.lane)], bx=x0+it.f*CW+3, bw=(it.t-it.f+1)*CW-6, by=r.y+PAD/2+it.row*ROW, bh=ROW-6;
      const href=it.link&&linkFor?linkFor(it.link):null, g=href?sv(svg,"a",{href,class:"rm-b link st-"+it.status}):sv(svg,"g",{class:"rm-b st-"+it.status});
      if(href&&/^https?:/.test(href)){g.setAttribute("target","_blank");g.setAttribute("rel","noopener")}
      sv(g,"title",{},it.text+" ("+STAT[it.status]+", "+ps[it.f]+(it.t>it.f?" → "+ps[it.t]:"")+")");
      sv(g,"rect",{x:bx,y:by,width:bw,height:bh,rx:6});
      const ls=fit(it.text,Math.max(4,Math.floor((bw-16)/CHAR_W)));
      ls.forEach((t,j)=>sv(g,"text",{x:bx+8,y:by+bh/2+4+(j-(ls.length-1)/2)*13,class:"rm-t"},t))});
    return {svg,used:[...new Set(items.map(i=>i.status))]};
  }

  return (b,linkFor)=>{const f=document.createElement("figure");f.className="swimfig";
    const {svg,used}=draw(b,linkFor);
    const lg=document.createElement("div");lg.className="sw-legend";
    Object.keys(STAT).filter(k=>used.includes(k)).forEach(k=>{const s=document.createElement("span"), i=document.createElement("i");i.className="rm-k st-"+k;s.append(i,STAT[k]);lg.append(s)});
    const c=document.createElement("div");c.className="sw-canvas";c.append(svg);f.append(lg,c);
    if(b.caption){const fc=document.createElement("figcaption");fc.textContent=b.caption;f.append(fc)}
    return f};
})();

/* Lộ trình tab map (design/roadmap-astra.html): layered gold ridges, camps = phases on the main ridge, cairns = gates,
   walked trail up to the "you are here" flag. Only geometry is computed here; text goes in via textContent.
   camps: [{n, label, state: done|doing|todo, gate: {key, state: done|open|todo} | null}]  (gate = cairn after that camp) */
const astraMap=(()=>{
  const NS="http://www.w3.org/2000/svg", LBL={done:"xong",doing:"đang làm",todo:"sắp tới"};
  const sv=(p,tag,a,text)=>{const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);if(text!=null)e.textContent=text;if(p)p.appendChild(e);return e};
  const smooth=pts=>{let d=`M${pts[0][0]} ${pts[0][1]}`;
    for(let i=0;i<pts.length-1;i++){const p0=pts[i-1]||pts[i],p1=pts[i],p2=pts[i+1],p3=pts[i+2]||p2;
      d+=` C${(p1[0]+(p2[0]-p0[0])/6).toFixed(1)} ${(p1[1]+(p2[1]-p0[1])/6).toFixed(1)} ${(p2[0]-(p3[0]-p1[0])/6).toFixed(1)} ${(p2[1]-(p3[1]-p1[1])/6).toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`}
    return d};
  const lineD=pts=>"M"+pts.map(p=>p.join(" ")).join(" L");
  function ridge(base,amp,seed,peaks){const pts=[];
    for(let x=-20;x<=1020;x+=10){let y=base;peaks.forEach(([px,h,w])=>{y-=h*Math.max(0,1-Math.abs(x-px)/w)});
      y+=amp*(Math.sin(x*.031+seed)*.6+Math.sin(x*.087+seed*2)*.3+Math.sin(x*.19+seed)*.12);pts.push([x,+(y*.857).toFixed(1)])}
    return pts}
  function scene(s,main,X,W){
    let r=7;const rnd=()=>(r=(r*9301+49297)%233280)/233280, g=sv(s,"g",{"aria-hidden":"true"}), sg=sv(g,"g",{transform:`scale(${X.toFixed(4)},1)`});
    for(let i=0;i<Math.round(46*X);i++){const x=rnd()*W,y=rnd()*120,big=rnd()>.85;sv(g,"circle",{class:"star",cx:x.toFixed(1),cy:y.toFixed(1),r:big?1.3:.7,opacity:(big?.8:.35+rnd()*.3).toFixed(2)})}
    [{pts:ridge(170,10,1.3,[[150,60,170],[470,95,190],[760,70,150]]),op:.28,w:.8},
     {pts:ridge(225,9,2.7,[[60,40,140],[330,85,170],[620,105,200],[980,70,160]]),op:.45,w:.9},
     {pts:ridge(285,7,.4,[[220,50,160],[540,70,190],[870,55,150]]),op:.65,w:1}].forEach(L=>{
      sv(sg,"path",{class:"body",d:lineD(L.pts)+" L1020 360 L-20 360 Z","stroke-width":L.w,"stroke-opacity":L.op});
      [10,22].forEach((o,k)=>sv(sg,"path",{class:"ln",d:lineD(L.pts.map(([x,y])=>[x,+(y+o+Math.sin(x*.05)*2).toFixed(1)])),"stroke-width":.6,opacity:(L.op*(.45-k*.18)).toFixed(2)}))});
    sv(g,"path",{class:"body",d:smooth(main)+` L${W+20} 360 L-20 360 Z`,"stroke-width":1.5});
    [12,26,44].forEach((o,k)=>sv(g,"path",{class:"ln",d:smooth(main.map(([x,y])=>[x,y+o+(x>W-100?(x-W+100)*.2:0)])),"stroke-width":.8,opacity:(.6-k*.17).toFixed(2)}));
    const wg=sv(g,"g",{transform:`scale(${X.toFixed(4)},1)`});
    // waves start below the lowest camp label (fix: they used to cross the TRẠI 1 caption)
    [[322,1.3,.85],[334,1.05,.6],[345,.9,.4],[354,.8,.25]].forEach(([y0,w,o],i)=>{const pts=[];
      for(let x=-20;x<=1020;x+=8)pts.push([x,+(y0+Math.sin(x*.018+i*1.7)*2.5+Math.sin(x*.05+i)*1.2).toFixed(1)]);
      sv(wg,"path",{class:"ln",d:lineD(pts),"stroke-width":w,opacity:o})});
  }
  function draw(camps,o){
    // drawn at the container's real pixel width so text keeps its size; ridges stretch, labels do not
    const W=Math.max(680,Math.round(o.width||1000)), H=W<900?340:400, X=W/1000;
    const svgEl=sv(null,"svg",{class:"lt-map",viewBox:`0 0 ${W} ${H}`,width:W,height:H,role:"group","aria-label":o.label||"Bản đồ lộ trình"}), s=sv(svgEl,"g",{transform:`translate(0,${H-360})`});
    const seq=[];camps.forEach(c=>{seq.push({c});if(c.gate)seq.push({g:c.gate})});
    const M=seq.length, step=840/Math.max(M-1,1);
    seq.forEach((q,k)=>{const t=M>1?k/(M-1):0;q.p=[+((80+k*step)*X).toFixed(1),+(262-204*Math.pow(t,1.15)+(q.c?6:-4)).toFixed(1)]});
    const P=seq.map(q=>q.p), last=P[M-1];
    scene(s,[[-20,250],...P,[Math.min(last[0]+55,W-10),last[1]+24],[W+20,last[1]+54]],X,W);
    // here: between the current camp and the next point, at pct; no current = trail walked to the end
    const ci=seq.findIndex(q=>q.c&&q.c.n===o.cur);
    let hi=M-1,here=last;
    if(ci>=0){hi=ci;const a=P[ci],b=P[ci+1]||a,f=Math.max(0,Math.min(1,(o.pct||0)/100))*.85;here=[+(a[0]+(b[0]-a[0])*f).toFixed(1),+(a[1]+(b[1]-a[1])*f).toFixed(1)]}
    const up={transform:"translate(0,-6)"};
    if(hi<M-1||ci>=0)sv(s,"path",{class:"trail-todo",d:smooth([here,...P.slice(hi+1)]),...up});
    if(hi>0||here!==P[0]){const dd=smooth([...P.slice(0,hi+1),here]);sv(s,"path",{class:"trail-done",d:dd,...up});sv(s,"path",{class:"sheen",d:dd,...up})}
    seq.forEach((q,k)=>{if(!q.g)return;const[x,y0]=q.p,y=y0-6,st=q.g.state,sz=k===M-1?13:9;
      sv(s,"polygon",{class:"cairn "+st,points:`${x},${y-sz*1.3} ${x+sz},${y+sz*.5} ${x-sz},${y+sz*.5}`});
      // label always above the cairn (fix: the open gate's label used to sit on the trail end)
      sv(s,"text",{class:"gid"+(st==="open"?" open":""),x,y:y-sz*1.3-7,"text-anchor":"middle"},q.g.key+(st==="open"?" · CHƯA QUA":""))});
    if(o.summit)sv(s,"text",{class:"summit",x:Math.min(last[0]+12,W-15),y:Math.max(last[1]-50,20),"text-anchor":"end"},o.summit);
    // crowded (many phases): shorter names, no caption line, so neighbouring camp labels do not overlap
    const gap=camps.length>1?step*(M-1)/(camps.length-1):840, crowd=gap*X<160, alt=gap*X<260, room=Math.max(8,Math.floor(gap*X*(alt?1.7:.95)/7.6)), cut=t=>t.length>room?t.slice(0,room-1).trimEnd()+"…":t;
    // alternate labels above/below; parity chosen so the current camp (flag) keeps its label below
    let ci2=0;const cpar=Math.max(0,camps.findIndex(c=>c.n===o.cur))%2;
    seq.forEach(q=>{if(!q.c)return;const c=q.c,up2=alt&&ci2++%2!==cpar&&c!==camps[camps.length-1],[x,y0]=q.p,y=y0-6;
      const g=sv(s,"g",{class:"camp "+c.state+(c.n===o.sel?" sel":""),tabindex:0,role:"button","aria-pressed":String(c.n===o.sel),"aria-label":`Trại ${c.n}: ${c.label}, ${LBL[c.state]}`});
      sv(g,"title",{},c.label);
      sv(g,"circle",{class:"ring",cx:x,cy:y,r:19});sv(g,"circle",{class:"dot",cx:x,cy:y,r:12});
      sv(g,"text",{class:"n",x,y:y+4},String(c.n));
      sv(g,"text",{class:"nm",x,y:up2?y-40:y+36,"text-anchor":"middle"},cut(c.label));
      if(!crowd)sv(g,"text",{class:"sm",x,y:up2?y-26:y+50,"text-anchor":"middle"},"TRẠI "+c.n+" · "+LBL[c.state].toUpperCase());
      const pick=()=>o.onPick&&o.onPick(c.n);
      g.addEventListener("click",pick);g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick()}})});
    if(ci>=0){const[hx,hy0]=here,hy=hy0-6,f=sv(s,"g",{class:"flag","aria-hidden":"true"});
      sv(f,"line",{x1:hx,y1:hy,x2:hx,y2:hy-44});sv(f,"polygon",{points:`${hx},${hy-44} ${hx+16},${hy-38} ${hx},${hy-32}`});sv(f,"circle",{cx:hx,cy:hy,r:4});
      sv(f,"text",{class:"here",x:hx<220?hx+22:hx-10,y:hy-28,"text-anchor":hx<220?"start":"end"},"BẠN Ở ĐÂY · "+(o.pct||0)+"%")}
    return svgEl;
  }
  return draw;
})();
