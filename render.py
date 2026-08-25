#!/usr/bin/env python3
"""Render market_data.json (+ optional commentary.json) into the daily brief HTML."""

import json, sys, os, html, math
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")   # handles EST/EDT automatically
except Exception:
    ET = timezone(timedelta(hours=-4))

def short_date(ds):
    """2026-08-21 -> 'Aug 21'; monthly series (day 01) -> 'Jul 2026'."""
    try:
        y, m, day = (int(x) for x in ds.split("-"))
    except Exception:
        return ds
    mon = ("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")[m-1]
    return f"{mon} {y}" if day == 1 else f"{mon} {day}"


def fmt(v, dec=2, comma=True):
    if v is None: return "—"
    return f"{v:,.{dec}f}" if comma else f"{v:.{dec}f}"

def signed(v, dec=2, suffix=""):
    if v is None: return "—"
    return f"{v:+,.{dec}f}{suffix}"

def dircls(v):
    if v is None: return "flat"
    return "up" if v > 0 else ("down" if v < 0 else "flat")

def arrow(v):
    if v is None: return "·"
    return "▲" if v > 0 else ("▼" if v < 0 else "■")

def spark(series, w=104, h=28, cls="up"):
    """Inline sparkline: area fill + line + emphasized endpoint."""
    pts = [p for p in (series or []) if p is not None]
    if len(pts) < 3:
        return '<div class="spark-empty" aria-hidden="true"></div>'
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    n = len(pts)
    xs = [i * w / (n - 1) for i in range(n)]
    ys = [h - 2 - (p - lo) / rng * (h - 4) for p in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"0,{h} {line} {w},{h}"
    return (
        f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'preserveAspectRatio="none" aria-hidden="true" focusable="false">'
        f'<polygon class="spark-fill" points="{area}"/>'
        f'<polyline class="spark-line" points="{line}"/>'
        f'<circle class="spark-dot" cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.4"/>'
        f'</svg>')

def esc(s):
    return html.escape(str(s), quote=True)

# ---------------------------------------------------------------- components
def hero_tile(label, value, sub, delta_txt, d, series=None, note="", tone=None):
    # tone="flat" for policy indicators (CPI, unemployment) where a rise is not
    # "good" and a fall is not "bad" — the arrow still shows direction.
    cls = tone or dircls(d)
    sub_txt = esc(sub) + (f' <span class="asof">· {esc(note)}</span>' if note else '')
    return f'''
    <div class="tile">
      <div class="tile-head"><span class="tile-label">{esc(label)}</span></div>
      <div class="tile-value">{value}</div>
      <div class="tile-foot">
        <span class="delta {cls}"><span class="arw" aria-hidden="true">{arrow(d)}</span>{delta_txt}</span>
        {spark(series, cls=cls) if series else ''}
      </div>
      <div class="tile-sub">{sub_txt}</div>
    </div>'''

def row(label, value, delta_html, extra=""):
    return (f'<tr><th scope="row">{esc(label)}</th><td class="num">{value}</td>'
            f'<td class="num">{delta_html}</td><td class="num dim">{extra}</td></tr>')

def delta_cell(v, dec=2, suffix="", bp=False, tone=None):
    if v is None: return '<span class="delta flat">—</span>'
    cls = tone or dircls(v)
    txt = f"{v*100:+.0f} bp" if bp else f"{v:+,.{dec}f}{suffix}"
    return f'<span class="delta {cls}"><span class="arw" aria-hidden="true">{arrow(v)}</span>{txt}</span>'


def history_chart(series, W=760, H=150, accent=True):
    """6-month history line for a single series: area fill, faint grid, endpoint dot."""
    pts = [p for p in (series or []) if p is not None]
    if len(pts) < 5:
        return '<p class="dim">History unavailable.</p>'
    PL, PR, PT, PB = 48, 14, 14, 20
    lo, hi = min(pts), max(pts)
    pad = max((hi - lo) * 0.18, 0.05)
    lo, hi = lo - pad, hi + pad
    n = len(pts)
    def px(i): return PL + i * (W - PL - PR) / (n - 1)
    def py(v): return PT + (hi - v) / (hi - lo) * (H - PT - PB)
    grid, ticks = [], []
    for i in range(4):
        v = lo + (hi - lo) * i / 3
        y = py(v)
        grid.append(f'<line class="grid" x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}"/>')
        ticks.append(f'<text class="axis" x="{PL-7}" y="{y+3.5:.1f}" text-anchor="end">{v:.2f}%</text>')
    line = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(pts))
    area = f"{PL},{H-PB} {line} {W-PR},{H-PB}"
    cls = "hist-accent" if accent else "hist-plain"
    return (f'<div class="chart-wrap"><svg viewBox="0 0 {W} {H}" class="hist {cls}" role="img" '
            f'aria-label="Six-month history">{"".join(grid)}'
            f'<polygon class="hist-fill" points="{area}"/>'
            f'<polyline class="hist-line" points="{line}"/>'
            f'<circle class="hist-dot" cx="{px(n-1):.1f}" cy="{py(pts[-1]):.1f}" r="3.4"/>'
            f'{"".join(ticks)}'
            f'<text class="axis" x="{PL}" y="{H-6}">6 months ago</text>'
            f'<text class="axis" x="{W-PR}" y="{H-6}" text-anchor="end">today</text>'
            f'</svg></div>')


