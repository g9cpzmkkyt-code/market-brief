#!/usr/bin/env python3
"""Fetch market + macro data for the daily brief. No API keys required.

Sources
  CNBC quote API  - real-time levels for indices, commodities, FX, crypto, sector
                    ETFs. One batched request for everything. Primary.
  FRED CSV        - Treasury yields, spreads, CPI/PCE, employment, GDP.
  Yahoo Finance   - best-effort daily history for sparklines only. Yahoo rate-limits
                    aggressively; if it refuses, the brief simply renders without
                    sparklines rather than failing.

Designed to run unattended: every source degrades independently and the last good
value is reused from cache, so a partial outage never produces an empty brief.
"""

import json, sys, os, csv, io, time, random, threading
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

# CNBC and Yahoo expect a browser UA. FRED's Akamai edge does the opposite: it
# tarpits browser UAs from non-browser clients (18s timeouts) but serves a
# curl-style UA instantly. So the User-Agent is per-source, not global.
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_PLAIN = "curl/8.4.0"

def log(m): print(m, file=sys.stderr, flush=True)

_lock = threading.Lock(); _last = [0.0]; MIN_GAP = 0.25
def _pace():
    with _lock:
        w = MIN_GAP - (time.time() - _last[0])
        if w > 0: time.sleep(w)
        _last[0] = time.time()

def get(url, tries=3, timeout=35, quiet=False, ua=UA_BROWSER):
    for i in range(tries):
        _pace()
        try:
            hdrs = {"User-Agent": ua}
            if ua is UA_BROWSER:
                hdrs["Accept"] = "text/csv,application/json,*/*"
                hdrs["Accept-Language"] = "en-US,en;q=0.9"
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                if quiet: return None          # rate-limited optional source: give up fast
                if i < tries - 1:
                    time.sleep((2.5 ** i) + random.uniform(0, 1)); continue
            if i == tries - 1 and not quiet: log(f"  ! HTTP {e.code}  {url[:64]}")
        except Exception as e:
            if i == tries - 1:
                if not quiet: log(f"  ! {e}  {url[:64]}")
                return None
            time.sleep(1.2 * (i + 1))
    return None

def num(s):
    """CNBC returns pre-formatted strings like '7,671.18' or '+0.24%'."""
    if s in (None, "", "-", "UNCH"): return None
    try: return float(str(s).replace(",", "").replace("%", "").replace("+", "").strip())
    except ValueError: return None

# ---------------------------------------------------------------- instruments
# cnbc symbol -> (label, category, yahoo symbol for sparkline history, decimals)
INSTRUMENTS = [
    (".SPX",    "S&P 500",            "equity", "^GSPC",    2),
    (".IXIC",   "Nasdaq Composite",   "equity", "^IXIC",    2),
    (".DJI",    "Dow Jones",          "equity", "^DJI",     2),
    (".RUT",    "Russell 2000",       "equity", "^RUT",     2),
    (".VIX",    "VIX",                "equity", "^VIX",     2),
    ("@CL.1",   "WTI Crude",          "cmdty",  "CL=F",     2),
    ("@LCO.1",  "Brent Crude",        "cmdty",  "BZ=F",     2),
    ("@NG.1",   "Natural Gas",        "cmdty",  "NG=F",     3),
    ("@GC.1",   "Gold",               "cmdty",  "GC=F",     2),
    ("@SI.1",   "Silver",             "cmdty",  "SI=F",     3),
    ("@HG.1",   "Copper",             "cmdty",  "HG=F",     4),
    ("@W.1",    "Wheat",              "cmdty",  "ZW=F",     2),
    ("@C.1",    "Corn",               "cmdty",  "ZC=F",     2),
    (".DXY",    "US Dollar Index",    "fx",     "DX-Y.NYB", 3),
    ("EUR=",    "EUR/USD",            "fx",     "EURUSD=X", 4),
    ("JPY=",    "USD/JPY",            "fx",     "JPY=X",    2),
    ("BTC.CM=", "Bitcoin",            "fx",     "BTC-USD",  0),
    ("XLK",     "Technology",         "sector", "XLK",      2),
    ("XLF",     "Financials",         "sector", "XLF",      2),
    ("XLE",     "Energy",             "sector", "XLE",      2),
    ("XLV",     "Health Care",        "sector", "XLV",      2),
    ("XLI",     "Industrials",        "sector", "XLI",      2),
    ("XLY",     "Cons Discretionary", "sector", "XLY",      2),
    ("XLP",     "Cons Staples",       "sector", "XLP",      2),
    ("XLU",     "Utilities",          "sector", "XLU",      2),
    ("XLB",     "Materials",          "sector", "XLB",      2),
    ("XLRE",    "Real Estate",        "sector", "XLRE",     2),
    ("XLC",     "Communication Svcs", "sector", "XLC",      2),
]
META = {c: (lab, cat, y, d) for c, lab, cat, y, d in INSTRUMENTS}

