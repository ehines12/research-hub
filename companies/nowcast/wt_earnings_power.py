"""WT earnings power: pull WisdomTree IR daily AUM workbook, build weekly series, compute
annualized earnings power at current AUM. Warn-only: never raises (exit 0) so weekday refresh
is not failed by it.

Sources (keyless):
  https://www.wisdomtree.com/-/media/us-media-files/xls/irwebsite_aum.xlsx
  https://www.wisdomtree.com/-/media/us-media-files/xls/irwebsite_inflows.xlsx
  Q3'26 8-K Ex. 99.1 assumptions verified against the release.
"""
import json, sys, datetime as dt, pathlib, traceback, io, tempfile
from urllib.request import Request, urlopen

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "wt_earnings_power.json"
WARN = []

AUM_URL = "https://www.wisdomtree.com/-/media/us-media-files/xls/irwebsite_aum.xlsx"
INFLOWS_URL = "https://www.wisdomtree.com/-/media/us-media-files/xls/irwebsite_inflows.xlsx"

# Verified from WT Q3'26 earnings release (8-K Ex. 99.1 filed 2026-10-30):
# avg AUM $170.5bn, adj op rev $179.375M, adj op income $77.343M, adj pretax $65.679M,
# adj tax rate 24.7%, diluted shares 156.179M. Revenue yield = 179.375*4/170.5 = 0.420821%.
# Non-op annual = (65.679 - 77.343) * 4 = -$46.656M.
BASE = {
    "label": "Q3 2026 reported base (8-K Ex. 99.1, filed 2026-10-30)",
    "quarter": "Q3 2026",
    "period_end": "2026-09-30",
    "avg_aum_bn": 170.5,
    "end_aum_bn": 171.0,          # company total incl. private
    "etp_end_aum_bn": 168.930,    # IR spreadsheet Total at 2026-09-30
    "private_end_aum_bn": 2.055,  # Ceres private, as reported at Q3'26
    "rev_q_m": 179.375,
    "adj_op_q_m": 77.343,
    "adj_pretax_q_m": 65.679,
    "rev_yield": 179.375 * 4 / (170.5 * 1000),  # ~0.00420821 (rev $M / AUM $M)
    "tax_rate": 0.247,
    "diluted_shares_m": 156.179,
    "nonop_annual_m": (65.679 - 77.343) * 4,  # -46.656
    "incr_op_margin_default": 0.50,
    "src": "https://www.sec.gov/Archives/edgar/data/880631/000121465926013478/ex99_1.htm",
}

# Convertible dilution context from WT converts analysis (make-whole max vs normal rates).
# Shares are approximate; panel labels them as scenarios, not guidance.
CONVERT = {
    "reported_diluted_m": 156.179,
    "normal_convert_add_m": 52.8,   # approx at normal conversion rates
    "max_makewhole_add_m": 80.7,    # approx at make-whole max rates + perf RSUs at 200%
    "note": "Convertible share adds are approximate from the convertible notes' conversion rates (normal vs make-whole maximum). Not a forecast of settlement method; WT's notes generally settle principal in cash with net shares for the conversion value.",
}

CATS = [
    "U.S. Equity", "Commodity & Currency", "International Developed Market Equity",
    "Fixed Income", "Emerging Market Equity", "Alternatives", "Leveraged & Inverse",
    "Cryptocurrency",
]

def warn(m):
    WARN.append(m); print("::warning::wt_earnings_power: " + m)

