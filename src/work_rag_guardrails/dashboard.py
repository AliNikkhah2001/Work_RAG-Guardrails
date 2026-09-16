"""Guard dashboard — same :8200 server (/dashboard routes).

Stats (block percentages by category/stage/detector), terminated-sample
viewer (all formats: input text, output text, signals), SVG plots.
PII is masked at log time (events.mask_text); never raw here.
"""
from __future__ import annotations

import html
from typing import Any, Dict

from . import events
from .policies import load_active_policy


def _bar(label: str, pct: float, n: int) -> str:
    w = max(1, min(100, round(pct * 100)))
    return (f"<div class='row'><span class='lbl'>{html.escape(str(label))}</span>"
            f"<div class='track'><div class='fill' style='width:{w}%'></div></div>"
            f"<span class='val'>{pct*100:.1f}% ({n})</span></div>")


def _svg_bars(data: Dict[str, int], title: str) -> str:
    if not data:
        return f"<p>{html.escape(title)}: no data yet</p>"
    items = sorted(data.items(), key=lambda kv: -kv[1])[:12]
    mx = max(v for _, v in items) or 1
    W, H, bh, pad = 520, 26 * len(items) + 34, 18, 130
    rects = []
    for i, (k, v) in enumerate(items):
        y = 24 + i * 26
        bw = max(2, round((W - pad - 60) * v / mx))
        rects.append(
            f"<text x='4' y='{y+13}' font-size='11'>{html.escape(str(k)[:22])}</text>"
            f"<rect x='{pad}' y='{y}' width='{bw}' height='{bh}' fill='#b91c1c'/>"
            f"<text x='{pad+bw+6}' y='{y+13}' font-size='11'>{v}</text>")
    return (f"<h3>{html.escape(title)}</h3><svg width='{W}' height='{H}' "
            f"style='background:#fafafa;border:1px solid #ddd'>"
            + "".join(rects) + "</svg>")


PAGE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>Guardrails Dashboard</title><style>
body{font-family:Tahoma,sans-serif;margin:24px;background:#fff;color:#111;max-width:1000px}
.cards{display:flex;gap:12px;margin:12px 0}.card{border:1px solid #ddd;padding:12px 18px;border-radius:8px;min-width:120px;text-align:center}
.card b{font-size:24px;display:block}.row{display:flex;align-items:center;gap:8px;margin:4px 0}
.lbl{min-width:170px;font-size:13px}.track{flex:1;background:#eee;height:14px;border-radius:4px}.fill{background:#b91c1c;height:14px;border-radius:4px}
.val{min-width:110px;font-size:12px}table{border-collapse:collapse;width:100%;font-size:12px;margin-top:12px}
th,td{border:1px solid #ddd;padding:6px;text-align:right}th{background:#f3f4f6}
.sig{color:#92400e}.small{color:#555;font-size:12px}h2{border-bottom:2px solid #111;padding-bottom:4px}
</style></head><body>
<h2>داشبورد گاردریل</h2>
<p class="small">Policy: <b>{policy}</b> · Judge mode: <b>{mode}</b> · NeMo: <b>{nemo}</b> · <a href="/dashboard/api/stats">stats JSON</a> · <a href="/dashboard/api/events?limit=200">events JSON</a></p>
<div class="cards">
<div class="card"><b>{total}</b>decisions</div>
<div class="card"><b>{blocked}</b>blocked</div>
<div class="card"><b>{rate}%</b>block rate</div>
</div>
<h3>Blocked % by category</h3>{catbars}
{svgcat}
{svgdet}
<h3>Terminated samples (latest {n}, PII masked)</h3>
<table><tr><th>time</th><th>stage</th><th>category</th><th>signals</th><th>text</th></tr>{rows}</table>
</body></html>"""


def render_page() -> str:
    import datetime
    import os
    from .judge import judge_mode, nemo_mode
    st = events.stats()
    pol = load_active_policy()
    evs = [e for e in events.read_events(limit=200) if not e.get("allowed")][::-1][:100]
    tot = st["total"] or 1
    catbars = "".join(_bar(k, v / tot, v) for k, v in
                      sorted(st["by_category"].items(), key=lambda kv: -kv[1]))
    rows = []
    for e in evs:
        ts = datetime.datetime.fromtimestamp(e.get("ts", 0)).strftime("%m-%d %H:%M")
        sigs = ", ".join(f"{s.get('detector')}:{s.get('matched')}"
                         for s in e.get("signals", [])[:3])
        rows.append(f"<tr><td>{ts}</td><td>{html.escape(e.get('stage',''))}</td>"
                    f"<td>{html.escape(e.get('category',''))}</td>"
                    f"<td class='sig'>{html.escape(sigs)}</td>"
                    f"<td>{html.escape((e.get('text') or '')[:300])}</td></tr>")
    page = PAGE
    page = page.replace("{policy}", html.escape(f"{pol.get('id','-')} v{pol.get('version','-')}"))
    page = page.replace("{mode}", html.escape(judge_mode()))
    page = page.replace("{nemo}", html.escape(nemo_mode()))
    page = page.replace("{total}", str(st["total"]))
    page = page.replace("{blocked}", str(st["blocked"]))
    page = page.replace("{rate}", str(round(st["block_rate"]*100, 2)))
    page = page.replace("{catbars}", catbars or "<p>No blocks logged yet.</p>")
    page = page.replace("{svgcat}", _svg_bars(st["by_category"], "Blocks by category"))
    page = page.replace("{svgdet}", _svg_bars(st["by_detector"], "Blocks by detector signal"))
    page = page.replace("{n}", str(len(rows)))
    page = page.replace("{rows}", "".join(rows) or "<tr><td colspan=5>No terminated samples yet.</td></tr>")
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

    @app.get("/dashboard/api/plot.png", response_class=PlainTextResponse)
    async def dashboard_plot():
        return PlainTextResponse(
            "Use /dashboard (SVG plots) or /dashboard/api/stats (JSON).",
            media_type="text/plain")
