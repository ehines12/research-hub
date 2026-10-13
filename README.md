# Research Hub

Central financials research hub: a home page of tiles, one per research area, with config-driven dashboards behind them.

- `index.html` + `assets/hub.js` + `assets/hub.css`: static front end (hash router: `#/`, `#/macro`, `#/banks`, ...). Add `?r=1Y|5Y|10Y|Max` to set the lookback.
- `config/hub.json`: tile registry (title, icon, status `live` / `coming_soon`, description, planned views).
- `config/dashboards/<id>.json`: dashboard definition (FRED series + transform + format, sections and chart panels).
- `fetch_data.py`: pulls every series (series with `"source": "gdpnow"` come from the Atlanta Fed GDPNow tracking workbook, GDPTrackingModelDataAndForecasts.xlsx; needs `openpyxl`) for every live dashboard from the FRED fredgraph CSV (keyless; ALFRED fallback) into `data/<id>.json`. If a pull fails, the last good copy is kept and flagged STALE. Nothing is ever made up.
- `build_export.py`: writes `research-hub.html`, one self-contained file with all data inlined.
- `refresh.sh`: fetch + export, logs to `logs/refresh.log` (use this for scheduled refreshes).
- `serve.sh [port]`: serves locally in the background (default 8077).

## Prediction Markets (#/predictions)

`predictions.py` (called by `fetch_data.py` for configs with `"kind": "predictions"`) picks the top 12 most liquid macro / markets / geopolitical markets across Kalshi (public trade API v2) and Polymarket (Gamma + CLOB), recomputed every run: category/tag candidates, keyword allow-groups plus a deny-list, live outcomes only, ranked by 7-day volume (open interest tiebreak), with the same question on both venues merged. If either venue fails, the last good list is kept and flagged stale. Odds-only Action runs at 9:52 AM, 12:52 PM and 2:52 PM CT on weekdays, in addition to the 3 full runs.

## H.8 / H.6 Quarterly Data

H.8 uses domestically chartered commercial banks only (domestic total / large / small, FRED ...DCBW / ...LCBW / ...SCBW; large-bank C&I = domestic − small since FRED has no large C&I weekly series). Quarterly groups and growth5y rows carry a `bank` tag (D/L/S) and the page shows one group at a time via a shared Banks toggle; downloads include all three. `"quarterly"` in `config/dashboards/h8.json` drives the Quarterly Data table on #/h8, computed in `fetch_data.py` (`calc.quarter_averages`) from the series already pulled: quarter-average levels ($bn) of the weekly H.8 / monthly H.6 data, YoY vs the same quarter a year earlier, and compounded LQA ((avg_q/avg_q-1)^4 - 1). Partial quarters are flagged QTD per cell. Each data change also writes `data/h8-quarterly.csv` and `data/h8-quarterly.xlsx` (openpyxl), committed by the Action.

## Macro: non-FRED sources

Set per series with `"source"` in `config/dashboards/macro.json` (all keyless, fetched with curl):
- `gdpnow`: Atlanta Fed GDPNow tracking workbook (daily nowcast history).
- `clevnow`: Cleveland Fed Inflation Nowcasting chart JSON (`/-/media/files/webcharts/inflationnowcasting/nowcast_{month,quarter,year}.json`), the files the public page itself loads. One obs per target month/quarter = latest nowcast (final pre-release value for past targets); `obs_meta` carries the target, as-of date, m/m and pending flag. `"mode": "actual"` gives the released print. `nowcast_table` in a section renders every target still being nowcast.
- `tsa` (fetcher kept, NOT used: tsa.gov returns HTTP 403 to GitHub Actions runners, so it cannot refresh on schedule): TSA checkpoint travel numbers HTML table (current year plus 3 prior year pages); `avg7` = trailing 7-day average, `yoy` = vs the same 7 weekdays 364 days earlier.
- `dts`: Treasury Fiscal Data DTS API, deposits 'Taxes - Withheld Individual/FICA' (since 2023-02); `sum20` = rolling N-business-day sum (`window`, default 20), `yoy` = vs the window ending on the same date a year earlier.
A section's `"kpis"` list puts those KPI cards inside the section (and keeps them out of the top grid).

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

## H.8 / H.6 dashboard (#/h8)
`config/dashboards/h8.json`: Fed H.8 weekly bank balance sheet (deposits, loans by type, large/small domestic banks, deposit mix, securities, cash, total assets, borrowings) and H.6 monthly deposit mix / retail MMFs, all via FRED.
Moved from the Financials Dashboard on 2026-10-09 (rollback there: tag `pre-h8-move`). Derived series (`derived`), KPI tiles (`kpis`) and the summary table (`summary`) use `calc.py`, which uses the same formulas as the Financials Dashboard: YoY with on-or-before lookback, shares, contribution to YoY, H.6 savings+OCD -> MDLM splice, and 1W/1M/3M/1Y changes.
H.8 is released Fridays around 4:15 PM ET; the 21:17 UTC (4:17 PM CDT / 3:17 PM CST) weekday run is the first to catch it in CDT. In CST it falls just after the release.

## Geopolitics & Global Risk (`config/dashboards/geo.json`)

- **GPR** (Caldara-Iacoviello): daily (`data_gpr_daily_recent.xls`: GPRD, GPRD_ACT, GPRD_THREAT) and monthly (`data_gpr_export.xls`: GPR, GPRT, GPRA) from matteoiacoviello.com; source `gpr`, needs `xlrd`.
- **TPU** (Caldara et al.): `tpu_web_latest.xlsx`, sheets TPU_DAILY / TPU_MONTHLY; source `tpu`.
- **EPU** via FRED: USEPUINDXD, USEPUINDXM, GEPUCURRENT (global), EPUTRADE (trade-policy category).
- Cards (`stats: "risk"`): latest, 30-day (daily) / 3-month (monthly) average vs. trailing 1Y average, percentile of that average vs. full history.
- **IMF PortWatch** chokepoints: public ArcGIS `Daily_Chokepoints_Data` feature service (paged, 1000 rows/call); source `portwatch`. 7-day averages (`ma7`), last-year overlay (`ma7_ly`, +364 days); cards (`stats: "chokepoint"`) vs same dates last year and vs 2019-2022 same-date average. ~1 week publication lag.

## Treasury auctions (Macro, `auctions` block)

Fiscal Data `auctions_query` (notes/bonds incl. TIPS and FRNs) + TreasuryDirect `TA_WS/securities/upcoming`. Each auction is compared with the prior 6 of the same tenor (reopenings under original tenor) and flagged weak/strong on bid-to-cover (±0.10) and dealer takedown (±3 pp). No tails: when-issued yields are not freely available.
