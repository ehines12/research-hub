"""Bank Conditions diffusion index (research hub tile #/bank-conditions).

Every input is real published data: FRED (fredgraph CSV, via fetch_data.fetch / curl) and Yahoo Finance
daily chart JSON for ETF relative performance. Each component is scored +1 / 0 / -1 by a fixed, transparent
rule; diffusion = 100 * (favorable + 0.5 * neutral) / scored components.
History is rebuilt weekly using only observations whose estimated publication date is on or before each
week (see PUB_LAG). Values are today's vintage (revisions, e.g. H.8, are not point-in-time) - noted on page.
If a source fails, its last good copy (data/bank-conditions-raw.json) is shown but flagged STALE and excluded.
"""
import json, bisect, datetime as dt, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW_PATH = DATA / "bank-conditions-raw.json"
CSV_PATH = DATA / "bank-conditions-history.csv"
KEEP_FROM = "2008-01-01"
HIST_FROM = "2012-01-06"

FRED_IDS = ["SOFR", "DGS5", "T10Y2Y", "T10Y3M", "LLBSCBW027SBOG", "LLBDCBW027SBOG", "DPSSCBW027SBOG", "NFCI", "STLFSI4",
            "VIXCLS", "BAMLH0A0HYM2", "BAMLC0A4CBBB", "DRTSCILM", "DRSDCILM", "SUBLPDRCSC", "SUBLPDRCSN", "SUBLPDRCSM",
            "SUBLPDRCDC", "SUBLPDRCDN", "SUBLPDRCDM", "ICSA", "CORALACBS", "DRALACBS", "NDR12MCD", "FEDFUNDS", "DGS10", "DGS1", "DFF", "MMNDR", "LTDSCBW027SBOG", "H8B3094NSMD",
            "DRCRELEXFACBS", "CORCREXFACBS", "BOGZ1FL075035503Q", "WLCFLL"]
TICKERS = ["KRE", "XLF", "IWM", "SPY", "^MOVE"]
# estimated days from FRED observation date to public release (point-in-time history)
PUB_LAG = {"SOFR": 1, "DGS5": 1, "T10Y2Y": 1, "T10Y3M": 1, "VIXCLS": 1, "BAMLH0A0HYM2": 1, "BAMLC0A4CBBB": 1,
           "LLBSCBW027SBOG": 9, "LLBDCBW027SBOG": 9, "DPSSCBW027SBOG": 9, "NFCI": 5, "STLFSI4": 6, "ICSA": 5,
           "DRTSCILM": 40, "DRSDCILM": 40, "SUBLPDRCSC": 40, "SUBLPDRCSN": 40, "SUBLPDRCSM": 40, "SUBLPDRCDC": 40,
           "SUBLPDRCDN": 40, "SUBLPDRCDM": 40, "CORALACBS": 145, "DRALACBS": 145, "NDR12MCD": 50, "FEDFUNDS": 32,
           "KRE": 0, "XLF": 0, "IWM": 0, "SPY": 0, "^MOVE": 0,
           "DGS10": 1, "DGS1": 1, "DFF": 1, "MMNDR": 50, "LTDSCBW027SBOG": 9, "H8B3094NSMD": 9, "DRCRELEXFACBS": 145,
           "CORCREXFACBS": 145, "BOGZ1FL075035503Q": 165, "WLCFLL": 1}
MAX_AGE = {"d": 7, "q2": 300, "w": 21, "m": 80, "q": 240}   # days; older latest value => STALE (excluded)
D = dt.date.fromisoformat


