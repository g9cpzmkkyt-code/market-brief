# Daily Market Brief

Numbers-only pre-market macro + markets dashboard. No prose, no commentary —
levels, changes, and a calendar.

Runs on **GitHub Actions** every weekday at 6:30 AM ET and deploys to GitHub
Pages, so it updates whether or not any app is open on your machine.

## One-time setup

```bash
cd ~/market-brief
git branch -M main
git remote add origin https://github.com/<your-username>/market-brief.git
git push -u origin main
```

Then in the repo on github.com:

1. **Settings → Pages → Build and deployment → Source: GitHub Actions**
2. **Settings → Actions → General → Workflow permissions: Read and write**
3. **Actions tab → Daily Market Brief → Run workflow** to test it immediately.

Your dashboard is then at `https://<your-username>.github.io/market-brief/`.

Note: GitHub Pages on a free account is publicly readable. Everything here is
public market data — no personal information is on the page.

## Schedule

GitHub cron is UTC, so the workflow is scheduled at both 10:30 and 11:30 UTC and
a `gate` job drops whichever run isn't 6 AM in New York. That holds 6:30 AM ET
across daylight-saving changes.

## Run it by hand

```bash
cd ~/market-brief
./run_brief.sh            # fetch fresh data + render to brief.html
./run_brief.sh --render   # re-render from cached data
python3 summarize.py      # print the numbers as text
```

## The calendar

`commentary.json` holds the "On Deck" list. Each entry carries an `until` date
and disappears on its own once past, so an unattended deploy never shows a stale
release. Top it up every few weeks:

```json
{"when": "Wed Sep 16", "what": "FOMC decision — effective funds 3.63%", "until": "2026-09-16"}
```

The headline is generated from the data by `build_headline.py` — CI has no model
available, so it names the largest moves rather than writing a sentence.

## Files

| File | Role |
|---|---|
| `fetch_data.py` | Pulls all data → `market_data.json` |
| `summarize.py` | Compact text digest of the data, for reasoning over |
| `render.py` | `market_data.json` + `commentary.json` → the HTML page |
| `build_headline.py` | Composes the headline from the biggest moves |
| `.github/workflows/brief.yml` | The scheduled cloud build |
| `commentary.json` | Headline, Fed target range, and the On Deck calendar |
| `run_brief.sh` | fetch + render |

## Data sources (all keyless)

- **CNBC quote service** — real-time indices, commodities, FX, crypto, sector
  ETFs. One batched request for all 28 instruments. This is the primary source.
- **FRED** (St. Louis Fed) — Treasury curve, spreads, CPI/PCE, employment, GDP.
- **Yahoo Finance** — sparkline history only, and strictly best-effort.

## Things that will bite you if you change this

- **FRED tarpits browser User-Agents.** Requests with a `Mozilla/...` UA hang for
  ~18s and time out; a `curl/8.4.0` UA returns in 0.06s. Hence `UA_PLAIN` in
  `fetch_data.py`. Do not "normalize" the User-Agent across sources.
- **FRED also tarpits parallel connections.** Its series are fetched serially,
  which is faster than 4-way concurrency, not slower.
- **Yahoo rate-limits hard (HTTP 429)** and can stay limited for a long while.
  It is optional by design: `0/28 sparklines` is a normal log line, not a
  failure. Never make it a required source or add aggressive retries.
- **Several FRED series have gaps** (e.g. `CPILFESL` is missing 2025-10).
  Year-over-year is computed by *date lookup*, never a fixed `-12` offset —
  a positional offset silently compares against the wrong month and was
  producing a CPI figure ~0.25pp too high.
- **Stooq is unusable** — it now sits behind a JavaScript proof-of-work wall.
- Anything that fails is served from the previous run's cache and flagged
  `_stale`, so the page always renders.