def fetch_cnbc():
    """One batched request for every instrument."""
    out, status = {}, None
    syms = "|".join(c for c, *_ in INSTRUMENTS)
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
           f"?symbols={urllib.parse.quote(syms, safe='|@.=')}"
           "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    raw = get(url, tries=3)
    if not raw:
        return out, status
    try:
        rows = json.loads(raw)["FormattedQuoteResult"]["FormattedQuote"]
    except Exception as e:
        log(f"  ! CNBC parse: {e}")
        return out, status
    for r in rows:
        sym = r.get("symbol")
        if sym not in META: continue
        px, prev = num(r.get("last")), num(r.get("previous_day_closing"))
        if px is None or not prev: continue
        label, cat, ysym, dec = META[sym]
        status = status or r.get("curmktstatus")
        out[sym] = {
            "symbol": sym, "label": label, "cat": cat, "dec": dec, "yahoo": ysym,
            "price": px, "prev": prev, "chg": px - prev,
            "pct": (px - prev) / prev * 100,
            "open": num(r.get("open")), "high": num(r.get("high")), "low": num(r.get("low")),
            "wk52hi": num(r.get("yrhiprice")), "wk52lo": num(r.get("yrloprice")),
            "asof": r.get("last_timedate"), "mktstatus": r.get("curmktstatus"),
        }
    return out, status

def fetch_spark(ysym):
    """Best-effort daily closes from Yahoo for the sparkline. Silent on failure."""
    raw = get(f"https://query1.finance.yahoo.com/v8/finance/chart/"
              f"{urllib.parse.quote(ysym)}?range=6mo&interval=1d", tries=1, quiet=True)
    if not raw: return None
    try:
        res = json.loads(raw)["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        return closes[-90:] or None
    except Exception:
        return None

# ---------------------------------------------------------------- FRED
FRED = {
    "DGS3MO": "3-Month Treasury", "DGS2": "2-Year Treasury", "DGS5": "5-Year Treasury",
    "DGS10": "10-Year Treasury", "DGS30": "30-Year Treasury",
    "T10Y2Y": "2s10s Spread", "T10Y3M": "3m10y Spread",
    "DFF": "Fed Funds (Effective)", "SOFR": "SOFR",
    "T10YIE": "10-Year Breakeven", "MORTGAGE30US": "30-Year Mortgage",
    "BAMLH0A0HYM2": "High-Yield OAS", "BAMLC0A0CM": "Investment-Grade OAS",
    "UNRATE": "Unemployment Rate", "CPIAUCSL": "CPI", "CPILFESL": "Core CPI",
    "PCEPILFE": "Core PCE", "ICSA": "Initial Jobless Claims",
    "PAYEMS": "Nonfarm Payrolls", "A191RL1Q225SBEA": "Real GDP QoQ SAAR",
    "UMCSENT": "Consumer Sentiment",
}
YOY_SERIES = {"CPIAUCSL", "CPILFESL", "PCEPILFE"}

def fred(sid):
    cosd = (datetime.now() - timedelta(days=1300)).strftime("%Y-%m-%d")
    raw = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={cosd}",
              tries=3, timeout=20, ua=UA_PLAIN)
    if not raw: return None
    pts = []
    for r in csv.reader(io.StringIO(raw)):
        if len(r) < 2: continue
        try: pts.append((r[0], float(r[1])))
        except ValueError: continue      # FRED writes "." or "" for missing obs
    if not pts: return None
    d, v = pts[-1]
    out = {"date": d, "value": v, "series": [p[1] for p in pts[-180:]], "label": FRED[sid]}
    if len(pts) > 1:
        out["prev"] = pts[-2][1]; out["chg"] = v - pts[-2][1]

    if sid in YOY_SERIES:
        # Look the year-ago observation up BY DATE. Several FRED series have gaps
        # (CPILFESL is missing 2025-10), so a fixed -12 positional offset silently
        # compares against the wrong month.
        by_month = {}
        for ds, val in pts:
            y, m, _ = ds.split("-")
            by_month[(int(y), int(m))] = val

        def yoy_at(ds):
            y, m, _ = ds.split("-")
            base = by_month.get((int(y) - 1, int(m)))
            cur = by_month.get((int(y), int(m)))
            if base and cur is not None:
                return (cur - base) / base * 100
            return None

        def prev_month(ds):
            y, m, _ = ds.split("-")
            y, m = int(y), int(m)
            return f"{y-1:04d}-12-01" if m == 1 else f"{y:04d}-{m-1:02d}-01"

        out["yoy"] = yoy_at(d)
        out["yoy_prev"] = yoy_at(prev_month(d))
        pm = prev_month(d)
        y, m, _ = pm.split("-")
        pv = by_month.get((int(y), int(m)))
        if pv:
            out["mom"] = (v - pv) / pv * 100
    return out