def ten_year_panel(F):
    """The 10-year gets top billing: big number, deltas, and its own history."""
    d = F.get("DGS10")
    if not d:
        return ""
    s = d.get("series") or []
    chg = d.get("chg")
    stats = []
    for lbl, k in (("1 day", 1), ("1 month", 22), ("3 months", 64), ("6 months", len(s) - 1)):
        if len(s) > k > 0:
            delta = (d["value"] - s[-1 - k]) * 100
            stats.append(f'<div class="stat"><span class="stat-k">{lbl}</span>'
                         f'<span class="delta {dircls(delta)}">'
                         f'<span class="arw" aria-hidden="true">{arrow(delta)}</span>'
                         f'{delta:+.0f} bp</span></div>')
    if s:
        stats.append(f'<div class="stat"><span class="stat-k">6-month range</span>'
                     f'<span class="stat-v">{min(s):.2f}% – {max(s):.2f}%</span></div>')
    sp = F.get("T10Y2Y")
    if sp:
        stats.append(f'<div class="stat"><span class="stat-k">2s10s</span>'
                     f'<span class="stat-v">{sp["value"]:+.2f}%</span></div>')
    return f'''<div class="hero10">
      <div class="hero10-top">
        <div>
          <div class="hero10-label">10-Year Treasury</div>
          <div class="hero10-value">{d["value"]:.2f}<span class="pct">%</span></div>
          <div class="delta {dircls(chg)}"><span class="arw" aria-hidden="true">{arrow(chg)}</span>
            {(chg or 0)*100:+.0f} bp vs prior close</div>
        </div>
        <div class="hero10-stats">{"".join(stats)}</div>
      </div>
      {history_chart(s)}
      <div class="hero10-foot">As of {short_date(d["date"])}</div>
    </div>'''

# ---------------------------------------------------------------- yield curve
def yield_curve_svg(F):
    tenors = [("DGS3MO", "3M", 0.25), ("DGS2", "2Y", 2), ("DGS5", "5Y", 5),
              ("DGS10", "10Y", 10), ("DGS30", "30Y", 30)]
    cur, prior = [], []
    for sid, lab, x in tenors:
        f = F.get(sid)
        if not f: continue
        cur.append((lab, x, f["value"]))
        s = f.get("series") or []
        if len(s) > 64:
            prior.append((lab, x, s[-64]))
    if len(cur) < 3:
        return '<p class="dim">Curve data unavailable.</p>'

    W, H = 640, 240
    PL, PR, PT, PB = 46, 18, 18, 34
    vals = [v for _, _, v in cur] + [v for _, _, v in prior]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.25, 0.15)
    lo, hi = lo - pad, hi + pad
    import math
    xs = [math.log(x) for _, x, _ in cur]
    xmin, xmax = min(xs), max(xs)
    def px(x): return PL + (math.log(x) - xmin) / (xmax - xmin) * (W - PL - PR)
    def py(v): return PT + (hi - v) / (hi - lo) * (H - PT - PB)

    grid, ticks = [], []
    steps = 4
    for i in range(steps + 1):
        v = lo + (hi - lo) * i / steps
        y = py(v)
        grid.append(f'<line class="grid" x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}"/>')
        ticks.append(f'<text class="axis" x="{PL-8}" y="{y+3.5:.1f}" text-anchor="end">{v:.2f}%</text>')
    for lab, x, _ in cur:
        ticks.append(f'<text class="axis" x="{px(x):.1f}" y="{H-12}" text-anchor="middle">{lab}</text>')

    def path(pts):
        return " ".join(f"{px(x):.1f},{py(v):.1f}" for _, x, v in pts)

    prior_el = ""
    if len(prior) >= 3:
        prior_el = (f'<polyline class="curve-prior" points="{path(prior)}"/>' +
                    "".join(f'<circle class="dot-prior" cx="{px(x):.1f}" cy="{py(v):.1f}" r="2.6"/>'
                            for _, x, v in prior))
    dots = "".join(
        f'<circle class="dot-cur" cx="{px(x):.1f}" cy="{py(v):.1f}" r="4"><title>{lab}: {v:.2f}%</title></circle>'
        for lab, x, v in cur)
    labels = "".join(
        f'<text class="pt-label" x="{px(x):.1f}" y="{py(v)-11:.1f}" text-anchor="middle">{v:.2f}</text>'
        for lab, x, v in cur)

    return f'''<div class="chart-wrap">
      <svg viewBox="0 0 {W} {H}" class="curve" role="img"
           aria-label="US Treasury yield curve, current versus three months ago">
        {''.join(grid)}
        {prior_el}
        <polyline class="curve-cur" points="{path(cur)}"/>
        {dots}{labels}{''.join(ticks)}
      </svg>
    </div>
    <div class="legend">
      <span class="lg"><i class="sw sw-cur"></i>Today</span>
      <span class="lg"><i class="sw sw-prior"></i>~3 months ago</span>
    </div>'''

