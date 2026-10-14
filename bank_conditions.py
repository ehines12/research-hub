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
            "SUBLPDRCDC", "SUBLPDRCDN", "SUBLPDRCDM", "ICSA", "CORALACBS", "DRALACBS", "NDR12MCD", "FEDFUNDS", "DGS10", "DGS2", "DGS1", "DFF", "MMNDR", "LTDSCBW027SBOG", "H8B3094NSMD",
            "DRCRELEXFACBS", "CORCREXFACBS", "BOGZ1FL075035503Q", "WLCFLL"]
TICKERS = ["KRE", "XLF", "IWM", "SPY", "^MOVE"]
# estimated days from FRED observation date to public release (point-in-time history)
PUB_LAG = {"SOFR": 1, "DGS5": 1, "T10Y2Y": 1, "T10Y3M": 1, "VIXCLS": 1, "BAMLH0A0HYM2": 1, "BAMLC0A4CBBB": 1,
           "LLBSCBW027SBOG": 9, "LLBDCBW027SBOG": 9, "DPSSCBW027SBOG": 9, "NFCI": 5, "STLFSI4": 6, "ICSA": 5,
           "DRTSCILM": 40, "DRSDCILM": 40, "SUBLPDRCSC": 40, "SUBLPDRCSN": 40, "SUBLPDRCSM": 40, "SUBLPDRCDC": 40,
           "SUBLPDRCDN": 40, "SUBLPDRCDM": 40, "CORALACBS": 145, "DRALACBS": 145, "NDR12MCD": 50, "FEDFUNDS": 32,
           "KRE": 0, "XLF": 0, "IWM": 0, "SPY": 0, "^MOVE": 0,
           "DGS10": 1, "DGS2": 1, "UL_ALL": 60, "UL_CB": 60, "DGS1": 1, "DFF": 1, "MMNDR": 50, "LTDSCBW027SBOG": 9, "H8B3094NSMD": 9, "DRCRELEXFACBS": 145,
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


LAGGARD_WHY = "context only, not scored: lagged KRE in the pre-2019 test (forward correlation below -0.10); bad readings tended to arrive after the stock move"
CONTEXT_ONLY = {k: LAGGARD_WHY for k in ("fed_lending", "cre_nco", "cre_px", "sloos_cre_std", "cre_dq", "sloos_cre_dem", "dq",
                                         "sloos_ci_dem", "nco", "sloos_ci_std", "claims")}


def rate12_rule(vals, i):
    """12-month change in bp: a big rise is unfavorable (AOCI, deposit repricing); a big fall is NOT scored favorable (it usually means a growth scare)."""
    v = vals[i][1]
    return -1 if v >= 75 else (1 if -50 <= v <= 25 else 0)


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
        ("ust10_12m", "Rate shock", "10Y Treasury: 12-month change", "bp", "d", _scale(_chg(s("DGS10"), 250), 100), ["DGS10"], rate12_rule,
         "≥ +75bp unfavorable · −50 to +25bp favorable · a larger fall is neutral (usually a growth scare, not a tailwind)", "low"),
        ("ust2_12m", "Rate shock", "2Y Treasury: 12-month change", "bp", "d", _scale(_chg(s("DGS2"), 250), 100), ["DGS2"], rate12_rule,
         "≥ +75bp unfavorable · −50 to +25bp favorable · a larger fall is neutral (policy-path shock)", "low"),
        ("ul_all", "Rate shock", "Unrealized securities gains (−losses), AFS + HTM, % of equity: all insured banks", "%", "q", s("UL_ALL"), ["UL_ALL"],
         band(-2, -8, "high"), "≥ −2% favorable · ≤ −8% unfavorable (FDIC, ~60-day publication lag)", "high"),
        ("ul_cb_4q", "Rate shock", "Community-bank unrealized securities gains (−losses), % of equity: 4-quarter change", "pp", "q", _chg(s("UL_CB"), 4), ["UL_CB"],
         band(0, -3, "high"), "≥ 0 favorable (improving) · ≤ −3pp unfavorable (worsening) (FDIC, ~60-day lag)", "high"),
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


def realtime_signals(R, grid, builders):
    """Per-week signals for components built only from ALFRED-revised series, from the vintage public at each week."""
    import alfred_rt as A
    live = {k: R.get(k, []) for k in A.TAIL}
    try:
        c, st = A.update(grid, live=live)
    except Exception as e:  # noqa
        print(f"  ALFRED update FAILED: {e}")
        c, st = A.load(), {"all": {"status": "failed", "error": str(e)[:200]}}
    keys = [k for k, (srcs, *_r) in builders.items() if srcs and all(x in A.TAIL for x in srcs)]
    out = {k: {} for k in keys}
    cov = {k: 0 for k in keys}
    for g in grid:
        Rv = {}
        for sid in A.TAIL:
            v = A.series_at(c, sid, g)
            if v:
                Rv[sid] = [tuple(x) for x in v]
        if not Rv:
            continue
        built = {row[0]: row for row in components(Rv)}
        for k in keys:
            srcs, rule, freq, lag = builders[k]
            if not all(x in Rv for x in srcs):
                continue          # no vintage for this week: caller falls back to revised data
            vals = [(t, round(v, 4)) for t, v in built[k][5]]
            if not vals:
                out[k][g] = None; continue
            sc = score_series(vals, rule)
            ok = sc[-1] is not None and (D(g) - D(vals[-1][0])).days <= MAX_AGE[freq] + lag
            out[k][g] = sc[-1][0] if ok else None
            cov[k] += 1
    first = {k: min(out[k]) if out[k] else None for k in keys}
    return out, {k: {"weeks_realtime": cov[k], "weeks": len(grid), "from": first[k]} for k in keys}, st


def rate_credit_flag(R, hist):
    """Context flag: ON when the 10Y is up > 50bp over 12 months AND the full Credit subscore (incl. context-only
    inputs) sits deeper below its 26-week high than its pre-2019 20th percentile. Threshold fixed on pre-2019 data."""
    import statistics as S
    H = hist
    dates = [h["date"] for h in H]; N = len(H)
    cr = [h.get("credit_full") for h in H]
    off = [None if cr[i] is None else cr[i] - max(x for x in cr[max(0, i - 26):i + 1] if x is not None) for i in range(N)]
    pre = sorted(o for o, d in zip(off, dates) if o is not None and d < "2019-01-01")
    if len(pre) < 50 or not R.get("DGS10"):
        return None
    th = pre[int(0.2 * len(pre))]
    ds = [t for t, _ in R["DGS10"]]; vs = [v for _, v in R["DGS10"]]
    def ust12(g):
        i = bisect.bisect_right(ds, (D(g) - dt.timedelta(days=1)).isoformat()) - 1
        j = bisect.bisect_right(ds, (D(ds[i]) - dt.timedelta(days=365)).isoformat()) - 1
        return None if i < 0 or j < 0 else round(100 * (vs[i] - vs[j]), 0)
    u = [ust12(g) for g in dates]
    on = [None if off[i] is None or u[i] is None else (u[i] > 50 and off[i] <= th) for i in range(N)]
    # forward outcomes
    def px(k):
        if not R.get(k): return [None] * N
        kd = [t for t, _ in R[k]]; kv = [v for _, v in R[k]]
        return [kv[bisect.bisect_right(kd, g) - 1] for g in dates]
    K, I, X = px("KRE"), px("IWM"), px("XLF")
    kd = [t for t, _ in R["KRE"]]; kv = [v for _, v in R["KRE"]]
    live = [h.get("live") for h in H]
    def f(i, n, B=None):
        if i + n >= N or live[i + n] or K[i] is None: return None
        return 100 * ((K[i + n] / K[i]) / ((B[i + n] / B[i]) if B else 1) - 1)
    def mdd(i):
        if i + 26 >= N or live[i + 26]: return None
        a = bisect.bisect_right(kd, dates[i]) - 1; e = bisect.bisect_right(kd, dates[i + 26])
        return 100 * (min(kv[a:e]) / kv[a] - 1)
    tg = {"rel_iwm_26": lambda i: f(i, 26, I), "rel_xlf_26": lambda i: f(i, 26, X), "abs_26": lambda i: f(i, 26), "mdd_26": mdd}
    stats = []
    for lab, sel in (("In-sample (2012-2018, threshold set here)", lambda d: d < "2019-01-01"), ("Out-of-sample (2019 onward)", lambda d: d >= "2019-01-01")):
        for state in (True, False):
            idx = [i for i in range(N) if on[i] is state and sel(dates[i])]
            r = {"period": lab, "state": "ON" if state else "OFF", "weeks": len(idx)}
            for k, fn in tg.items():
                v = [x for x in (fn(i) for i in idx) if x is not None]
                r[k] = round(S.mean(v), 2) if v else None
            stats.append(r)
    eps, prev = [], False
    for i in range(N):
        if on[i] and not prev:
            eps.append({"date": dates[i], "rel_iwm_26": f(i, 26, I), "abs_26": f(i, 26), "mdd_26": mdd(i)})
        prev = bool(on[i])
    for e in eps:
        for k in ("rel_iwm_26", "abs_26", "mdd_26"):
            e[k] = None if e[k] is None else round(e[k], 1)
    # Confirmed tier: flag ON and the ex-equity index below -15 vs its 26-wk high for >= 6 consecutive weeks
    sx = [h.get("score_ex") for h in H]
    offx = [None if sx[i] is None else sx[i] - max(x for x in sx[max(0, i - 26):i + 1] if x is not None) for i in range(N)]
    streak = []
    for i in range(N):
        b_ = offx[i] is not None and offx[i] <= -15
        streak.append((streak[-1] + 1 if streak and b_ else int(b_)))
    conf = [bool(on[i]) and streak[i] >= 6 for i in range(N)]
    cev = []
    for i in range(N):
        if conf[i] and (i == 0 or not conf[i - 1]):
            r6, m6 = f(i, 26, I), mdd(i)
            cev.append({"date": dates[i], "rel_iwm_26": None if r6 is None else round(r6, 1), "mdd_26": None if m6 is None else round(m6, 1),
                        "abs_26": None if f(i, 26) is None else round(f(i, 26), 1)})
    return {"threshold": round(th, 1), "rate_bp": 50, "current": {"on": on[-1], "ust12_bp": u[-1], "credit_off": None if off[-1] is None else round(off[-1], 1),
            "credit": cr[-1], "date": dates[-1], "streak": streak[-1], "confirmed": conf[-1]},
            "streak_hist": [[d, k] for d, k in zip(dates, streak)], "confirmed_hist": [int(c) for c in conf], "confirmed_events": cev,
            "history": [[d, None if o is None else int(o), None if x is None else round(x, 1), y] for d, o, x, y in zip(dates, on, off, u)],
            "stats": stats, "episodes": eps}


def build(cfg):
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    R, st = fetch_all()
    fwd_raw = fwd_st = None
    try:
        import fwd_context
        fwd_raw, fwd_st = fwd_context.fetch_all()
        S = fwd_context.series(fwd_raw)
        for k, src in (("UL_ALL", "fdic_all"), ("UL_CB", "fdic_cb")):
            if S.get(k):
                R[k] = S[k]; st[k] = dict(fwd_st[src], src="FDIC BankFind financials API")
            else:
                st[k] = {"status": "failed", "error": fwd_st.get(src, {}).get("error", "no data")}
    except Exception as e:  # noqa
        for k in ("UL_ALL", "UL_CB"):
            st[k] = {"status": "failed", "error": str(e)[:200]}
    comps, series_status = [], {}
    cats = []
    timelines = {}
    builders = {}
    for key, cat, name, unit, freq, vals, srcs, rule, rule_txt, better in components(R):
        if cat not in cats:
            cats.append(cat)
        vals = [(t, round(v, 4)) for t, v in vals]
        sc = score_series(vals, rule) if vals else []
        lag = max(PUB_LAG[x] for x in srcs)
        bad = [x for x in srcs if st.get(x, {}).get("status") != "ok"]
        rec = {"key": key, "cat": cat, "name": name, "unit": unit, "freq": freq, "rule": rule_txt, "better": better,
               "sources": srcs, "pub_lag_days": lag, "scored": key not in CONTEXT_ONLY}
        if key in CONTEXT_ONLY:
            rec["context_reason"] = CONTEXT_ONLY[key]
        builders[key] = (srcs, rule, freq, lag)
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
    SC = lambda c: c["signal"] if c["scored"] else None
    cur = diffusion([SC(c) for c in comps])
    cat_now = {c: diffusion([SC(x) for x in comps if x["cat"] == c]) for c in cats}

    # weekly point-in-time history (Fridays), latest point = today
    grid, d0 = [], D(HIST_FROM)
    while d0 < today:
        grid.append(d0.isoformat()); d0 += dt.timedelta(days=7)
    EQ_KEYS = {c["key"] for c in comps if c["cat"].startswith("Equity")}
    rt, rt_cov, rt_status = realtime_signals(R, grid, builders)
    catof = {c["key"]: c["cat"] for c in comps}
    hist = []
    for g in grid:
        sigs = {}
        for c in comps:
            k = c["key"]
            if k in rt and g in rt[k]:
                if rt[k][g] is not None:
                    sigs[k] = rt[k][g]
                continue
            tl = timelines.get(k)
            if not tl:
                continue
            i = bisect.bisect_right(tl[0], g) - 1
            if i < 0:
                continue
            # drop signals whose latest observation is older than the freshness limit at that date
            if (D(g) - D(tl[0][i])).days > MAX_AGE[c["freq"]]:
                continue
            sigs[k] = tl[1][i]
        scd = {k: v for k, v in sigs.items() if k not in CONTEXT_ONLY}
        row = {"date": g, "score": diffusion(list(scd.values())), "n": len(scd),
               "score_ex": diffusion([v for kk, v in scd.items() if kk not in EQ_KEYS]),
               "credit_full": diffusion([v for kk, v in sigs.items() if catof[kk] == "Credit"]),
               "cats": {k: diffusion([v for kk, v in scd.items() if catof[kk] == k]) for k in cats}}
        hist.append(row)
    hist.append({"date": today.isoformat(), "score": cur, "score_ex": diffusion([SC(c) for c in comps if c["key"] not in EQ_KEYS]),
                 "credit_full": diffusion([c["signal"] for c in comps if c["cat"] == "Credit"]),
                 "n": sum(1 for c in comps if SC(c) is not None), "cats": cat_now, "live": True})
    total = sum(1 for c in comps if c["scored"])
    cov = next((h["date"] for h in hist if h["n"] >= total * 0.75), None)

    def ago(days):
        tgt = (today - dt.timedelta(days=days)).isoformat()
        c = [h for h in hist if h["date"] <= tgt and h["score"] is not None]
        return c[-1] if c else None
    w1, m1 = ago(7), ago(28)
    doc = {"id": cfg["id"], "config": cfg, "updated_at": now.isoformat(timespec="seconds"),
           "current": {"score": cur, "label": label(cur), "n": sum(1 for c in comps if SC(c) is not None), "total": total,
                       "fav": sum(1 for c in comps if SC(c) == 1), "neu": sum(1 for c in comps if SC(c) == 0),
                       "unf": sum(1 for c in comps if SC(c) == -1), "context_only": len(comps) - total,
                       "w1": w1 and {"date": w1["date"], "score": w1["score"]}, "m1": m1 and {"date": m1["date"], "score": m1["score"]}},
           "categories": [{"name": k, "score": cat_now[k], "label": label(cat_now[k]),
                           "n": sum(1 for c in comps if c["cat"] == k and SC(c) is not None),
                           "total": sum(1 for c in comps if c["cat"] == k and c["scored"]),
                           "context": sum(1 for c in comps if c["cat"] == k and not c["scored"])} for k in cats],
           "components": comps, "history": hist, "coverage_from": cov, "sources": st, "series": series_status}
    doc["realtime"] = {"coverage": rt_cov, "status": rt_status}
    doc["kre"] = kre_rows(R, hist)
    doc["flag"] = rate_credit_flag(R, hist)
    doc["deterioration"] = deterioration(R, hist)
    lines = ["date,diffusion,components_scored," + ",".join('"' + k + '"' for k in cats)]
    for h in hist:
        lines.append(",".join([h["date"], "" if h["score"] is None else str(h["score"]), str(h["n"])] +
                              ["" if h["cats"][k] is None else str(h["cats"][k]) for k in cats]))
    CSV_PATH.write_text("\n".join(lines) + "\n")
    return doc
