#!/bin/bash
# Refresh market data and re-render the daily brief.
# Usage: ./run_brief.sh          (fetch + render)
#        ./run_brief.sh --render (render only, reuse cached data)
cd "$(dirname "$0")" || exit 1
if [ "$1" != "--render" ]; then
  echo "==> Fetching market data..."
  python3 fetch_data.py market_data.json || echo "!! fetch had errors; using cache where needed"
fi
echo "==> Rendering brief..."
python3 render.py market_data.json brief.html commentary.json
