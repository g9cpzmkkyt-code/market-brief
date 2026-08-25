#!/usr/bin/env python3
"""Generate commentary.json's headline deterministically from the data.

CI has no model available, so the headline is composed from the largest moves on
the board rather than written. Preserves `watch` and `fed_target` if already set.
"""
import json, os, sys

base = os.path.dirname(os.path.abspath(__file__))
dpath = os.path.join(base, "market_data.json")
cpath = os.path.join(base, "commentary.json")

d = json.load(open(dpath))
Q, F = d.get("quotes", {}), d.get("fred", {})
C = {}
if os.path.exists(cpath):
    try: C = json.load(open(cpath))
    except Exception: C = {}

def pct(sym):
    q = Q.get(sym)
    return q["pct"] if q else None

parts = []

# S&P always leads
if pct(".SPX") is not None:
    parts.append(f"S&P {pct('.SPX'):+.2f}%")

# biggest commodity move, if it actually moved
cmdty = [(s, q) for s, q in Q.items() if q.get("cat") == "cmdty" and q.get("pct") is not None]
if cmdty:
    s, q = max(cmdty, key=lambda kv: abs(kv[1]["pct"]))
    if abs(q["pct"]) >= 1.5:
        parts.append(f"{q['label']} {q['pct']:+.1f}%")

# 10-year, if it moved meaningfully
t10 = F.get("DGS10")
if t10 and t10.get("chg") is not None and abs(t10["chg"] * 100) >= 3:
    parts.append(f"10Y {t10['chg']*100:+.0f}bp")

# volatility spike
v = pct(".VIX")
if v is not None and abs(v) >= 6:
    parts.append(f"VIX {v:+.1f}%")

C["headline"] = ", ".join(parts[:4]) if parts else "Quiet tape"

# Fed target range brackets the effective rate, in 25bp steps
ff = F.get("DFF")
if ff:
    lo = int(ff["value"] * 4) / 4
    C["fed_target"] = f"Target range {lo:.2f}%–{lo+0.25:.2f}%"

C.setdefault("watch", [])
json.dump(C, open(cpath, "w"), indent=2)
print(f"headline: {C['headline']}")
