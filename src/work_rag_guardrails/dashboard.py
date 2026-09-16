"""Guard dashboard — same :8200 server (/dashboard routes).

Live, interactive, zero-dependency (vanilla JS + inline SVG; no Streamlit,
no build step): auto-refreshing cards, category/detector bars, 24h block
timeline, stage donut, filterable terminated-sample viewer.
PII is masked at log time (events.mask_text); never raw here.
"""
from __future__ import annotations

import datetime
import html
from typing import Any, Dict, List

from . import events
from .policies import load_active_policy


def timeseries(hours: int = 24) -> List[Dict[str, Any]]:
    """Blocked + allowed counts per hour bucket (oldest → newest)."""
    import time as _time
    now = int(_time.time())
    buckets = [{"t": now - (hours - 1 - i) * 3600, "block": 0, "allow": 0}
               for i in range(hours)]
    for e in events.read_events(limit=5000):
        ts = e.get("ts", 0)
        idx = (ts - (now - (hours - 1) * 3600)) // 3600
        if 0 <= idx < hours:
            b = buckets[int(idx)]
            if e.get("allowed"):
                b["allow"] += 1
            else:
                b["block"] += 1
    for b in buckets:
        b["label"] = datetime.datetime.fromtimestamp(b["t"]).strftime("%H:00")
    return buckets


