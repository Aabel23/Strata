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
