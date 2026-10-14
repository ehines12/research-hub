"""Forward-looking context for the Bank Conditions page (NOT part of the diffusion score).
Valuation, positioning and rate-shock indicators from free public sources, each with its own as-of date.
Every value is a published number or a direct arithmetic transform of one; failed sources keep the last good
copy (flagged stale) and are never filled in."""
import bisect, datetime as dt, json, subprocess, time
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
CACHE = DATA / "bank-fwd-raw.json"
FD_URL = "https://raw.githubusercontent.com/ehines12/financials-dashboard/main/web/data/data.json"
FDIC = "https://api.fdic.gov/banks/financials"
UA = "Mozilla/5.0 (research-hub data refresh)"


def _curl(url, timeout=120):
    last = None
    for i in range(3):
        r = subprocess.run(["curl", "-sSfL", "--max-time", str(timeout), "-A", UA, url], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        last = f"curl exit {r.returncode}: {r.stderr.strip()[:150]}"
        time.sleep(4 * (i + 1))
    raise RuntimeError(last)


def fdic(filt):
    from urllib.parse import urlencode
    q = urlencode({"filters": f"REPDTE:[20080101 TO 20991231] AND {filt}", "agg_by": "REPDTE",
                   "agg_sum_fields": "EQ,ASSET,SCAF,SCAA,SCHA,SCHF", "agg_limit": 500, "limit": 1, "format": "json"})
    rows = sorted((x["data"] for x in json.loads(_curl(f"{FDIC}?{q}", 180))["data"]), key=lambda x: x["REPDTE"])
    if len(rows) < 40:
        raise ValueError("too few FDIC quarters")
    out = []
    for x in rows:
        d = dt.datetime.strptime(x["REPDTE"], "%Y%m%d").date().isoformat()
        out.append([d, {k: x[f"sum_{k}"] for k in ("EQ", "ASSET", "SCAF", "SCAA", "SCHA", "SCHF")} | {"n": x["count"]}])
    return out


def yahoo(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1136073600&period2=9999999999&interval=1d&events=div"
    res = json.loads(_curl(url, 60))["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    day = lambda t: dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()
    close = [[day(t), round(c, 4)] for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
    divs = sorted([day(v["date"]), v["amount"]] for v in (res.get("events") or {}).get("dividends", {}).values())
    if len(close) < 2000 or len(divs) < 20:
        raise ValueError("too little history")
    return {"close": close, "divs": divs}


def fetch_all():
    import fetch_data
    prev = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    jobs = {"fd": lambda: {k: v["data"] for k, v in json.loads(_curl(FD_URL))["series"].items() if k in ("KRE_SI_PCT_SO", "KRE_SO")},
            "fdic_all": lambda: fdic("ASSET:[1 TO 99999999999]"),
            "fdic_cb": lambda: fdic("CB:1"),
            "fdic_u100": lambda: fdic("ASSET:[1 TO 100000000]"),
            "KRE": lambda: yahoo("KRE"), "SPY": lambda: yahoo("SPY"),
            "DGS10": lambda: fetch_data.fetch("DGS10")[2], "DGS2": lambda: fetch_data.fetch("DGS2")[2]}
    raw, st = {}, {}
    for k, f in jobs.items():
        try:
            v = f()
            if k == "fd" and not (v.get("KRE_SI_PCT_SO") and v.get("KRE_SO")):
                raise ValueError("KRE SI / shares outstanding missing from Financials Dashboard data")
            raw[k] = [[t, x] for t, x in v] if k.startswith("DGS") else v
            st[k] = {"status": "ok"}
        except Exception as e:  # noqa
            st[k] = {"status": "stale" if k in prev else "failed", "error": str(e)[:200]}
            if k in prev:
                raw[k] = prev[k]
            print(f"  fwd {k}: FAILED ({e})")
    CACHE.write_text(json.dumps(raw, separators=(",", ":")))
    return raw, st


def asof(ser, d, max_days=None):
    ds = [t for t, _ in ser]
    i = bisect.bisect_right(ds, d) - 1
    if i < 0 or (max_days is not None and (dt.date.fromisoformat(d) - dt.date.fromisoformat(ds[i])).days > max_days):
        return None
    return ser[i]


def series(raw):
    S = {}
    # dividend yield: trailing 12-month dividends / unadjusted close
    for sym in ("KRE", "SPY"):
        if sym not in raw: continue
        dv = raw[sym]["divs"]; out = []
        for d, c in raw[sym]["close"]:
            lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat()
            ttm = sum(a for t, a in dv if lo < t <= d)
            if ttm and d >= "2007-07-01":
                out.append([d, round(100 * ttm / c, 3)])
        S[f"{sym}_DY"] = out
    if "KRE_DY" in S and "SPY_DY" in S:
        sp = dict(S["SPY_DY"]); S["KRE_SPY_DY"] = [[d, round(v - sp[d], 3)] for d, v in S["KRE_DY"] if d in sp]
    # P/B PROXY: KRE price / book-value index of insured banks under $100bn (aggregate equity, rebased), released ~60 days after quarter end
    if "KRE" in raw and "fdic_u100" in raw:
        eq = [[(dt.date.fromisoformat(d) + dt.timedelta(days=60)).isoformat(), v["EQ"]] for d, v in raw["fdic_u100"]]
        out = []
        for d, c in raw["KRE"]["close"]:
            e = asof(eq, d)
            if e: out.append([d, c / e[1]])
        if out:
            b = out[0][1]; S["PB_PROXY"] = [[d, round(100 * v / b, 2)] for d, v in out]
    # unrealized securities losses, % of equity (fair value minus amortized cost, AFS + HTM), quarter-end date
    for k, lab in (("fdic_all", "UL_ALL"), ("fdic_cb", "UL_CB")):
        if k in raw:
            S[lab] = [[d, round(100 * ((v["SCAF"] - v["SCAA"]) + (v["SCHF"] - v["SCHA"])) / v["EQ"], 2)] for d, v in raw[k] if v["EQ"]]
    for k in ("DGS10", "DGS2"):
        if k in raw:
            s = raw[k]; out = []
            for d, v in s:
                p = asof(s, (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat(), 7)
                if p: out.append([d, round(100 * (v - p[1]), 1)])
            S[f"{k}_12M"] = out  # bp
    if "fd" in raw:
        S["KRE_SI"] = raw["fd"]["KRE_SI_PCT_SO"]
        so = [x for x in raw["fd"]["KRE_SO"] if x[1] > 0]; out = []
        for d, v in so:
            p = asof(so, (dt.date.fromisoformat(d) - dt.timedelta(days=91)).isoformat(), 7)
            if p and d >= "2008-01-01": out.append([d, round(100 * (v / p[1] - 1), 1)])
        S["KRE_SO_3M"] = out
    return S


META = [  # key, label, unit, group, release lag (days after as-of date before it was public), "cheap/stressed" direction note
    ("PB_PROXY", "KRE price-to-book PROXY (KRE price / aggregate equity of insured banks < $100bn, Jan 2008 = 100)", "idx", "Valuation", 0, "low = cheap"),
    ("KRE_DY", "KRE trailing 12-month dividend yield", "%", "Valuation", 0, "high = cheap"),
    ("KRE_SPY_DY", "KRE minus SPY dividend yield", "pp", "Valuation", 0, "high = cheap vs S&P 500"),
    ("KRE_SI", "KRE short interest, % of shares outstanding (FINRA / State Street)", "%", "Positioning", 9, "high = crowded short"),
    ("KRE_SO_3M", "KRE shares outstanding, 3-month change (creations - redemptions)", "%", "Positioning", 1, "low = outflows"),
    ("DGS10_12M", "10Y Treasury, 12-month change", "bp", "Rate shock", 1, "high = rate shock"),
    ("DGS2_12M", "2Y Treasury, 12-month change", "bp", "Rate shock", 1, "high = rate shock"),
    ("UL_ALL", "Unrealized securities gains (-losses), AFS + HTM, % of equity: all insured banks", "%", "Rate shock", 60, "low = larger losses"),
    ("UL_CB", "Unrealized securities gains (-losses), AFS + HTM, % of equity: community banks", "%", "Rate shock", 60, "low = larger losses"),
]


def pctile(ser, d, years=10):
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365 * years)).isoformat()
    v = [x for t, x in ser if lo <= t <= d]
    cur = asof(ser, d)
    if not cur or len(v) < 8: return None
    return round(100 * sum(1 for x in v if x <= cur[1]) / len(v))


def at(S, k, lag, d):
    """value public at date d (as-of date + release lag <= d)"""
    s = S.get(k)
    if not s: return None
    p = asof(s, (dt.date.fromisoformat(d) - dt.timedelta(days=lag)).isoformat(), 200)
    return p and {"date": p[0], "value": p[1], "pct": pctile(s, p[0])}


def episodes(S, hist, kre, iwm):
    """first crossings of the ex-equity index below its 26-wk high, re-armed above -15"""
    H = [h for h in hist if not h.get("live")] + [hist[-1]]
    dates = [h["date"] for h in H]; s = [h.get("score_ex") for h in H]; N = len(H)
    off = [None if s[i] is None else s[i] - max(x for x in s[max(0, i - 26):i + 1] if x is not None) for i in range(N)]
    K = [asof(kre, d) for d in dates]; I = [asof(iwm, d) for d in dates]
    out = {}
    for T in (20, 25):
        eps, armed = [], True
        for i, o in enumerate(off):
            if o is None: continue
            if armed and o <= -T:
                r = lambda n, B=None: None if i + n >= N or H[i + n].get("live") or not K[i] else round(100 * ((K[i + n][1] / K[i][1]) / ((I[i + n][1] / I[i][1]) if B else 1) - 1), 1)
                eps.append({"date": dates[i], "index": s[i], "off": round(o, 1), "abs3": r(13), "rel3": r(13, 1), "abs6": r(26), "rel6": r(26, 1),
                            "ind": {k: at(S, k, lag, dates[i]) for k, *_x, lag, _n in [(m[0], m[1], m[2], m[3], m[4], m[5]) for m in META]}})
                armed = False
            elif not armed and o > -15:
                armed = True
        out[str(T)] = eps
    return out


def build(R, hist, today):
    raw, st = fetch_all()
    S = series(raw)
    cur = []
    for k, lab, unit, grp, lag, note in META:
        s = S.get(k)
        last = s[-1] if s else None
        cur.append({"key": k, "label": lab, "unit": unit, "group": grp, "note": note,
                    "value": last and last[1], "date": last and last[0], "pct10y": last and pctile(s, last[0]),
                    "from": s[0][0] if s else None})
    return {"current": cur,
            "episodes": episodes(S, hist, R.get("KRE", []), R.get("IWM", [])), "sources": st}