def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (research-hub; +https://ehines12.github.io/research-hub/)"})
    with urlopen(req, timeout=120) as r:
        return r.read()

def parse_daily_eop(data):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb["Daily_EOP"]
    rows = list(ws.iter_rows(min_row=1, max_row=40, values_only=True))
    # dates in row 3 (index 2), starting where values look like dates/strings YYYY-MM-DD
    header = rows[2]
    dates, cols = [], []
    for i, v in enumerate(header):
        if v is None: continue
        if hasattr(v, "date"):
            d = v.date().isoformat() if hasattr(v, "date") else v.isoformat()[:10]
            dates.append(d); cols.append(i)
        elif isinstance(v, str) and len(v) >= 10 and v[0:4].isdigit():
            dates.append(v[:10]); cols.append(i)
    # map labels
    label_row = {}
    for r_i, row in enumerate(rows):
        lab = row[0]
        if lab: label_row[str(lab).strip()] = r_i
    def series(label):
        r_i = label_row.get(label)
        if r_i is None: return {}
        row = rows[r_i]
        out = {}
        for d, c in zip(dates, cols):
            v = row[c]
            if v is not None:
                try: out[d] = float(v)
                except (TypeError, ValueError): pass
        return out
    total = series("Total:")
    # First Total: is division total (row 7); category Total is later — openpyxl read used first 40 rows
    # Re-read carefully: division Total is first occurrence in rows 0-7
    div_total = {}
    for r_i, row in enumerate(rows[:8]):
        if row[0] and str(row[0]).strip() == "Total:":
            for d, c in zip(dates, cols):
                v = row[c]
                if v is not None:
                    try: div_total[d] = float(v)
                    except (TypeError, ValueError): pass
            break
    cats = {}
    for cat in CATS:
        s = series(cat)
        if s: cats[cat] = s
    us = series("WT-US"); eu = series("WT-Europe"); oc = series("WT-Onchain")
    wb.close()
    return {"dates": sorted(div_total), "total": div_total, "us": us, "europe": eu, "onchain": oc, "categories": cats}

def parse_monthly_eop(data):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb["Monthly_EOP"]
    rows = list(ws.iter_rows(min_row=1, max_row=20, values_only=True))
    header = rows[2]
    months, cols = [], []
    for i, v in enumerate(header):
        if v and v != "Division" and isinstance(v, str) and len(v) >= 6:
            months.append(v); cols.append(i)
    total_row = None
    for row in rows[:8]:
        if row[0] and str(row[0]).strip() == "Total:":
            total_row = row; break
    out = []
    if total_row:
        for m, c in zip(months, cols):
            v = total_row[c]
            if v is None: continue
            # "2026 Oct" -> month-end approx
            try:
                y = int(m[:4]); mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].index(m[5:8]) + 1
                # month-end day
                if mon == 12: end = dt.date(y, 12, 31)
                else: end = dt.date(y, mon + 1, 1) - dt.timedelta(days=1)
                out.append({"month": m, "end": end.isoformat(), "aum_m": float(v), "aum_bn": round(float(v) / 1000, 3)})
            except Exception:
                continue
    wb.close()
    return out

def week_ends(daily_total):
    """Last available observation in each ISO week, oldest first."""
    items = sorted((d, v) for d, v in daily_total.items())
    by_week = {}
    for d, v in items:
        day = dt.date.fromisoformat(d)
        key = day.isocalendar()[:2]  # year, week
        by_week[key] = (d, v)  # keep last in week (dates ascending)
    return [{"date": d, "aum_m": v, "aum_bn": round(v / 1000, 3)} for d, v in (by_week[k] for k in sorted(by_week))]

def chg(cur, prev):
    if cur is None or prev is None or not prev: return None
    return round((cur / prev - 1) * 100, 2)

def earnings_power(aum_bn, yield_, incr_m, tax, shares_m, nonop_m, base=BASE):
    base_rev = base["rev_q_m"] * 4
    base_op = base["adj_op_q_m"] * 4
    rev = aum_bn * 1000 * yield_  # AUM $M × yield fraction → revenue $M
    d_rev = rev - base_rev
    op = base_op + incr_m * d_rev
    pretax = op + nonop_m
    ni = pretax * (1 - tax)
    eps = ni / shares_m if shares_m else None
    return {
        "aum_bn": round(aum_bn, 3),
        "rev_annual_m": round(rev, 1),
        "op_income_annual_m": round(op, 1),
        "op_margin": round(op / rev * 100, 1) if rev else None,
        "pretax_annual_m": round(pretax, 1),
        "ni_annual_m": round(ni, 1),
        "eps": round(eps, 2) if eps is not None else None,
        "vs_base_rev_m": round(d_rev, 1),
    }

