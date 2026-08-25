#!/usr/bin/env python3
"""Print a compact text digest of market_data.json for the morning agent to reason over."""
import json, sys, os

base = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "market_data.json")))
Q, F = d["quotes"], d["fred"]

def line(label, val, chg=None, extra=""):
    c = f"  {chg:+.2f}%" if chg is not None else ""
    print(f"  {label:<24} {val:>12}{c:>10}  {extra}")

print(f"DATA AS OF (UTC): {d['generated_utc']}")
if d.get("errors"): print(f"FAILED THIS RUN: {', '.join(d['errors'])}")
if d.get("stale"):  print(f"SERVED FROM CACHE (stale): {', '.join(d['stale'])}")

for cat, title in (("equity","EQUITY INDICES"),("sector","S&P SECTORS"),
                   ("cmdty","COMMODITIES"),("fx","FX & CRYPTO")):
    rows = [q for q in Q.values() if q.get("cat")==cat]
    if not rows: continue
    print(f"\n{title}")
    for q in sorted(rows, key=lambda x: x["pct"], reverse=True):
        ex = []
        if q.get("pct_1m") is not None: ex.append(f"1M {q['pct_1m']:+.1f}%")
        if q.get("pct_6m") is not None: ex.append(f"6M {q['pct_6m']:+.1f}%")
        if q.get("wk52hi"): ex.append(f"52wk {q['wk52lo']:,.0f}-{q['wk52hi']:,.0f}")
        if q.get("_stale"): ex.append("STALE")
        line(q["label"], f"{q['price']:,.2f}", q["pct"], " · ".join(ex))

print("\nRATES & SPREADS (level in %, chg in bp)")
for sid in ("DGS3MO","DGS2","DGS5","DGS10","DGS30","T10Y2Y","T10Y3M","DFF","SOFR",
            "T10YIE","BAMLC0A0CM","BAMLH0A0HYM2","MORTGAGE30US"):
    f = F.get(sid)
    if not f: continue
    s = f.get("series") or []
    ex = [f"as of {f['date']}"]
    if len(s) > 22: ex.append(f"1M {(f['value']-s[-22])*100:+.0f}bp")
    if len(s) > 64: ex.append(f"3M {(f['value']-s[-64])*100:+.0f}bp")
    if f.get("_stale"): ex.append("STALE")
    chg = f.get("chg")
    print(f"  {f['label']:<24} {f['value']:>11.2f}%  {f'{chg*100:+.0f}bp' if chg is not None else '':>9}  {' · '.join(ex)}")

print("\nMACRO")
for sid in ("UNRATE","PAYEMS","ICSA","CPIAUCSL","CPILFESL","PCEPILFE",
            "A191RL1Q225SBEA","UMCSENT"):
    f = F.get(sid)
    if not f: continue
    if f.get("yoy") is not None:
        v = f"{f['yoy']:.2f}% y/y"
        p = f" (prior {f['yoy_prev']:.2f}%)" if f.get("yoy_prev") is not None else ""
        m = f" mom {f['mom']:+.2f}%" if f.get("mom") is not None else ""
        print(f"  {f['label']:<24} {v:>16}{p}{m}  as of {f['date']}")
    else:
        c = f" ({f['chg']:+,.1f} vs prior)" if f.get("chg") is not None else ""
        print(f"  {f['label']:<24} {f['value']:>16,.2f}{c}  as of {f['date']}")