def sector_bars(quotes):
    secs = sorted([q for q in quotes.values() if q.get("cat") == "sector"],
                  key=lambda q: q["pct"], reverse=True)
    if not secs:
        return '<p class="dim">Sector data unavailable.</p>'
    mx = max(abs(q["pct"]) for q in secs) or 1
    out = []
    for q in secs:
        p = q["pct"]
        cls = dircls(p)
        w = abs(p) / mx * 50
        left = 50 if p >= 0 else 50 - w
        out.append(f'''<div class="sbar-row">
          <div class="sbar-label">{esc(q['label'])}</div>
          <div class="sbar-track"><div class="sbar-zero"></div>
            <div class="sbar-fill {cls}" style="left:{left:.2f}%;width:{w:.2f}%"
                 title="{esc(q['label'])}: {p:+.2f}%"></div></div>
          <div class="sbar-val delta {cls}">{p:+.2f}%</div>
        </div>''')
    return f'<div class="sbars">{"".join(out)}</div>'

# ---------------------------------------------------------------- stylesheet
CSS = """
:root{
  color-scheme: light;
  --ground:#EDF0F4; --surface:#FFFFFF; --surface-2:#F5F7FA; --raise:#FBFCFD;
  --line:#D7DDE6; --line-soft:#E5EAF1;
  --ink:#0F141C; --ink-2:#454F5E; --ink-3:#6B7686;
  --accent:#8A6115; --accent-2:#B8862F; --accent-soft:#F2E6CC;
  --up:#0A7A3D; --down:#BE2A1D;
  --up-mark:#0CA34F; --down-mark:#D03B3B;
  --up-wash:rgba(12,163,79,.13); --down-wash:rgba(208,59,59,.13);
  --shadow:0 1px 2px rgba(15,20,28,.06), 0 4px 16px rgba(15,20,28,.05);
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    color-scheme: dark;
    --ground:#0E121A; --surface:#151B25; --surface-2:#1A212C; --raise:#1E2632;
    --line:#28313F; --line-soft:#212936;
    --ink:#E8EDF4; --ink-2:#A5B0C1; --ink-3:#77839A;
    --accent:#E3B160; --accent-2:#C99333; --accent-soft:#33291A;
    --up:#3FD98D; --down:#FF7B66;
    --up-mark:#2FC77D; --down-mark:#E86A56;
    --up-wash:rgba(47,199,125,.15); --down-wash:rgba(232,106,86,.15);
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.28);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --ground:#0E121A; --surface:#151B25; --surface-2:#1A212C; --raise:#1E2632;
  --line:#28313F; --line-soft:#212936;
  --ink:#E8EDF4; --ink-2:#A5B0C1; --ink-3:#77839A;
  --accent:#E3B160; --accent-2:#C99333; --accent-soft:#33291A;
  --up:#3FD98D; --down:#FF7B66;
  --up-mark:#2FC77D; --down-mark:#E86A56;
  --up-wash:rgba(47,199,125,.15); --down-wash:rgba(232,106,86,.15);
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.28);
}

*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.mono,.num,.tile-value,.delta,.axis,.pt-label{
  font-family:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 72px}

/* ---- masthead ---- */
.mast{border-bottom:1px solid var(--line);background:var(--surface);
  box-shadow:var(--shadow);margin-bottom:26px}
.mast-in{max-width:1180px;margin:0 auto;padding:22px 20px 0}
.kicker{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent);font-weight:700;margin:0 0 6px}
h1{margin:0;font-size:clamp(1.6rem,3.6vw,2.15rem);letter-spacing:-.022em;
  font-weight:760;text-wrap:balance;line-height:1.15}
.stamp{margin:8px 0 0;color:var(--ink-3);font-size:12.5px}
.stamp b{color:var(--ink-2);font-weight:600}

/* ---- ticker strip ---- */
.strip{display:flex;gap:0;overflow-x:auto;margin:18px -20px 0;padding:0 20px;
  border-top:1px solid var(--line-soft);scrollbar-width:none}
.strip::-webkit-scrollbar{display:none}
.strip-item{flex:0 0 auto;padding:11px 20px 11px 0;margin-right:20px;
  border-right:1px solid var(--line-soft);display:flex;gap:9px;align-items:baseline;
  white-space:nowrap}
.strip-item:last-child{border-right:0}
.strip-k{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
.strip-v{font-size:14px;font-weight:650;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}

/* ---- sections ---- */
section{margin-top:38px}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;
  gap:16px;padding-bottom:9px;border-bottom:1.5px solid var(--ink);margin-bottom:16px}
h2{margin:0;font-size:15px;letter-spacing:.1em;text-transform:uppercase;font-weight:720}
.sec-note{font-size:12.5px;color:var(--ink-3);text-align:right}

/* ---- tiles ---- */
.tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(176px,1fr))}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:4px;
  padding:14px 15px 13px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:7px}
.tile-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.tile-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-3);font-weight:670;white-space:nowrap}
.tile-note{font-size:10.5px;color:var(--ink-3);background:var(--surface-2);
  border:1px solid var(--line-soft);border-radius:2px;padding:1px 5px;white-space:nowrap}
.tile-value{font-size:26px;font-weight:640;letter-spacing:-.02em;line-height:1.05}
.tile-foot{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;min-height:28px}
.tile-sub{font-size:11.5px;text-wrap:balance;color:var(--ink-3);border-top:1px solid var(--line-soft);padding-top:7px}
.asof{font-family:ui-monospace,"SF Mono",Menlo,monospace;opacity:.75}

/* ---- deltas ---- */
.delta{font-size:13px;font-weight:640;white-space:nowrap;display:inline-flex;gap:4px;align-items:baseline}
.delta.up{color:var(--up)} .delta.down{color:var(--down)} .delta.flat{color:var(--ink-3)}
.arw{font-size:9px;line-height:1}

/* ---- sparklines ---- */
.spark{flex:0 0 auto;display:block}
.spark-empty{width:104px;height:28px}
.spark-line{fill:none;stroke-width:1.6;vector-effect:non-scaling-stroke}
.spark-fill{stroke:none}
.spark.up .spark-line{stroke:var(--up-mark)} .spark.up .spark-fill{fill:var(--up-wash)}
.spark.up .spark-dot{fill:var(--up-mark)}
.spark.down .spark-line{stroke:var(--down-mark)} .spark.down .spark-fill{fill:var(--down-wash)}
.spark.down .spark-dot{fill:var(--down-mark)}
.spark.flat .spark-line{stroke:var(--ink-3)} .spark.flat .spark-fill{fill:transparent}
.spark.flat .spark-dot{fill:var(--ink-3)}

/* ---- tables ---- */
.tbl-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);
  border-radius:4px;box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse;min-width:480px}
caption{text-align:left;font-size:12px;color:var(--ink-3);padding:11px 15px 0}
th,td{padding:9px 15px;text-align:left;border-bottom:1px solid var(--line-soft);font-size:14px}
thead th{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);
  font-weight:670;border-bottom:1px solid var(--line);background:var(--surface-2)}
tbody th{font-weight:550;color:var(--ink)}
tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--surface-2)}
.num{text-align:right;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}
.dim{color:var(--ink-3);font-size:12.5px}

/* ---- charts ---- */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:4px;
  padding:16px;box-shadow:var(--shadow)}
.chart-wrap{overflow-x:auto}
.curve{width:100%;height:auto;min-width:420px;display:block}
.grid{stroke:var(--line-soft);stroke-width:1}
.curve-cur{fill:none;stroke:var(--accent-2);stroke-width:2;stroke-linejoin:round}
.curve-prior{fill:none;stroke:var(--ink-3);stroke-width:1.6;stroke-dasharray:4 3;opacity:.8}
.dot-cur{fill:var(--accent-2);stroke:var(--surface);stroke-width:2}
.dot-prior{fill:var(--ink-3);opacity:.75}
.axis{fill:var(--ink-3);font-size:10.5px}
.pt-label{fill:var(--ink);font-size:11px;font-weight:640}
.legend{display:flex;gap:18px;margin-top:10px;font-size:12px;color:var(--ink-2);flex-wrap:wrap}
.lg{display:inline-flex;align-items:center;gap:7px}
.sw{width:16px;height:0;border-top-width:2.5px;border-top-style:solid;display:inline-block}
.sw-cur{border-top-color:var(--accent-2)}
.sw-prior{border-top-color:var(--ink-3);border-top-style:dashed}

/* ---- sector bars ---- */
.sbars{display:flex;flex-direction:column;gap:5px}
.sbar-row{display:grid;grid-template-columns:132px 1fr 66px;gap:11px;align-items:center}
.sbar-label{font-size:12.5px;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sbar-track{position:relative;height:17px;background:var(--surface-2);border-radius:2px}
.sbar-zero{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--line)}
.sbar-fill{position:absolute;top:2px;bottom:2px;border-radius:2px;min-width:2px}
.sbar-fill.up{background:var(--up-mark)} .sbar-fill.down{background:var(--down-mark)}
.sbar-val{font-size:12.5px;text-align:right}

/* ---- 10-year hero ---- */
.hero10{background:var(--surface);border:1px solid var(--line);border-radius:4px;
  padding:18px 20px 14px;box-shadow:var(--shadow);border-left:3px solid var(--accent)}
.hero10-top{display:flex;justify-content:space-between;align-items:flex-start;
  gap:24px;flex-wrap:wrap;margin-bottom:14px}
.hero10-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--ink-3);font-weight:700;margin-bottom:4px}
.hero10-value{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums;
  font-size:clamp(2.6rem,6vw,3.4rem);font-weight:640;letter-spacing:-.03em;line-height:1;
  margin-bottom:6px}
.hero10-value .pct{font-size:.45em;color:var(--ink-3);margin-left:2px}
.hero10-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));
  gap:10px 22px;flex:1 1 380px;max-width:560px}
.stat{display:flex;flex-direction:column;gap:2px;border-left:1px solid var(--line-soft);padding-left:10px}
.stat-k{font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);font-weight:660}
.stat-v{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums;
  font-size:13px;font-weight:620}
.hero10-foot{font-size:11px;color:var(--ink-3);margin-top:6px}
.hist{width:100%;height:auto;min-width:380px;display:block}
.hist-line{fill:none;stroke:var(--accent-2);stroke-width:2;stroke-linejoin:round}
.hist-fill{fill:var(--accent-2);opacity:.10;stroke:none}
.hist-dot{fill:var(--accent-2);stroke:var(--surface);stroke-width:2}

/* ---- watch list ---- */
.watch{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.watch li{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:10px 0;
  border-bottom:1px solid var(--line-soft);font-size:14px}
.watch li:last-child{border-bottom:0}
.watch .when{font-size:11.5px;color:var(--accent);font-weight:680;letter-spacing:.04em;
  text-transform:uppercase;padding-top:2px}
.watch .what{color:var(--ink-2)} .watch .what b{color:var(--ink);font-weight:620}

/* ---- footer ---- */
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px}
footer p{margin:0 0 6px;max-width:78ch}
.flag{color:var(--down);font-weight:600}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
a:focus-visible,tr:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:640px){
  .wrap,.mast-in{padding-left:14px;padding-right:14px}
  .strip{margin-left:-14px;margin-right:-14px;padding-left:14px;padding-right:14px}
  .tile-value{font-size:23px}
  .sbar-row{grid-template-columns:104px 1fr 58px;gap:8px}
  .watch li{grid-template-columns:1fr;gap:3px}
}
"""