def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    try:
        blob = fetch(AUM_URL)
    except Exception as e:
        warn(f"AUM workbook fetch failed ({e}); keeping previous"); 
        if old: old["warnings"] = WARN; OUT.write_text(json.dumps(old, indent=1)); return
        raise
    try:
        daily = parse_daily_eop(blob)
        monthly = parse_monthly_eop(blob)
    except Exception as e:
        warn(f"AUM workbook parse failed ({e}); keeping previous")
        if old: old["warnings"] = WARN; OUT.write_text(json.dumps(old, indent=1)); return
        raise

    if not daily["dates"]:
        warn("no daily AUM dates parsed; keeping previous")
        if old: old["warnings"] = WARN; OUT.write_text(json.dumps(old, indent=1)); return

    asof = daily["dates"][-1]
    total_m = daily["total"][asof]
    private = BASE["private_end_aum_bn"]
    etp_bn = total_m / 1000
    company_bn = etp_bn + private

    weeks = week_ends(daily["total"])
    # changes vs prior observations
    def aum_on(date):
        return daily["total"].get(date)
    # find date N trading days back
    def back(n):
        if len(daily["dates"]) <= n: return None
        return daily["dates"][-(n + 1)]
    d1 = back(1); d5 = back(5); d20 = back(20)
    # quarter / year starts
    asof_d = dt.date.fromisoformat(asof)
    q_start = dt.date(asof_d.year, ((asof_d.month - 1) // 3) * 3 + 1, 1).isoformat()
    y_start = f"{asof_d.year}-01-01"
    # nearest available on/before
    def on_or_before(target):
        cand = [d for d in daily["dates"] if d <= target]
        return cand[-1] if cand else None
    dq = on_or_before(q_start); dy = on_or_before(y_start)

    changes = {
        "d1": {"from": d1, "pct": chg(total_m, aum_on(d1)) if d1 else None},
        "d5_approx_1w": {"from": d5, "pct": chg(total_m, aum_on(d5)) if d5 else None},
        "d20_approx_4w": {"from": d20, "pct": chg(total_m, aum_on(d20)) if d20 else None},
        "qtd": {"from": dq, "pct": chg(total_m, aum_on(dq)) if dq else None},
        "ytd": {"from": dy, "pct": chg(total_m, aum_on(dy)) if dy else None},
    }
    # week-over-week from week series
    if len(weeks) >= 2:
        changes["wow"] = {"from": weeks[-2]["date"], "pct": chg(weeks[-1]["aum_m"], weeks[-2]["aum_m"])}
    if len(weeks) >= 5:
        changes["w4"] = {"from": weeks[-5]["date"], "pct": chg(weeks[-1]["aum_m"], weeks[-5]["aum_m"])}

    cats_latest = {}
    for k, s in daily["categories"].items():
        if asof in s: cats_latest[k] = round(s[asof] / 1000, 3)

    div_latest = {
        "us": round(daily["us"].get(asof, 0) / 1000, 3) if daily["us"] else None,
        "europe": round(daily["europe"].get(asof, 0) / 1000, 3) if daily["europe"] else None,
        "onchain": round(daily["onchain"].get(asof, 0) / 1000, 3) if daily["onchain"] else None,
    }

    # stale if asof older than 7 calendar days
    stale_days = (dt.date.today() - asof_d).days
    stale = stale_days > 5

    yld = BASE["rev_yield"]
    incr = BASE["incr_op_margin_default"]
    tax = BASE["tax_rate"]
    sh = BASE["diluted_shares_m"]
    nonop = BASE["nonop_annual_m"]

    base_power = earnings_power(BASE["avg_aum_bn"], yld, incr, tax, sh, nonop)
    # at Q3 avg AUM with incr margin, delta_rev=0 so this is pure run-rate
    cur_etp = earnings_power(etp_bn, yld, incr, tax, sh, nonop)
    cur_co = earnings_power(company_bn, yld, incr, tax, sh, nonop)
    # scenarios
    scenarios = []
    for label, aum, shares, incr_m in [
        ("Current ETP/Onchain AUM (IR sheet)", etp_bn, sh, incr),
        ("Current + last-reported private (Ceres)", company_bn, sh, incr),
        ("Company AUM, +10% AUM", company_bn * 1.10, sh, incr),
        ("Company AUM, −10% AUM", company_bn * 0.90, sh, incr),
        ("Company AUM, normal convert dilution", company_bn, sh + CONVERT["normal_convert_add_m"], incr),
        ("Company AUM, max make-whole convert dilution", company_bn, sh + CONVERT["max_makewhole_add_m"], incr),
        ("Company AUM, 40% incremental margin", company_bn, sh, 0.40),
        ("Company AUM, 60% incremental margin", company_bn, sh, 0.60),
    ]:
        p = earnings_power(aum, yld, incr_m, tax, shares, nonop)
        p["label"] = label
        p["shares_m"] = round(shares, 1)
        p["incr_margin"] = incr_m
        scenarios.append(p)

    # daily series for chart (compact): last ~180 obs
    daily_series = [{"d": d, "aum_bn": round(daily["total"][d] / 1000, 3)} for d in daily["dates"][-180:]]
    # monthly last 60
    monthly_series = list(reversed(monthly))[-60:] if monthly else []

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "asof": asof,
        "stale": stale,
        "stale_days": stale_days,
        "source_aum": AUM_URL,
        "source_inflows": INFLOWS_URL,
        "aum": {
            "etp_onchain_m": round(total_m, 1),
            "etp_onchain_bn": round(etp_bn, 3),
            "private_lagged_bn": private,
            "private_asof": BASE["period_end"],
            "company_bn": round(company_bn, 3),
            "divisions": div_latest,
            "categories_bn": cats_latest,
        },
        "changes": changes,
        "weekly": weeks[-104:],   # ~2y if available; daily sheet only has YTD 2026
        "daily": daily_series,
        "monthly": monthly_series,
        "base": {**BASE, "rev_yield": round(BASE["rev_yield"], 8),
                 "rev_annual_m": round(BASE["rev_q_m"] * 4, 1),
                 "adj_op_annual_m": round(BASE["adj_op_q_m"] * 4, 1),
                 "nonop_annual_m": round(BASE["nonop_annual_m"], 3)},
        "assumptions_default": {
            "rev_yield": round(yld, 8),
            "incr_op_margin": incr,
            "tax_rate": tax,
            "diluted_shares_m": sh,
            "nonop_annual_m": round(nonop, 3),
            "aum_basis": "company_bn",
        },
        "earnings_power": {
            "label": "Annualized earnings power at current AUM",
            "disclaimer": "Not quarterly EPS, not guidance. Applies the latest reported revenue yield to current AUM, then layers an incremental operating-margin assumption on the revenue change vs the Q3'26 annualized base. Non-operating items and diluted shares held at the Q3'26 reported run-rate unless overridden. Private AUM is lagged to the last quarter-end report.",
            "at_q3_avg_aum": base_power,
            "at_current_etp": cur_etp,
            "at_current_company": cur_co,
        },
        "scenarios": scenarios,
        "convertibles": CONVERT,
        "coverage": {
            "daily_from": daily["dates"][0],
            "daily_to": daily["dates"][-1],
            "daily_n": len(daily["dates"]),
            "weekly_n": len(weeks),
            "monthly_n": len(monthly),
            "note": "IR Historical ETF AUM workbook publishes daily EOP AUM (YTD window on the Daily_EOP tab) and a long monthly history. Weekly series is the last observation in each ISO week. Totals exclude Ceres private AUM; company AUM adds the last reported private figure.",
        },
        "warnings": WARN,
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("wt_earnings_power:", asof, f"ETP ${etp_bn:.1f}bn", f"co ${company_bn:.1f}bn",
          f"EPS power ${cur_co['eps']:.2f}", f"stale={stale}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("::warning::wt_earnings_power failed; previous data/wt_earnings_power.json kept")
        sys.exit(0)
