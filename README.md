# Research Hub

Central financials research hub: a home page of tiles, one per research area, with config-driven dashboards behind them.

- `index.html` + `assets/hub.js` + `assets/hub.css`: static front end (hash router: `#/`, `#/macro`, `#/banks`, ...). Add `?r=1Y|5Y|10Y|Max` to set the lookback.
- `config/hub.json`: tile registry (title, icon, status `live` / `coming_soon`, description, planned views).
- `config/dashboards/<id>.json`: dashboard definition (FRED series + transform + format, sections and chart panels).
- `fetch_data.py`: pulls every series for every live dashboard from the FRED fredgraph CSV (keyless; ALFRED fallback) into `data/<id>.json`. If a pull fails, the last good copy is kept and flagged STALE. Nothing is ever made up.
- `build_export.py`: writes `research-hub.html`, one self-contained file with all data inlined.
- `refresh.sh`: fetch + export, logs to `logs/refresh.log` (use this for scheduled refreshes).
- `serve.sh [port]`: serves locally in the background (default 8077).

## Adding a dashboard
1. Create `config/dashboards/<id>.json` (copy `macro.json`). Transforms: `level`, `yoy`, `diff`, `div1000`. Formats: `pct1`, `pct2`, `pp2`, `k0`. Change units: `pp`, `bp`, `k`.
2. In `config/hub.json`, set that area's `status` to `live` and add `"dashboard": "config/dashboards/<id>.json"`.
3. Run `./refresh.sh`. No front-end code changes are needed for FRED-based dashboards.

## Publishing (GitHub Pages)
This folder is the git working copy of https://github.com/ehines12/research-hub, served at https://ehines12.github.io/research-hub/.
- `./publish.sh "message"`: pull any data commits from the Action, refresh, commit, push. Pages rebuilds in about 1-2 minutes.
- `.github/workflows/refresh-data.yml`: runs `fetch_data.py` on weekdays at 13:47, 16:07 and 21:17 UTC, and on demand (`gh workflow run refresh-data.yml`). It commits `data/*.json` only when something changed. `data/<id>.json` is rewritten only when FRED numbers change; `data/status.json` records each check time and series status.

## Embedded links
In `config/hub.json`, a link with `"embed": true` opens inside the hub at `#/<id>` in a full-height iframe, with an "Open in new tab" button. Only use this when the target site allows framing (no `X-Frame-Options: DENY/SAMEORIGIN` and no CSP `frame-ancestors` that excludes us). The FDIC QBP sends `X-Frame-Options: SAMEORIGIN`, so it stays an external link.