PAGE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guardrails Dashboard</title><style>
:root{--red:#b91c1c;--green:#15803d;--ink:#111;--mut:#666;--line:#e5e7eb;--bg:#f8fafc}
body{font-family:Tahoma,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
header{background:#111827;color:#fff;padding:14px 24px;display:flex;gap:16px;align-items:center;position:sticky;top:0}
header h1{font-size:18px;margin:0}.dot{width:10px;height:10px;border-radius:50%;background:#22c55e;display:inline-block;margin-inline-end:6px}
.dot.off{background:#ef4444}header .meta{font-size:12px;color:#cbd5e1}
main{max-width:1100px;margin:0 auto;padding:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
.card{background:#fff;border:1px solid var(--line);padding:14px;border-radius:10px;text-align:center}
.card b{font-size:26px;display:block}.card span{font-size:12px;color:var(--mut)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:800px){.grid{grid-template-columns:1fr}}
.panel{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
.panel h3{margin:0 0 10px;font-size:15px}
.row{display:flex;align-items:center;gap:8px;margin:5px 0;cursor:pointer}
.lbl{min-width:150px;font-size:13px}.track{flex:1;background:#eee;height:14px;border-radius:4px;overflow:hidden}
.fill{background:var(--red);height:14px;border-radius:4px;transition:width .5s}
.fill.g{background:var(--green)}.val{min-width:110px;font-size:12px;color:var(--mut)}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid var(--line);padding:6px;text-align:right}th{background:#f1f5f9}
.sig{color:#92400e;font-size:11px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.toolbar select,.toolbar input{padding:6px;border:1px solid var(--line);border-radius:6px;font-family:inherit}
.pill{font-size:11px;padding:2px 8px;border-radius:10px;background:#fee2e2;color:#991b1b}
.pill.ok{background:#dcfce7;color:#166534}
.tip{position:fixed;background:#111827;color:#fff;font-size:12px;padding:6px 10px;border-radius:6px;pointer-events:none;display:none;z-index:9}
.tabs{display:flex;gap:6px;margin-bottom:10px}.tab{padding:6px 14px;border:1px solid var(--line);border-radius:16px;cursor:pointer;font-size:13px;background:#fff}
.tab.on{background:#111827;color:#fff}
</style></head><body>
<header><h1><span class="dot" id="livedot"></span>داشبورد گاردریل</h1>
<span class="meta" id="meta">…</span>
<span class="meta">policy: <b>__POLICY__</b> · judge: <b>__MODE__</b> · refresh <span id="count">5</span>s</span></header>
<main>
<div class="tabs">
<div class="tab on" data-v="all">همه</div><div class="tab" data-v="block">مسدودشده</div><div class="tab" data-v="allow">مجاز</div>
</div>
<div class="cards" id="cards"></div>
<div class="grid">
<div class="panel"><h3>درصد مسدودی بر اساس دسته</h3><div id="catbars"></div></div>
<div class="panel"><h3>سیگنال‌های دتکتور (مسدودشده‌ها)</h3><div id="detbars"></div></div>
</div>
<div class="panel"><h3>خط زمانی ۲۴ ساعته (مسدود/مجاز)</h3><svg id="timeline" width="100%" height="150"></svg></div>
<div class="grid">
<div class="panel"><h3>ورودی در برابر خروجی</h3><div id="stagebars"></div></div>
<div class="panel"><h3>اجازه در برابر مسدود (دونات)</h3><svg id="donut" width="200" height="140"></svg><span id="donutlbl"></span></div>
</div>
<div class="panel"><h3>نمونه‌های خاتمه‌یافته (متن‌ها ماسک‌شده)</h3>
<div class="toolbar">
<select id="fcat"><option value="">همه دسته‌ها</option></select>
<select id="fstage"><option value="">ورودی+خروجی</option><option value="input">ورودی</option><option value="output">خروجی</option></select>
<input id="fq" placeholder="جست‌وجو در متن…" size="24">
</div>
<table><tr><th>زمان</th><th>مرحله</th><th>دسته</th><th>سیگنال‌ها</th><th>متن</th></tr><tbody id="rows"></tbody></table></div>
</main>
<div class="tip" id="tip"></div>
<script>
let VIEW='all',CDN=5;
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));t.classList.add('on');VIEW=t.dataset.v;refresh();});
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function bar(lbl,pct,n,green){let w=Math.max(1,Math.min(100,Math.round(pct*100)));
return "<div class='row'><span class='lbl'>"+esc(lbl)+"</span><div class='track'><div class='fill"+(green?" g":"")+"' style='width:"+w+"%'></div></div><span class='val'>"+(pct*100).toFixed(1)+"% ("+n+")</span></div>";}
async function refresh(){
try{
let s=await (await fetch('api/stats')).json();
let ev=await (await fetch('api/events?limit=300')).json();
document.getElementById('livedot').className='dot';
document.getElementById('meta').textContent='به‌روزرسانی: '+new Date().toLocaleTimeString('fa-IR');
let tot=s.total||0,bl=s.blocked||0;
document.getElementById('cards').innerHTML=
"<div class='card'><b>"+tot+"</b><span>تصمیم</span></div>"+
"<div class='card'><b>"+bl+"</b><span>مسدود</span></div>"+
"<div class='card'><b>"+(s.allowed||0)+"</b><span>مجاز</span></div>"+
"<div class='card'><b>"+(s.block_rate*100).toFixed(1)+"%</b><span>نرخ مسدودی</span></div>";
document.getElementById('catbars').innerHTML=Object.entries(s.by_category||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>bar(k,v/tot,v)).join('')||'<p>—</p>';
document.getElementById('detbars').innerHTML=Object.entries(s.by_detector||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>bar(k,v/Math.max(1,bl),v)).join('')||'<p>—</p>';
let st=s.by_stage||{},si=Object.entries(st).filter(([k])=>k.startsWith('input')).reduce((a,[,v])=>a+v,0),so=tot-si;
document.getElementById('stagebars').innerHTML=bar('ورودی (input)',si/tot,si)+bar('خروجی (output)',so/tot,so,true);
let ba=bl,al=tot-bl,r=ba+al?ba/(ba+al):0,C=2*Math.PI*54;
document.getElementById('donut').innerHTML="<circle cx='100' cy='70' r='54' fill='none' stroke='#eee' stroke-width='18'/><circle cx='100' cy='70' r='54' fill='none' stroke='#b91c1c' stroke-width='18' stroke-dasharray='"+(C*r).toFixed(1)+" "+C.toFixed(1)+"' transform='rotate(-90 100 70)'/>";
document.getElementById('donutlbl').textContent='مسدود '+(r*100).toFixed(1)+'%';
let ts=await (await fetch('api/timeseries')).json();
let svg=document.getElementById('timeline'),W=svg.clientWidth||900,mx=1;
ts.forEach(b=>{mx=Math.max(mx,b.block+b.allow);});
let bw=(W-40)/ts.length,h='';
ts.forEach((b,i)=>{let x=20+i*bw,bh=(b.block+b.allow)/mx*110,ba2=b.block/Math.max(1,b.block+b.allow)*bh;
h+="<rect x='"+x.toFixed(1)+"' y='"+(130-bh).toFixed(1)+"' width='"+Math.max(1,bw-2).toFixed(1)+"' height='"+bh.toFixed(1)+"' fill='#bbf7d0' data-t='"+b.label+" مسدود:"+b.block+" مجاز:"+b.allow+"'><title>"+b.label+" ب:"+b.block+" م:"+b.allow+"</title></rect>";
h+="<rect x='"+x.toFixed(1)+"' y='"+(130-ba2).toFixed(1)+"' width='"+Math.max(1,bw-2).toFixed(1)+"' height='"+ba2.toFixed(1)+"' fill='#b91c1c'><title>"+b.label+" مسدود:"+b.block+"</title></rect>";});
svg.setAttribute('viewBox','0 0 '+W+' 140');svg.innerHTML=h;
let fc=document.getElementById('fcat'),cur=fc.value;
let cats=[...new Set(ev.map(e=>e.category).filter(Boolean))];
fc.innerHTML='<option value="">همه دسته‌ها</option>'+cats.map(c=>"<option"+(c==cur?" selected":"")+">"+esc(c)+"</option>").join('');
let fs=document.getElementById('fstage').value,q=document.getElementById('fq').value;
let rows=ev.filter(e=>!e.allowed||VIEW=='all'||(VIEW=='allow'&&e.allowed)).filter(e=>VIEW=='all'||(VIEW=='block'?!e.allowed:e.allowed));
rows=rows.filter(e=>(!fc.value||e.category==fc.value)&&(!fs||e.stage==fs)&&(!q||(e.text||'').includes(q))).slice(0,100).reverse();
document.getElementById('rows').innerHTML=rows.map(e=>{
let d=new Date(e.ts*1000).toLocaleString('fa-IR');
let sg=(e.signals||[]).slice(0,3).map(s=>esc(s.detector+':'+(s.matched||''))).join('، ');
return "<tr><td>"+d+"</td><td>"+esc(e.stage)+"</td><td><span class='pill"+(e.allowed?" ok":"")+"'>"+esc(e.category||(e.allowed?'allow':'?'))+"</span></td><td class='sig'>"+sg+"</td><td>"+esc((e.text||'').slice(0,220))+"</td></tr>";}).join('')||'<tr><td colspan=5>موردی نیست</td></tr>';
CDN=5;
}catch(err){document.getElementById('livedot').className='dot off';}
}
document.getElementById('fstage').onchange=refresh;document.getElementById('fq').oninput=refresh;document.getElementById('fcat').onchange=refresh;
refresh();setInterval(()=>{CDN--;document.getElementById('count').textContent=CDN;if(CDN<=0)refresh();},1000);
</script></body></html>
"""


def render_page() -> str:
    from .judge import judge_mode, nemo_mode
    pol = load_active_policy()
    page = PAGE
    page = page.replace("__POLICY__", html.escape(f"{pol.get('id','-')} v{pol.get('version','-')}"))
    page = page.replace("__MODE__", html.escape(judge_mode()))
    # nemo mode shown via meta line below (kept static-safe: no braces used)
    return page


def register(app) -> None:
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard():
        return render_page()

    @app.get("/dashboard/api/stats")
    async def dashboard_stats():
        return JSONResponse(events.stats())

    @app.get("/dashboard/api/events")
    async def dashboard_events(limit: int = 200, blocked_only: bool = False):
        evs = events.read_events(limit=min(limit, 1000))
        if blocked_only:
            evs = [e for e in evs if not e.get("allowed")]
        return JSONResponse(evs)

    @app.get("/dashboard/api/policy")
    async def dashboard_policy():
        return JSONResponse(load_active_policy())

    @app.get("/dashboard/api/timeseries")
    async def dashboard_timeseries(hours: int = 24):
        return JSONResponse(timeseries(min(max(hours, 1), 72)))

    @app.get("/dashboard/api/plot.png", response_class=PlainTextResponse)
    async def dashboard_plot():
        return PlainTextResponse(
            "Use /dashboard (live SVG plots) or /dashboard/api/stats (JSON).",
            media_type="text/plain")