# ---------------------------------------------------------------- main
def main():
    outpath = sys.argv[1] if len(sys.argv) > 1 else "market_data.json"
    data = {"generated_utc": datetime.now(timezone.utc).isoformat(),
            "quotes": {}, "fred": {}, "errors": [], "stale": [], "market_status": None}

    log("Quotes (CNBC, batched)...")
    quotes, status = fetch_cnbc()
    data["quotes"], data["market_status"] = quotes, status
    missing = [c for c, *_ in INSTRUMENTS if c not in quotes]
    data["errors"] += [f"quote:{c}" for c in missing]
    log(f"  {len(quotes)}/{len(INSTRUMENTS)} quotes  (market: {status})")

    log("Macro (FRED)...")
    for sid in FRED:                       # serial: FRED tarpits parallel connections
        f = fred(sid)
        if f: data["fred"][sid] = f
        else: data["errors"].append(f"fred:{sid}")
    log(f"  {len(data['fred'])}/{len(FRED)} series")

    log("Sparkline history (Yahoo, best effort)...")
    got = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        for sym, s in ex.map(lambda kv: (kv[0], fetch_spark(kv[1]["yahoo"])), list(quotes.items())):
            if s:
                quotes[sym]["spark"] = s; got += 1
                px = quotes[sym]["price"]
                if len(s) > 21: quotes[sym]["pct_1m"] = (px - s[-22]) / s[-22] * 100
                if len(s) > 63: quotes[sym]["pct_3m"] = (px - s[-64]) / s[-64] * 100
                quotes[sym]["pct_6m"] = (px - s[0]) / s[0] * 100
    log(f"  {got}/{len(quotes)} sparklines" + ("  (Yahoo throttled - brief renders without them)"
                                               if got == 0 else ""))

    # ---- reuse last good values for anything that failed ----
    if os.path.exists(outpath):
        try:
            old = json.load(open(outpath))
            for key in ("quotes", "fred"):
                for k, v in old.get(key, {}).items():
                    if k not in data[key]:
                        v["_stale"] = True; data[key][k] = v; data["stale"].append(f"{key}:{k}")
                    elif key == "quotes" and "spark" not in data[key][k] and "spark" in v:
                        data[key][k]["spark"] = v["spark"]      # keep old sparkline shape
        except Exception as e:
            log(f"  ! cache reuse failed: {e}")

    json.dump(data, open(outpath, "w"), indent=1)
    log(f"\nWrote {outpath}: {len(data['quotes'])} quotes, {len(data['fred'])} series, "
        f"{len(data['errors'])} failed, {len(data['stale'])} from cache")
    return 0 if (data["quotes"] and data["fred"]) else 1

if __name__ == "__main__":
    sys.exit(main())