def _yahoo(sym):
    p1 = int(dt.datetime(2008, 1, 1).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^', '%5E')}?period1={p1}&period2=9999999999&interval=1d"
    last = None
    for i in range(3):
        r = subprocess.run(["curl", "-sSfL", "--max-time", "60", "-A", "Mozilla/5.0 (research-hub data refresh)", url],
                           capture_output=True, text=True)
        try:
            if r.returncode:
                raise RuntimeError(f"curl exit {r.returncode}: {r.stderr.strip()[:150]}")
            res = json.loads(r.stdout)["chart"]["result"][0]
            off = res["meta"].get("gmtoffset", 0)
            adj = res["indicators"]["adjclose"][0]["adjclose"]
            obs = {}
            for t, v in zip(res["timestamp"], adj):
                if v is not None:
                    obs[dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()] = round(v, 4)
            if len(obs) < 500:
                raise RuntimeError("too few observations")
            return "Yahoo Finance", url, sorted(obs.items())
        except Exception as e:  # noqa
            last = e
            time.sleep(3 * (i + 1))
    raise last


def fetch_all():
    import fetch_data
    from concurrent.futures import ThreadPoolExecutor
    prev = json.loads(RAW_PATH.read_text()) if RAW_PATH.exists() else {}
    jobs = [(k, lambda k=k: fetch_data.fetch(k)) for k in FRED_IDS] + [(k, lambda k=k: _yahoo(k)) for k in TICKERS]

    def run(job):
        try:
            return job[1]()
        except Exception as e:  # noqa
            return e
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = dict(zip([j[0] for j in jobs], ex.map(run, jobs)))
    raw, st = {}, {}
    for k, r in res.items():
        if isinstance(r, Exception):
            old = prev.get(k)
            st[k] = {"status": "stale" if old else "failed", "error": str(r)[:300]}
            if old:
                raw[k] = old
            print(f"  {k}: FAILED ({r})")
            continue
        src, url, obs = r
        raw[k] = [[t, v] for t, v in obs if t >= KEEP_FROM]
        st[k] = {"status": "ok", "src": src}
    RAW_PATH.write_text(json.dumps(raw, separators=(",", ":")))
    return raw, st


# ---------- value-series builders (each returns [(date_str, value)]) ----------
def _join(a, b, f):
    bd = dict(b)
    return [(t, f(v, bd[t])) for t, v in a if t in bd]


def _asof_join(a, b, f):
    """b value = latest b observation on/before a's date (for mixed frequencies)."""
    bt = [t for t, _ in b]
    out = []
    for t, v in a:
        i = bisect.bisect_right(bt, t) - 1
        if i >= 0:
            out.append((t, f(v, b[i][1])))
    return out


def _accel(L):
    out = []
    for i in range(52, len(L)):
        g13 = ((L[i][1] / L[i - 13][1]) ** 4 - 1) * 100
        g52 = (L[i][1] / L[i - 52][1] - 1) * 100
        out.append((L[i][0], g13 - g52))
    return out


def _chg(s, n):
    return [(s[i][0], s[i][1] - s[i - n][1]) for i in range(n, len(s))]


def _relret(a, b, n):
    r = _join(a, b, lambda x, y: x / y)
    return [(r[i][0], (r[i][1] / r[i - n][1] - 1) * 100) for i in range(n, len(r))]


def _avg(*ss):
    ds = [dict(s) for s in ss]
    common = sorted(set.intersection(*[set(d) for d in ds]))
    return [(t, sum(d[t] for d in ds) / len(ds)) for t in common]


def _ma_ratio(s, short, long):
    out = []
    for i in range(long - 1, len(s)):
        a = sum(v for _, v in s[i - short + 1:i + 1]) / short
        b = sum(v for _, v in s[i - long + 1:i + 1]) / long
        out.append((s[i][0], (a / b - 1) * 100))
    return out


def _yoy_n(s, n):
    return [(s[i][0], (s[i][1] / s[i - n][1] - 1) * 100) for i in range(n, len(s))]


def _scale(s, k):
    return [(t, v * k) for t, v in s]


# ---------- rules ----------
def absband(fav, unf):
    """Size of the move in either direction: |v| <= fav -> +1, |v| >= unf -> -1."""
    def f(vals, i):
        v = abs(vals[i][1])
        return 1 if v <= fav else (-1 if v >= unf else 0)
    return f


def policy_rule(vals, i):
    v = vals[i][1]
    return -1 if v >= 2 else (1 if -4 < v <= 0.5 else 0)


def fed_lending_rule(vals, i):
    t = D(vals[i][0]); j = bisect.bisect_right(vals, ((t - dt.timedelta(days=28)).isoformat(),)) - 1
    if j < 0:
        return None
    d = vals[i][1] - vals[j][1]
    if d >= 2 or vals[i][1] >= 50:
        return -1
    return 1 if d <= 0.5 else 0

def band(fav, unf, better):
    """better='high': v>=fav -> +1, v<=unf -> -1. better='low': v<=fav -> +1, v>=unf -> -1."""
    def f(vals, i):
        v = vals[i][1]
        if better == "high":
            return 1 if v >= fav else (-1 if v <= unf else 0)
        return 1 if v <= fav else (-1 if v >= unf else 0)
    return f


def pctile(better, years=5, min_years=1):
    """Percentile of the value within its own trailing window (point in time). Better third = +1, worst third = -1."""
    def f(vals, i):
        t = D(vals[i][0])
        lo = (t - dt.timedelta(days=int(365.25 * years))).isoformat()
        j = bisect.bisect_left(vals, (lo,))
        w = [x[1] for x in vals[j:i + 1]]
        if (t - D(vals[j][0])).days < 365 * min_years or len(w) < 20:
            return None
        p = 100 * sum(1 for x in w if x < vals[i][1]) / (len(w) - 1 or 1)
        q = 100 - p if better == "low" else p
        return 1 if q >= 67 else (-1 if q <= 33 else 0), p
    return f


def components(R):
    s = lambda k: [(t, v) for t, v in R.get(k, [])]
    smdep = s("DPSSCBW027SBOG")
    ltd_share = _join(s("LTDSCBW027SBOG"), smdep, lambda a, b: a / b * 100)
    bor_vs_dep = _join(_yoy_n(s("H8B3094NSMD"), 52), _yoy_n(smdep, 52), lambda a, b: a - b)
    ldr = _join(s("LLBSCBW027SBOG"), s("DPSSCBW027SBOG"), lambda a, b: a / b * 100)
    C = [
        # key, category, name, unit, freq, series, sources, rule fn, rule text, better
        ("5y_sofr", "Curve & funding", "5Y Treasury minus SOFR", "pp", "d", _join(s("DGS5"), s("SOFR"), lambda a, b: a - b),
         ["DGS5", "SOFR"], band(0.25, -0.25, "high"), "≥ +0.25 favorable · ≤ −0.25 unfavorable (asset yields vs overnight funding)", "high"),
        ("2s10s", "Curve & funding", "2s10s Treasury slope", "pp", "d", s("T10Y2Y"), ["T10Y2Y"], band(0.50, 0.0, "high"),
         "≥ +0.50 favorable · ≤ 0 (inverted) unfavorable", "high"),
        ("3m10y", "Curve & funding", "3m10y Treasury slope", "pp", "d", s("T10Y3M"), ["T10Y3M"], band(0.50, 0.0, "high"),
         "≥ +0.50 favorable · ≤ 0 (inverted) unfavorable", "high"),
        ("ust10_1m", "Curve & funding", "10Y Treasury: 1-month change", "bp", "d", _scale(_chg(s("DGS10"), 21), 100), ["DGS10"], absband(25, 50),
         "Size of 21-trading-day move, either direction: ≤ 25bp favorable · ≥ 50bp unfavorable (rate volatility hits AOCI, mortgage and deposit repricing)", "abs"),
        ("ust10_3m", "Curve & funding", "10Y Treasury: 3-month change", "bp", "d", _scale(_chg(s("DGS10"), 63), 100), ["DGS10"], absband(40, 75),
         "Size of 63-trading-day move, either direction: ≤ 40bp favorable · ≥ 75bp unfavorable", "abs"),
        ("policy_path", "Curve & funding", "Policy path priced, next 12 mo (PROXY: 1Y Treasury − eff. fed funds)", "# of 25bp", "d",
         _join(s("DGS1"), s("DFF"), lambda a, b: (a - b) / 0.25), ["DGS1", "DFF"], policy_rule,
         "PROXY, not futures: (1Y CMT − EFFR)/25bp ≈ net hikes(+)/cuts(−) priced. ≥ +2 hikes unfavorable · −4 to +0.5 favorable · otherwise neutral (≤ −4 = recession-scale cuts)", "low"),
        ("h8_small_loans", "H.8 balance sheets", "Small-bank loan growth: accel/decel", "pp", "w", _accel(s("LLBSCBW027SBOG")),
         ["LLBSCBW027SBOG"], band(1.0, -1.0, "high"), "13-wk annualized minus 52-wk growth: ≥ +1pp accelerating (favorable) · ≤ −1pp decelerating", "high"),
        ("h8_dom_loans", "H.8 balance sheets", "Domestic-bank loan growth: accel/decel", "pp", "w", _accel(s("LLBDCBW027SBOG")),
         ["LLBDCBW027SBOG"], band(1.0, -1.0, "high"), "13-wk annualized minus 52-wk growth: ≥ +1pp favorable · ≤ −1pp unfavorable", "high"),
        ("h8_small_deps", "H.8 balance sheets", "Small-bank deposit growth: accel/decel", "pp", "w", _accel(s("DPSSCBW027SBOG")),
         ["DPSSCBW027SBOG"], band(1.0, -1.0, "high"), "13-wk annualized minus 52-wk growth: ≥ +1pp favorable · ≤ −1pp unfavorable", "high"),
        ("h8_small_ldr", "H.8 balance sheets", "Small-bank loans-to-deposits", "%", "w", ldr, ["LLBSCBW027SBOG", "DPSSCBW027SBOG"],
         pctile("low"), "Percentile vs trailing 5 yrs: lowest third favorable (liquidity room to lend) · highest third unfavorable (funding strain)", "low"),
        ("nfci", "Financial conditions", "Chicago Fed NFCI", "index", "w", s("NFCI"), ["NFCI"], pctile("low"),
         "Percentile vs trailing 5 yrs: loosest third favorable · tightest third unfavorable", "low"),
        ("stlfsi", "Financial conditions", "St. Louis Fed Financial Stress (STLFSI4)", "index", "w", s("STLFSI4"), ["STLFSI4"], pctile("low"),
         "Percentile vs trailing 5 yrs: lowest-stress third favorable · highest third unfavorable", "low"),
        ("vix", "Financial conditions", "VIX", "index", "d", s("VIXCLS"), ["VIXCLS"], pctile("low"),
         "Percentile vs trailing 5 yrs: lowest third favorable · highest third unfavorable", "low"),
        ("move", "Financial conditions", "ICE BofA MOVE index (Treasury vol)", "index", "d", s("^MOVE"), ["^MOVE"], pctile("low"),
         "Percentile vs trailing 5 yrs: lowest third favorable · highest third unfavorable", "low"),
        ("hy_lvl", "Credit", "HY OAS level", "pp", "d", s("BAMLH0A0HYM2"), ["BAMLH0A0HYM2"], pctile("low"),
         "Percentile vs trailing window (up to 5 yrs; FRED history begins Oct 2023): tightest third favorable · widest third unfavorable", "low"),
        ("hy_4w", "Credit", "HY OAS 4-week change", "pp", "d", _chg(s("BAMLH0A0HYM2"), 20), ["BAMLH0A0HYM2"], band(-0.15, 0.15, "low"),
         "20-trading-day change: ≤ −0.15 tightening favorable · ≥ +0.15 widening unfavorable", "low"),
        ("bbb_lvl", "Credit", "BBB OAS level", "pp", "d", s("BAMLC0A4CBBB"), ["BAMLC0A4CBBB"], pctile("low"),
         "Percentile vs trailing window (up to 5 yrs; FRED history begins Oct 2023): tightest third favorable · widest third unfavorable", "low"),
        ("bbb_4w", "Credit", "BBB OAS 4-week change", "pp", "d", _chg(s("BAMLC0A4CBBB"), 20), ["BAMLC0A4CBBB"], band(-0.05, 0.05, "low"),
         "20-trading-day change: ≤ −0.05 favorable · ≥ +0.05 unfavorable", "low"),
        ("sloos_ci_std", "Credit", "SLOOS C&I standards (large/mid firms)", "net %", "q", s("DRTSCILM"), ["DRTSCILM"], band(0, 10, "low"),
         "Net % tightening: ≤ 0 (easing/unchanged) favorable · ≥ 10 unfavorable", "low"),
        ("sloos_ci_dem", "Credit", "SLOOS C&I demand (large/mid firms)", "net %", "q", s("DRSDCILM"), ["DRSDCILM"], band(5, -5, "high"),
         "Net % reporting stronger demand: ≥ +5 favorable · ≤ −5 unfavorable", "high"),
        ("sloos_cre_std", "Credit", "SLOOS CRE standards (avg of 3 types)", "net %", "q",
         _avg(s("SUBLPDRCSC"), s("SUBLPDRCSN"), s("SUBLPDRCSM")), ["SUBLPDRCSC", "SUBLPDRCSN", "SUBLPDRCSM"], band(0, 10, "low"),
         "Avg net % tightening (construction & land, nonfarm nonres., multifamily): ≤ 0 favorable · ≥ 10 unfavorable", "low"),
        ("sloos_cre_dem", "Credit", "SLOOS CRE demand (avg of 3 types)", "net %", "q",
         _avg(s("SUBLPDRCDC"), s("SUBLPDRCDN"), s("SUBLPDRCDM")), ["SUBLPDRCDC", "SUBLPDRCDN", "SUBLPDRCDM"], band(5, -5, "high"),
         "Avg net % stronger demand: ≥ +5 favorable · ≤ −5 unfavorable", "high"),
        ("claims", "Credit", "Initial claims trend", "%", "w", _ma_ratio(s("ICSA"), 4, 52), ["ICSA"], band(0, 5, "low"),
         "4-wk avg vs 52-wk avg: ≤ 0% favorable · ≥ +5% unfavorable", "low"),
        ("nco", "Credit", "Net charge-off rate, all loans: y/y change", "pp", "q", _chg(s("CORALACBS"), 4), ["CORALACBS"], band(-0.05, 0.05, "low"),
         "Change vs 4 quarters earlier: ≤ −0.05 improving (favorable) · ≥ +0.05 worsening", "low"),
        ("dq", "Credit", "Delinquency rate, all loans: y/y change", "pp", "q", _chg(s("DRALACBS"), 4), ["DRALACBS"], band(-0.10, 0.10, "low"),
         "Change vs 4 quarters earlier: ≤ −0.10 favorable · ≥ +0.10 unfavorable", "low"),
        ("kre_xlf_1m", "Equity relative performance", "KRE vs XLF, 1-month", "%", "d", _relret(s("KRE"), s("XLF"), 21), ["KRE", "XLF"],
         band(1, -1, "high"), "21-trading-day relative total return (small/regional banks vs broad financials): ≥ +1% favorable · ≤ −1% unfavorable", "high"),
        ("kre_xlf_3m", "Equity relative performance", "KRE vs XLF, 3-month", "%", "d", _relret(s("KRE"), s("XLF"), 63), ["KRE", "XLF"],
         band(2, -2, "high"), "63-trading-day relative total return: ≥ +2% favorable · ≤ −2% unfavorable", "high"),
        ("iwm_spy_1m", "Equity relative performance", "IWM vs SPY, 1-month", "%", "d", _relret(s("IWM"), s("SPY"), 21), ["IWM", "SPY"],
         band(1, -1, "high"), "21-trading-day relative total return (small vs large caps): ≥ +1% favorable · ≤ −1% unfavorable", "high"),
        ("iwm_spy_3m", "Equity relative performance", "IWM vs SPY, 3-month", "%", "d", _relret(s("IWM"), s("SPY"), 63), ["IWM", "SPY"],
         band(2, -2, "high"), "63-trading-day relative total return: ≥ +2% favorable · ≤ −2% unfavorable", "high"),
        ("dep_pricing", "Deposit competition & funding", "12-mo CD (FDIC national) minus fed funds: 3-mo change", "pp", "m",
         _chg(_asof_join(s("NDR12MCD"), s("FEDFUNDS"), lambda a, b: a - b), 3), ["NDR12MCD", "FEDFUNDS", "DGS10", "DGS1", "DFF", "MMNDR", "LTDSCBW027SBOG", "H8B3094NSMD",
            "DRCRELEXFACBS", "CORCREXFACBS", "BOGZ1FL075035503Q", "WLCFLL"], band(-0.10, 0.10, "low"),
         "3-month change in CD-minus-fed-funds spread: ≤ −0.10 (deposit rates lagging policy) favorable · ≥ +0.10 (deposit pricing pressure) unfavorable", "low"),
        ("dep_mmda", "Deposit competition & funding", "MMDA (FDIC national) minus fed funds: 3-mo change", "pp", "m",
         _chg(_asof_join(s("MMNDR"), s("FEDFUNDS"), lambda a, b: a - b), 3), ["MMNDR", "FEDFUNDS"], band(-0.10, 0.10, "low"),
         "3-month change in MMDA-minus-fed-funds spread: ≤ −0.10 favorable · ≥ +0.10 (rising deposit competition) unfavorable", "low"),
        ("ltd_share", "Deposit competition & funding", "Small-bank large time deposits, % of deposits: 13-wk change", "pp", "w",
         _chg(ltd_share, 13), ["LTDSCBW027SBOG", "DPSSCBW027SBOG"], band(-0.25, 0.25, "low"),
         "13-week change in share: ≤ −0.25pp favorable · ≥ +0.25pp (mix shifting to costly CDs) unfavorable", "low"),
        ("bor_vs_dep", "Deposit competition & funding", "Small-bank borrowings growth minus deposit growth (y/y)", "pp", "w", bor_vs_dep,
         ["H8B3094NSMD", "DPSSCBW027SBOG"], band(0, 10, "low"),
         "52-wk borrowings growth (H.8, NSA) minus 52-wk deposit growth: ≤ 0 favorable · ≥ +10pp (wholesale funding replacing deposits) unfavorable", "low"),
        ("fed_lending", "Deposit competition & funding", "Fed loans to depository institutions (H.4.1)", "$bn", "w", _scale(s("WLCFLL"), 0.001),
         ["WLCFLL"], fed_lending_rule,
         "H.4.1 total loans (discount window primary/secondary/seasonal credit plus BTFP-type facilities when active): 4-wk rise ≥ $2bn or level ≥ $50bn unfavorable · 4-wk change ≤ +$0.5bn favorable", "low"),
        ("cre_dq", "CRE stress", "CRE delinquency rate (ex-farm): y/y change", "pp", "q", _chg(s("DRCRELEXFACBS"), 4), ["DRCRELEXFACBS"],
         band(-0.10, 0.10, "low"), "Change vs 4 quarters earlier: ≤ −0.10 favorable · ≥ +0.10 unfavorable", "low"),
        ("cre_nco", "CRE stress", "CRE net charge-off rate (ex-farm): y/y change", "pp", "q", _chg(s("CORCREXFACBS"), 4), ["CORCREXFACBS"],
         band(-0.05, 0.05, "low"), "Change vs 4 quarters earlier: ≤ −0.05 favorable · ≥ +0.05 unfavorable", "low"),
        ("cre_px", "CRE stress", "Commercial real estate prices (Fed Z.1): y/y", "%", "q", _yoy_n(s("BOGZ1FL075035503Q"), 4), ["BOGZ1FL075035503Q"],
         band(2, -2, "high"), "Year-over-year change: ≥ +2% favorable · ≤ −2% unfavorable", "high"),
    ]
    return C


def score_series(vals, rule):
    """Signal at every observation, using only that observation and earlier ones."""
    out = []
    dates = [x[0] for x in vals]
    for i in range(len(vals)):
        r = rule(vals, i)
        if r is None:
            out.append(None)
        elif isinstance(r, tuple):
            out.append(r)
        else:
            out.append((r, None))
    return out


def diffusion(sigs):
    sigs = [x for x in sigs if x is not None]
    if not sigs:
        return None
    return round(100 * (sum(1 for x in sigs if x == 1) + 0.5 * sum(1 for x in sigs if x == 0)) / len(sigs), 1)


def label(x):
    return None if x is None else ("Supportive" if x > 60 else ("Challenging" if x < 40 else "Neutral"))


def kre_rows(R, hist):
    """Weekly KRE price and KRE/IWM relative (rebased 100) on the index grid."""
    def asof(ser):
        ds = [t for t, _ in ser]; vs = [v for _, v in ser]
        return lambda g: (vs[bisect.bisect_right(ds, g) - 1] if bisect.bisect_right(ds, g) else None)
    if not R.get("KRE") or not R.get("IWM"):
        return []
    k, w = asof(R["KRE"]), asof(R["IWM"])
    rows, base = [], None
    for h in hist:
        kv, wv = k(h["date"]), w(h["date"])
        if kv is None or wv is None:
            rows.append({"date": h["date"], "kre": None, "rel": None}); continue
        r = kv / wv
        base = base or r
        rows.append({"date": h["date"], "kre": round(kv, 2), "rel": round(100 * r / base, 2)})
    return rows


def deterioration(R, hist, key="score_ex"):
    """In-sample: forward KRE returns bucketed by how far the ex-equity index sits below its trailing 26-week high."""
    import statistics as S
    if not all(R.get(k) for k in ("KRE", "IWM", "XLF")):
        return None
    H = [h for h in hist if not h.get("live")]
    dates = [h["date"] for h in H]; N = len(H)
    def asof(k):
        ds = [t for t, _ in R[k]]; vs = [v for _, v in R[k]]
        return ds, vs, [vs[bisect.bisect_right(ds, g) - 1] if bisect.bisect_right(ds, g) else None for g in dates]
    kd, kv, K = asof("KRE"); _, _, I = asof("IWM"); _, _, X = asof("XLF")
    def rel(a, b, n): return [None if i + n >= N or None in (a[i], b[i]) else 100 * ((a[i + n] / a[i]) / (b[i + n] / b[i]) - 1) for i in range(N)]
    def mdd(n):
        out = []
        for i, g in enumerate(dates):
            if i + n >= N: out.append(None); continue
            a = bisect.bisect_right(kd, g) - 1; e = bisect.bisect_right(kd, dates[i + n])
            out.append(100 * (min(kv[a:e]) / kv[a] - 1))
        return out
    F = {"rel_iwm_13": rel(K, I, 13), "rel_iwm_26": rel(K, I, 26), "rel_xlf_26": rel(K, X, 26), "mdd_26": mdd(26)}
    s = [h.get(key) for h in H]
    off = [None if s[i] is None else s[i] - max(x for x in s[max(0, i - 26):i + 1] if x is not None) for i in range(N)]
    rows = []
    buckets = [("At or within 5 pts of 26-wk high", 0, 5), ("5-10 pts below", 5, 10), ("10-15 pts below", 10, 15), ("15+ pts below", 15, 999)]
    for lab, a, b in buckets:
        idx = [i for i in range(N) if off[i] is not None and a <= -off[i] < b]
        r = {"label": lab, "weeks": len(idx)}
        for k, v in F.items():
            vals = [v[i] for i in idx if v[i] is not None]
            r[k] = round(S.mean(vals), 2) if vals else None
        rows.append(r)
    cur = off[-1] if off else None
    live = hist[-1].get(key)
    hi = max(x for x in [h.get(key) for h in hist[-27:]] if x is not None)
    return {"buckets": rows, "current_off_high": round(live - hi, 1) if live is not None else None, "high_26w": hi}


def build(cfg):
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    R, st = fetch_all()
    comps, series_status = [], {}
    cats = []
    timelines = {}
    for key, cat, name, unit, freq, vals, srcs, rule, rule_txt, better in components(R):
        if cat not in cats:
            cats.append(cat)
        vals = [(t, round(v, 4)) for t, v in vals]
        sc = score_series(vals, rule) if vals else []
        lag = max(PUB_LAG[x] for x in srcs)
        bad = [x for x in srcs if st.get(x, {}).get("status") != "ok"]
        rec = {"key": key, "cat": cat, "name": name, "unit": unit, "freq": freq, "rule": rule_txt, "better": better,
               "sources": srcs, "pub_lag_days": lag}
        if not vals or sc[-1] is None:
            rec.update(status="failed", signal=None, error="; ".join(st.get(x, {}).get("error", "insufficient history") for x in srcs))
        else:
            lt, lv = vals[-1]
            sig, pct = sc[-1]
            age = (today - D(lt)).days
            # ~4 weeks earlier value for direction
            j = bisect.bisect_right([x[0] for x in vals], (D(lt) - dt.timedelta(days=28)).isoformat()) - 1
            pv = vals[j] if j >= 0 and freq in ("d", "w") else (vals[-2] if len(vals) > 1 else None)
            stale = bool(bad) or age > MAX_AGE[freq] + lag
            rec.update(value=lv, asof=lt, pct=None if pct is None else round(pct), signal=None if stale else sig, raw_signal=sig,
                       prior={"date": pv[0], "value": pv[1]} if pv else None,
                       status="stale" if stale else "ok", start=next(vals[i][0] for i in range(len(sc)) if sc[i] is not None))
            if stale:
                rec["error"] = "; ".join(st[x]["error"] for x in bad if "error" in st[x]) or f"latest observation {lt} is older than the {MAX_AGE[freq]}-day freshness limit"
            # publication-dated signal timeline for history
            timelines[key] = ([(D(vals[i][0]) + dt.timedelta(days=lag)).isoformat() for i in range(len(sc)) if sc[i] is not None],
                              [sc[i][0] for i in range(len(sc)) if sc[i] is not None])
        comps.append(rec)
        series_status[key] = {"fred": "+".join(srcs), "status": rec["status"], "latest": {"date": rec.get("asof"), "value": rec.get("value")},
                              **({"error": rec["error"]} if rec.get("error") else {})}
    cur = diffusion([c["signal"] for c in comps])
    cat_now = {c: diffusion([x["signal"] for x in comps if x["cat"] == c]) for c in cats}

    # weekly point-in-time history (Fridays), latest point = today
    grid, d0 = [], D(HIST_FROM)
    while d0 < today:
        grid.append(d0.isoformat()); d0 += dt.timedelta(days=7)
    EQ_KEYS = {c["key"] for c in comps if c["cat"].startswith("Equity")}
    hist = []
    for g in grid:
        sigs = {}
        for c in comps:
            tl = timelines.get(c["key"])
            if not tl:
                continue
            i = bisect.bisect_right(tl[0], g) - 1
            if i < 0:
                continue
            # drop signals whose latest observation is older than the freshness limit at that date
            if (D(g) - D(tl[0][i])).days > MAX_AGE[c["freq"]]:
                continue
            sigs[c["key"]] = tl[1][i]
        row = {"date": g, "score": diffusion(list(sigs.values())), "n": len(sigs),
               "score_ex": diffusion([v for kk, v in sigs.items() if kk not in EQ_KEYS]),
               "cats": {k: diffusion([v for kk, v in sigs.items() if next(x["cat"] for x in comps if x["key"] == kk) == k]) for k in cats}}
        hist.append(row)
    hist.append({"date": today.isoformat(), "score": cur, "score_ex": diffusion([c["signal"] for c in comps if c["key"] not in EQ_KEYS]), "n": sum(1 for c in comps if c["signal"] is not None), "cats": cat_now, "live": True})
    total = len(comps)
    cov = next((h["date"] for h in hist if h["n"] >= total * 0.75), None)

    def ago(days):
        tgt = (today - dt.timedelta(days=days)).isoformat()
        c = [h for h in hist if h["date"] <= tgt and h["score"] is not None]
        return c[-1] if c else None
    w1, m1 = ago(7), ago(28)
    doc = {"id": cfg["id"], "config": cfg, "updated_at": now.isoformat(timespec="seconds"),
           "current": {"score": cur, "label": label(cur), "n": sum(1 for c in comps if c["signal"] is not None), "total": total,
                       "fav": sum(1 for c in comps if c["signal"] == 1), "neu": sum(1 for c in comps if c["signal"] == 0),
                       "unf": sum(1 for c in comps if c["signal"] == -1),
                       "w1": w1 and {"date": w1["date"], "score": w1["score"]}, "m1": m1 and {"date": m1["date"], "score": m1["score"]}},
           "categories": [{"name": k, "score": cat_now[k], "label": label(cat_now[k]),
                           "n": sum(1 for c in comps if c["cat"] == k and c["signal"] is not None),
                           "total": sum(1 for c in comps if c["cat"] == k)} for k in cats],
           "components": comps, "history": hist, "coverage_from": cov, "sources": st, "series": series_status}
    doc["kre"] = kre_rows(R, hist)
    doc["deterioration"] = deterioration(R, hist)
    lines = ["date,diffusion,components_scored," + ",".join('"' + k + '"' for k in cats)]
    for h in hist:
        lines.append(",".join([h["date"], "" if h["score"] is None else str(h["score"]), str(h["n"])] +
                              ["" if h["cats"][k] is None else str(h["cats"][k]) for k in cats]))
    CSV_PATH.write_text("\n".join(lines) + "\n")
    return doc
