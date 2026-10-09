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
