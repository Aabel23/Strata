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
  const STAT={done:"Done",doing:"In progress",plan:"Planned",blocked:"Blocked"};
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
    const svg=sv(document.createElement("div"),"svg",{class:"rm",viewBox:`0 0 ${Wd} ${H}`,width:Wd,height:H,role:"img","aria-label":"Roadmap"});
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

/* Roadmap tab map (design/roadmap-astra.html): layered gold ridges, camps = phases on the main ridge, cairns = gates,
   walked trail up to the "you are here" flag. Only geometry is computed here; text goes in via textContent.
   camps: [{n, label, state: done|doing|todo, gate: {key, state: done|open|todo} | null}]  (gate = cairn after that camp) */
const astraMap=(()=>{
  const NS="http://www.w3.org/2000/svg", LBL={done:"done",doing:"in progress",todo:"upcoming"};
  const sv=(p,tag,a,text)=>{const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);if(text!=null)e.textContent=text;if(p)p.appendChild(e);return e};
  // Catmull-Rom control points clamped into the segment's box: x stays increasing (no loops), y cannot overshoot (no kinks)
  const cl=(v,a,b)=>Math.max(Math.min(a,b),Math.min(Math.max(a,b),v));
  const ctrl=(p0,p1,p2,p3)=>[[cl(p1[0]+(p2[0]-p0[0])/6,p1[0],p2[0]),cl(p1[1]+(p2[1]-p0[1])/6,p1[1],p2[1])],[cl(p2[0]-(p3[0]-p1[0])/6,p1[0],p2[0]),cl(p2[1]-(p3[1]-p1[1])/6,p1[1],p2[1])]];
  const smooth=pts=>{let d=`M${pts[0][0]} ${pts[0][1]}`;
    for(let i=0;i<pts.length-1;i++){const p1=pts[i],p2=pts[i+1],[c1,c2]=ctrl(pts[i-1]||p1,p1,p2,pts[i+2]||p2);
      d+=` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`}
    return d};
  // real text widths (same fonts as the CSS, canvas measures what the svg will draw)
  let ctx=null;const tw=(t,font,ls)=>{if(!ctx)ctx=document.createElement("canvas").getContext("2d");const cs=getComputedStyle(document.documentElement);
    ctx.font=font.replace("D",cs.getPropertyValue("--display")||"serif").replace("M",cs.getPropertyValue("--mono")||"monospace");return ctx.measureText(t).width+t.length*ls};
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
    [12,26,44].forEach((o,k)=>sv(g,"path",{class:"ln",d:smooth(main.map(([x,y])=>[x,y+o+(x>W*.95?(x-W*.95)*.2:0)])),"stroke-width":.8,opacity:(.6-k*.17).toFixed(2)}));
    const wg=sv(g,"g",{transform:`scale(${X.toFixed(4)},1)`});
    // waves start below the lowest camp label (fix: they used to cross the TRẠI 1 caption)
    [[330,1.3,.85],[340,1.05,.6],[349,.9,.4],[356,.8,.25]].forEach(([y0,w,o],i)=>{const pts=[];
      for(let x=-20;x<=1020;x+=8)pts.push([x,+(y0+Math.sin(x*.018+i*1.7)*2.5+Math.sin(x*.05+i)*1.2).toFixed(1)]);
      sv(wg,"path",{class:"ln",d:lineD(pts),"stroke-width":w,opacity:o})});
  }
  function draw(camps,o){
    // drawn at the container's real pixel width so text keeps its size; ridges stretch, labels do not
    const W=Math.max(680,Math.round(o.width||1000)), H=W<900?340:400, X=W/1000;
    const svgEl=sv(null,"svg",{class:"lt-map",viewBox:`0 0 ${W} ${H}`,width:W,height:H,role:"group","aria-label":o.label||"Roadmap map"}), s=sv(svgEl,"g",{transform:`translate(0,${H-360})`});
    const seq=[];camps.forEach(c=>{seq.push({c});if(c.gate)seq.push({g:c.gate})});
    // route: spread over the width with a real climb whatever the phase count; the summit is always the last vertex
    const M=seq.length, x0=Math.max(90,W*.07), x1=W*.86, sum=[+(W*.93).toFixed(1),62];
    seq.forEach((q,k)=>{const t=M>1?k/(M-1):0;q.p=[+(x0+(x1-x0)*t).toFixed(1),+(268-170*Math.pow(t,1.1)+(q.c?6:-4)).toFixed(1)]});
    const P=seq.map(q=>q.p), lastG=seq[M-1].g, R=lastG?P:[...P,sum], top=R[R.length-1];
    // few points: add terraces between them so the ridge climbs in steps instead of one straight ramp
    if(R.length<5){const d=[R[0]];for(let k=1;k<R.length;k++){const a=R[k-1],b=R[k];[[.33,-.12],[.66,.18]].forEach(([t,j])=>{const dy=b[1]-a[1];d.push([+(a[0]+(b[0]-a[0])*t).toFixed(1),+(a[1]+dy*t+dy*j).toFixed(1),1])});d.push(b)}R.splice(0,R.length,...d)}
    scene(s,[[-20,256],...R.map(p=>[p[0],p[1]]),[Math.min(top[0]+55,W-10),top[1]+24],[W+20,top[1]+54]],X,W);
    const ci=seq.findIndex(q=>q.c&&q.c.n===o.cur);
    // here: on the way from the current camp to the next route point, at pct; no current = walked to the top
    let here=top, done=R, todo=[];
    if(ci>=0){const f=Math.max(0,Math.min(1,(o.pct||0)/100))*.85, i0=R.indexOf(P[ci]), nx=P[ci+1]||(lastG?P[ci]:sum), i1=Math.max(i0,R.indexOf(nx));
      // walk the route polyline (terraces included) from this camp toward the next real point
      const seg=R.slice(i0,i1+1), L=seg.slice(1).map((p,k)=>Math.hypot(p[0]-seg[k][0],p[1]-seg[k][1]));let d=f*L.reduce((x,y)=>x+y,0),k=0;
      while(k<L.length-1&&d>L[k]){d-=L[k];k++}
      const a=seg[k],b=seg[k+1]||a,t=L[k]?d/L[k]:0;here=[+(a[0]+(b[0]-a[0])*t).toFixed(1),+(a[1]+(b[1]-a[1])*t).toFixed(1)];
      done=[...R.filter(p=>p[0]<here[0]),here];todo=[here,...R.filter(p=>p[0]>here[0])]}
    const up={transform:"translate(0,-6)"}, xy=a=>a.map(p=>[p[0],p[1]]);
    // put "here" on the drawn curve (Catmull-Rom segment, t taken from x), not on the straight polyline
    if(ci>=0){const k=Math.max(0,R.findIndex((p,i)=>R[i+1]&&p[0]<=here[0]&&here[0]<=R[i+1][0]));
      const p0=R[k-1]||R[k],p1=R[k],p2=R[k+1]||p1,p3=R[k+2]||p2,t=p2[0]>p1[0]?(here[0]-p1[0])/(p2[0]-p1[0]):0,u=1-t;
      const [a1,a2]=ctrl(p0,p1,p2,p3),c1=a1[1],c2=a2[1];here=[here[0],+(u*u*u*p1[1]+3*u*u*t*c1+3*u*t*t*c2+t*t*t*p2[1]).toFixed(1)]}
    // one curve for the whole route, split at "here" by two clip rects, so the walked part sits exactly on the ridge
    const rd=smooth(xy(R)), id="ltc"+(++draw.n), defs=sv(s,"defs",{});
    sv(sv(defs,"clipPath",{id:id+"a"}),"rect",{x:-50,y:-200,width:here[0]+50,height:800});
    sv(sv(defs,"clipPath",{id:id+"b"}),"rect",{x:here[0],y:-200,width:W+50,height:800});
    if(todo.length>1)sv(s,"path",{class:"trail-todo",d:rd,"clip-path":`url(#${id}b)`,...up});
    if(done.length>1){sv(s,"path",{class:"trail-done",d:rd,"clip-path":`url(#${id}a)`,...up});sv(s,"path",{class:"sheen",d:rd,"clip-path":`url(#${id}a)`,...up})}
    if(!lastG)sv(s,"polygon",{class:"cairn",points:`${sum[0]},${sum[1]-6-17} ${sum[0]+13},${sum[1]-6+6.5} ${sum[0]-13},${sum[1]-6+6.5}`});

    /* label placement: boxes in svg-group coords. Obstacles = route samples, dots, cairns, flag, already placed labels.
       Each label tries candidate slots in order and takes the first free one (else the least bad), clamped inside the map. */
    const OFF=H-360, PAD=10, boxes=[], route=[];
    for(let k=0;k<R.length-1;k++)for(let t=0;t<=1;t+=.05)route.push([R[k][0]+(R[k+1][0]-R[k][0])*t,R[k][1]-6+(R[k+1][1]-R[k][1])*t]);
    const hit=(b,a)=>b.x<a.x+a.w&&a.x<b.x+b.w&&b.y<a.y+a.h&&a.y<b.y+b.h;
    const cost=b=>{let c=0;const g={x:b.x-5,y:b.y-5,w:b.w+10,h:b.h+10};
      boxes.forEach(a=>{if(hit(g,a))c+=100});route.forEach(([x,y])=>{if(x>g.x&&x<g.x+g.w&&y>g.y&&y<g.y+g.h)c+=4});
      if(b.y<-OFF+4||b.y+b.h>360-30)c+=6;if(b.y+b.h>324)c+=25;return c};
    const clamp=b=>({...b,x:Math.max(PAD,Math.min(W-PAD-b.w,b.x))});
    const place=(cands,w,h)=>{let best=null;const [x0,y0]=cands[0];  // after the fixed slots, sweep a ring of offsets around the first one
      cands=[...cands,...[0,-1,1,-2,2,-3,3].flatMap(m=>[-1,0,1].map(n=>[x0+n*(w+12)/1,y0+m*(h+8)])),...[-1,1].map(n=>[x0+n*(w+12)*1.5,y0])];
      for(const [cx,cy] of cands){const b=clamp({x:cx,y:cy,w,h}), c=cost(b);if(!best||c<best.c)best={...b,c};if(c===0)break}return best};
    const wName=t=>tw(t,"600 15px D",.15)+2, wCap=t=>tw(t,"9.5px M",1.14)+2;
    // reserved: dots, cairns, flag, summit
    seq.forEach(q=>{const[x,y]=q.p;boxes.push({x:x-14,y:y-6-14,w:28,h:28})});
    if(ci>=0)boxes.push({x:here[0]-3,y:here[1]-6-46,w:20,h:46});
    if(o.summit){const w=tw(o.summit,"italic 500 17px D",.34)+4, b=clamp({x:top[0]+14-w,y:top[1]-6-66,w,h:20});
      if(top[1]-6-66<-OFF+2)b.y=-OFF+2;boxes.push(b);sv(s,"text",{class:"summit",x:b.x+w,y:b.y+15,"text-anchor":"end"},o.summit)}
    if(ci>=0){const t="YOU ARE HERE"+(o.pct==null?"":" · "+o.pct+"%"), w=tw(t,"700 11px M",1.54)+4, hx=here[0], hy=here[1]-6;
      const b=place([[hx-10-w,hy-40],[hx+22,hy-46],[hx-w/2,hy-66],[hx-10-w,hy-14]],w,14);boxes.push(b);
      const f=sv(s,"g",{class:"flag","aria-hidden":"true"});
      sv(f,"line",{x1:hx,y1:hy,x2:hx,y2:hy-44});sv(f,"polygon",{points:`${hx},${hy-44} ${hx+16},${hy-38} ${hx},${hy-32}`});sv(f,"circle",{cx:hx,cy:hy,r:4});
      sv(f,"text",{class:"here",x:b.x,y:b.y+11},t)}
    seq.forEach((q,k)=>{if(!q.g)return;const[x,y0]=q.p,y=y0-6,st=q.g.state,sz=k===M-1?13:9;
      sv(s,"polygon",{class:"cairn "+st,points:`${x},${y-sz*1.3} ${x+sz},${y+sz*.5} ${x-sz},${y+sz*.5}`});
      const top=y-sz*1.3;let pk=null;
      for(const t of st==="open"?[q.g.key+" · CHƯA QUA",q.g.key]:[q.g.key]){const w=tw(t,"700 10px M",.8)+4;  // short key when the long one collides
        const b=place([[x-w/2,top-24],[x+8,top-20],[x-w-8,top-20],[x-w/2,top-36],[x+12,top-32],[x-w-12,top-32],[x-w/2,y+sz*.5+8]],w,13);
        if(!pk||b.c<pk.b.c)pk={b,t};if(b.c===0)break}
      boxes.push(pk.b);const g=sv(s,"text",{class:"gid"+(st==="open"?" open":""),x:pk.b.x,y:pk.b.y+10},pk.t);if(pk.t===q.g.key&&st==="open")sv(g,"title",{},q.g.key+" · not passed")});
    // camps: current first, then left to right. Variants: one line, two lines, then short "Camp n" (full name in <title>)
    const order=seq.filter(q=>q.c).sort((a,b)=>(b.c.n===o.cur)-(a.c.n===o.cur));
    const wrap2=t=>{const w=t.split(" ");let best=null;for(let i=1;i<w.length;i++){const a=w.slice(0,i).join(" "),b=w.slice(i).join(" "),m=Math.max(a.length,b.length);if(!best||m<best.m)best={l:[a,b],m}}return best?best.l:[t]};
    order.forEach(q=>{const c=q.c,[x,y0]=q.p,y=y0-6, cap="PHASE "+c.n+" · "+LBL[c.state].toUpperCase();
      let pick=null;
      for(const lines of [[c.label],wrap2(c.label),[]]){
        const cp=lines.length?cap:"PHASE "+c.n, w=Math.max(wCap(cp),...lines.map(wName)), h=lines.length*17+14;
        const cands=[[x-w/2,y+20],[x-w/2,y-20-h],[x-w-8,y-12-h],[x+10,y+16],[x-w-10,y+16],[x+12,y-12-h]];
        const b=place(cands,w,h);if(!pick||b.c<pick.b.c)pick={b,lines,cap:cp};if(b.c===0)break}
      boxes.push(pick.b);q.lab=pick});
    seq.forEach(q=>{if(!q.c)return;const c=q.c,[x,y0]=q.p,y=y0-6,{b,lines,cap}=q.lab,cx=b.x+b.w/2;
      const g=sv(s,"g",{class:"camp "+c.state+(c.n===o.sel?" sel":""),tabindex:0,role:"button","aria-pressed":String(c.n===o.sel),"aria-label":`Camp ${c.n}: ${c.label}, ${LBL[c.state]}`});
      sv(g,"title",{},c.label);
      sv(g,"circle",{class:"ring",cx:x,cy:y,r:19});sv(g,"circle",{class:"dot",cx:x,cy:y,r:12});
      sv(g,"text",{class:"n",x,y:y+4},String(c.n));
      lines.forEach((l,i)=>sv(g,"text",{class:"nm",x:cx,y:b.y+14+i*17,"text-anchor":"middle"},l));
      sv(g,"text",{class:"sm",x:cx,y:b.y+lines.length*17+11,"text-anchor":"middle"},cap);
      const pk=()=>o.onPick&&o.onPick(c.n);
      g.addEventListener("click",pk);g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pk()}})});
    return svgEl;
  }
  draw.n=0;
  return draw;
})();