# ---------------------------------------------------------------- page
def build(data, C):
    Q, F = data.get("quotes", {}), data.get("fred", {})
    def q(s): return Q.get(s)
    def f(s): return F.get(s)

    now_et = datetime.now(timezone.utc).astimezone(ET)
    gen = datetime.fromisoformat(data["generated_utc"]).astimezone(ET)

    # ---- ticker strip ----
    strip = []
    for sym, dec in ((".SPX", 2), (".VIX", 2), ("@CL.1", 2), ("@GC.1", 2)):
        d = q(sym)
        if d:
            strip.append(f'<div class="strip-item"><span class="strip-k">{esc(d["label"])}</span>'
                         f'<span class="strip-v">{fmt(d["price"],dec)}</span>'
                         f'<span class="delta {dircls(d["pct"])}">{d["pct"]:+.2f}%</span></div>')
    t10 = f("DGS10")
    if t10:
        strip.append(f'<div class="strip-item"><span class="strip-k">10Y</span>'
                     f'<span class="strip-v">{t10["value"]:.2f}%</span>'
                     f'<span class="delta {dircls(t10.get("chg"))}">'
                     f'{(t10.get("chg") or 0)*100:+.0f} bp</span></div>')

    # ---- hero tiles ----
    tiles = []
    sp = q(".SPX")
    if sp:
        sub = f"52wk {fmt(sp.get('wk52lo'),0)} – {fmt(sp.get('wk52hi'),0)}"
        tiles.append(hero_tile("S&P 500", fmt(sp["price"]),
                     sub, f"{sp['chg']:+,.2f}  ({sp['pct']:+.2f}%)", sp["pct"], sp.get("spark")))
    if t10:
        tiles.append(hero_tile("10Y", f"{t10['value']:.2f}%",
                     f"2s10s {f('T10Y2Y')['value']:+.2f}%" if f("T10Y2Y") else "US 10-year yield",
                     f"{(t10.get('chg') or 0)*100:+.0f} bp d/d", t10.get("chg"),
                     t10.get("series"), note=short_date(t10["date"])))
    ff = f("DFF")
    if ff:
        tiles.append(hero_tile("Fed Funds", f"{ff['value']:.2f}%",
                     C.get("fed_target", "Effective overnight rate"),
                     f"{(ff.get('chg') or 0)*100:+.0f} bp", ff.get("chg"),
                     ff.get("series"), note=short_date(ff["date"])))
    cpi = f("CPIAUCSL")
    if cpi and cpi.get("yoy") is not None:
        prev = cpi.get("yoy_prev")
        d = (cpi["yoy"] - prev) if prev is not None else None
        tiles.append(hero_tile("CPI", f"{cpi['yoy']:.1f}%",
                     f"Core {f('CPILFESL')['yoy']:.1f}% y/y" if (f('CPILFESL') and f('CPILFESL').get('yoy')) else "Headline, y/y",
                     f"{d:+.2f} pp vs prior" if d is not None else "y/y", d,
                     note=short_date(cpi["date"]), tone="flat"))
    un = f("UNRATE")
    if un:
        tiles.append(hero_tile("Unemployment", f"{un['value']:.1f}%",
                     f"Claims {f('ICSA')['value']/1000:,.0f}k weekly" if f("ICSA") else "U-3 rate",
                     f"{(un.get('chg') or 0):+.1f} pp", un.get("chg"),
                     un.get("series"), note=short_date(un["date"]), tone="flat"))
    vix = q(".VIX")
    if vix:
        tiles.append(hero_tile("VIX", fmt(vix["price"]),
                     "Implied 30-day S&P volatility",
                     f"{vix['chg']:+.2f}  ({vix['pct']:+.2f}%)", vix["pct"], vix.get("spark")))

    # ---- rates table ----
    rate_rows = []
    for sid in ("DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"):
        d = f(sid)
        if d:
            s = d.get("series") or []
            m1 = f"{(d['value']-s[-22])*100:+.0f} bp" if len(s) > 22 else "—"
            rate_rows.append(row(d["label"], f"{d['value']:.2f}%", delta_cell(d.get("chg"), bp=True), m1))
    spread_rows = []
    for sid, note in (("T10Y2Y", "10Y minus 2Y — the classic recession signal"),
                      ("T10Y3M", "10Y minus 3M — the Fed's preferred version"),
                      ("BAMLC0A0CM", "Investment-grade corporate risk premium"),
                      ("BAMLH0A0HYM2", "High-yield risk premium — risk appetite gauge"),
                      ("T10YIE", "Market-implied 10-year inflation"),
                      ("MORTGAGE30US", "30-year fixed mortgage average")):
        d = f(sid)
        if d:
            spread_rows.append(row(d["label"], f"{d['value']:.2f}%", delta_cell(d.get("chg"), bp=True),
                                   f'<span class="dim">{esc(note)}</span>'))

    # ---- market tables ----
    def qtable(cat):
        rows = []
        for s, d in Q.items():
            if d.get("cat") != cat: continue
            dec = d.get("dec", 2)
            extra = []
            if d.get("pct_1m") is not None: extra.append(f"1M {d['pct_1m']:+.1f}%")
            if d.get("pct_6m") is not None: extra.append(f"6M {d['pct_6m']:+.1f}%")
            # Trailing returns need Yahoo history, which is often unavailable. The
            # 52-week range always comes from the quote, so fall back to showing
            # where in that range the instrument is currently sitting.
            if not extra and d.get("wk52hi") and d.get("wk52lo"):
                lo, hi = d["wk52lo"], d["wk52hi"]
                extra.append(f"52wk {lo:,.{dec}f}–{hi:,.{dec}f}")
                if hi > lo:
                    extra.append(f"{(d['price']-lo)/(hi-lo)*100:.0f}% of range")
            rows.append(row(d["label"], fmt(d["price"], dec),
                            f'<span class="delta {dircls(d["pct"])}">'
                            f'<span class="arw" aria-hidden="true">{arrow(d["pct"])}</span>'
                            f'{d["pct"]:+.2f}%</span>',
                            '<span class="dim">' + " · ".join(extra) + '</span>'))
        return "".join(rows)

    def tbl(caption, head3, rows):
        return f'''<div class="tbl-wrap"><table>
        <caption>{esc(caption)}</caption>
        <thead><tr><th scope="col">Instrument</th><th scope="col" class="num">Level</th>
        <th scope="col" class="num">{esc(head3)}</th><th scope="col">Context</th></tr></thead>
        <tbody>{rows}</tbody></table></div>'''

    # ---- macro table ----
    macro_rows = []
    for sid, unit, note in (
        ("UNRATE", "%", "U-3 unemployment rate"),
        ("PAYEMS", "k", "Total nonfarm payrolls; change = jobs added"),
        ("ICSA", "k", "Weekly initial jobless claims"),
        ("CPIAUCSL", "yoy", "Headline CPI, year over year"),
        ("CPILFESL", "yoy", "Core CPI — ex food & energy"),
        ("PCEPILFE", "yoy", "Core PCE — the Fed's target measure"),
        ("A191RL1Q225SBEA", "%", "Real GDP growth, quarterly annualized"),
        ("UMCSENT", "idx", "U. Michigan consumer sentiment")):
        d = f(sid)
        if not d: continue
        if unit == "yoy" and d.get("yoy") is not None:
            val, dl = f"{d['yoy']:.1f}%", delta_cell(
                (d["yoy"] - d["yoy_prev"]) if d.get("yoy_prev") is not None else None,
                dec=2, suffix=" pp", tone="flat")
        elif unit == "k":
            if sid == "PAYEMS":            # thousands of persons -> show millions
                val = f"{d['value']/1000:,.1f}M"
                dl = delta_cell(d.get("chg"), dec=0, suffix="k", tone="flat")
            else:                          # ICSA: persons -> show thousands
                val = f"{d['value']/1000:,.0f}k"
                dl = delta_cell((d.get("chg") or 0)/1000 if d.get("chg") is not None else None,
                                dec=1, suffix="k", tone="flat")
        elif unit == "idx":
            val, dl = f"{d['value']:.1f}", delta_cell(d.get("chg"), dec=1, tone="flat")
        else:
            val, dl = f"{d['value']:.1f}%", delta_cell(d.get("chg"), dec=1, suffix=" pp", tone="flat")
        macro_rows.append(f'<tr><th scope="row">{esc(d["label"])}</th><td class="num">{val}</td>'
                          f'<td class="num">{dl}</td>'
                          f'<td class="dim">{esc(note)} · <span class="mono">{short_date(d["date"])}</span></td></tr>')

    # ---- on-deck calendar (terse fragments only) ----
    # Entries may carry an ISO "until" date; once past, they drop off by themselves
    # so an unattended deploy never shows a stale calendar.
    today_iso = now_et.strftime("%Y-%m-%d")
    upcoming = [w for w in C.get("watch", []) if w.get("until", "9999") >= today_iso]
    watch = "".join(f'<li><span class="when">{esc(w["when"])}</span>'
                    f'<span class="what">{w["what"]}</span></li>' for w in upcoming)

    stale = data.get("stale", [])
    stale_note = (f'<p class="flag">{len(stale)} series stale — showing last good value.</p>'
                  ) if stale else ""

    return f'''<title>Daily Market Brief</title>
<style>{CSS}</style>
<header class="mast"><div class="mast-in">
  <p class="kicker">Pre-Market Brief · Markets &amp; Macro</p>
  <h1>{esc(C.get("headline", "Where the market stands this morning"))}</h1>
  <p class="stamp">Data as of <b>{gen:%A, %B %-d, %Y · %-I:%M %p ET}</b> ·
     Live market levels from CNBC · macro series from the Federal Reserve (FRED)</p>
  <div class="strip">{''.join(strip)}</div>
</div></header>

<div class="wrap">
  <section aria-labelledby="head-h">
    <div class="sec-head"><h2 id="head-h">Headline Numbers</h2>
      <span class="sec-note">Quote these cold</span></div>
    <div class="tiles">{''.join(tiles)}</div>
  </section>

  <section aria-labelledby="rates-h">
    <div class="sec-head"><h2 id="rates-h">Treasuries</h2>
      <span class="sec-note">10-year first, then the rest of the curve</span></div>
    {ten_year_panel(F)}
    <div style="height:12px"></div>
    <div class="panel">{yield_curve_svg(F)}</div>
    <div style="height:12px"></div>
    {tbl("US Treasury yields — change shown in basis points", "1-Day", "".join(rate_rows))}
    <div style="height:12px"></div>
    {tbl("Spreads, credit and borrowing costs", "1-Day", "".join(spread_rows))}
  </section>

  <section aria-labelledby="eq-h">
    <div class="sec-head"><h2 id="eq-h">Equities</h2>
      <span class="sec-note">Index levels and sector leadership</span></div>
    {tbl("Major equity indices", "1-Day", qtable("equity"))}
    <div style="height:12px"></div>
    <div class="panel">
      <div style="font-size:12.5px;color:var(--ink-3);margin-bottom:12px">
        S&amp;P 500 sector performance, prior session (%)</div>
      {sector_bars(Q)}
    </div>
  </section>

  <section aria-labelledby="cm-h">
    <div class="sec-head"><h2 id="cm-h">Commodities, Currencies &amp; Crypto</h2>
      <span class="sec-note">Inflation and dollar transmission</span></div>
    {tbl("Commodities", "1-Day", qtable("cmdty"))}
    <div style="height:12px"></div>
    {tbl("Currencies and crypto", "1-Day", qtable("fx"))}
  </section>

  <section aria-labelledby="macro-h">
    <div class="sec-head"><h2 id="macro-h">Macro Scoreboard</h2>
      <span class="sec-note">Official releases · date shown is the reference period</span></div>
    <div class="tbl-wrap"><table>
      <caption>Latest official readings — change is versus the prior release. Arrows show direction only; these are not colour-coded good or bad.</caption>
      <thead><tr><th scope="col">Indicator</th><th scope="col" class="num">Latest</th>
      <th scope="col" class="num">Change</th><th scope="col">What it measures</th></tr></thead>
      <tbody>{''.join(macro_rows)}</tbody></table></div>
  </section>

  {f"""<section aria-labelledby="watch-h">
    <div class="sec-head"><h2 id="watch-h">On Deck</h2>
      <span class="sec-note">Releases and events that could move these numbers</span></div>
    <div class="panel"><ul class="watch">{watch}</ul></div>
  </section>""" if watch else ""}

  <footer>
    {stale_note}
    <p>Quotes may be delayed. Macro dates are reference periods, not release dates.</p>
    <p>Sources: CNBC · Federal Reserve Economic Data (FRED). Weekdays, 6:30&nbsp;AM ET.</p>
  </footer>
</div>'''

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    dpath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "market_data.json")
    opath = sys.argv[2] if len(sys.argv) > 2 else os.path.join(base, "brief.html")
    cpath = sys.argv[3] if len(sys.argv) > 3 else os.path.join(base, "commentary.json")
    with open(dpath) as fh:
        data = json.load(fh)
    C = {}
    if os.path.exists(cpath):
        try:
            with open(cpath) as fh: C = json.load(fh)
        except Exception as e:
            print(f"! commentary unreadable: {e}", file=sys.stderr)
    with open(opath, "w") as fh:
        fh.write(build(data, C))
    print(f"Wrote {opath} ({os.path.getsize(opath):,} bytes)")

if __name__ == "__main__":
    main()
